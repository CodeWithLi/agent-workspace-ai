param(
    [string]$BackupRoot = ".\backups",
    [string]$ComposeProject = "agent-workspace-ai",
    [string]$MinioAccessKey = $env:MINIO_ACCESS_KEY,
    [string]$MinioSecretKey = $env:MINIO_SECRET_KEY,
    [string]$MinioBucket = "agent-workspace"
)

$ErrorActionPreference = "Stop"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$target = Join-Path ([System.IO.Path]::GetFullPath($BackupRoot)) $timestamp
New-Item -ItemType Directory -Path $target -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $target "minio") -Force | Out-Null

docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres `
    pg_dump -U postgres -d agent_workspace_ai -Fc -f /tmp/agent-workspace.dump
docker compose -f docker-compose.yml -f docker-compose.prod.yml cp `
    postgres:/tmp/agent-workspace.dump (Join-Path $target "postgres.dump")
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres `
    rm -f /tmp/agent-workspace.dump

$network = "${ComposeProject}_default"
$minioTarget = (Join-Path $target "minio")
docker run --rm --network $network -v "${minioTarget}:/backup" --entrypoint /bin/sh minio/mc `
    -c "mc alias set source http://minio:9000 '$MinioAccessKey' '$MinioSecretKey' && mc mirror --overwrite source/$MinioBucket /backup"

@{
    created_at = (Get-Date).ToUniversalTime().ToString("o")
    database = "postgres.dump"
    minio_bucket = $MinioBucket
} | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $target "manifest.json")

Write-Output "Backup completed: $target"
