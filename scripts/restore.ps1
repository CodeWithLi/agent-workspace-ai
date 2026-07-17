param(
    [Parameter(Mandatory = $true)][string]$BackupPath,
    [string]$ComposeProject = "agent-workspace-ai",
    [string]$MinioAccessKey = $env:MINIO_ACCESS_KEY,
    [string]$MinioSecretKey = $env:MINIO_SECRET_KEY,
    [string]$MinioBucket = "agent-workspace",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$source = [System.IO.Path]::GetFullPath($BackupPath)
if (-not $Force) {
    throw "Restore replaces current PostgreSQL and MinIO data. Re-run with -Force after verification."
}
if (-not (Test-Path -LiteralPath (Join-Path $source "postgres.dump"))) {
    throw "postgres.dump is missing from backup path"
}

docker compose -f docker-compose.yml -f docker-compose.prod.yml cp `
    (Join-Path $source "postgres.dump") postgres:/tmp/agent-workspace.dump
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres `
    dropdb -U postgres --if-exists agent_workspace_ai
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres `
    createdb -U postgres agent_workspace_ai
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres `
    pg_restore -U postgres -d agent_workspace_ai --clean --if-exists /tmp/agent-workspace.dump
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres `
    rm -f /tmp/agent-workspace.dump

$network = "${ComposeProject}_default"
$minioSource = (Join-Path $source "minio")
docker run --rm --network $network -v "${minioSource}:/backup:ro" --entrypoint /bin/sh minio/mc `
    -c "mc alias set target http://minio:9000 '$MinioAccessKey' '$MinioSecretKey' && mc mirror --overwrite --remove /backup target/$MinioBucket"

docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T backend alembic upgrade head
Write-Output "Restore completed. Reindex knowledge documents from the admin UI to rebuild Milvus."
