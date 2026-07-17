# Operations Runbook

## Signals

- Liveness: `GET /health/live` only proves that the API process can serve requests.
- Readiness: `GET /health/ready` checks PostgreSQL, Redis, MinIO, Milvus, LLM configuration/connectivity and optional SMTP connectivity.
- Metrics: `GET /metrics` exposes HTTP rate/latency/in-progress requests plus workflow, knowledge and notification queue gauges.
- Every HTTP response includes `X-Request-ID`; application logs are one JSON object per line with the same ID.

Alert on sustained readiness failures, HTTP 5xx rate, p95 latency, `FAILED` queue states, workflows stuck in `RUNNING`, documents stuck in `INDEXING`, notification failures, database storage and backup age. Treat any `COMPENSATION_FAILED` workflow or non-zero `agent_workspace_saga_steps{status="COMPENSATION_FAILED"}` as a business-consistency incident. Track `agent_workspace_saga_compensation_duration_seconds` for rollback latency.

## Saga Compensation Incident

1. Open the project workflow and locate the failed Saga step. Do not edit the workflow status directly.
2. Compare `input_json`, `output_json`, and `transition_log_json` with the current business resource.
3. If a user changed a Saga-created resource, decide whether to preserve it or restore the recorded snapshot. For irreversible external actions, execute the registered business counter-operation.
4. Call `POST /api/v1/workflow/{id}/retry-compensation`. Success moves the workflow to its intended terminal state, `FAILED` or `CANCELLED`, and releases the project workflow lock.
5. If compensation still fails, keep the project locked and retain the audit trail for manual reconciliation.

Automatic compensation attempts are limited by `WORKFLOW_COMPENSATION_MAX_ATTEMPTS`. Billing is refunded even when reconciliation remains pending; a successful refund does not mean business rollback succeeded.

## Production Start

```powershell
docker compose -f docker-compose.yml -f docker-compose.prod.yml config
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

The production overlay requires PostgreSQL, MinIO, application and LLM secrets, removes host ports for data services and the API, disables local fallbacks, makes the API filesystem read-only and applies resource limits. Terminate HTTPS at a trusted reverse proxy or load balancer in front of the frontend.

## Backup And Restore

```powershell
.\scripts\backup.ps1
.\scripts\restore.ps1 -BackupPath .\backups\YYYYMMDD-HHMMSS -Force
```

Backups contain a PostgreSQL custom-format dump and the MinIO bucket. Store backup directories encrypted outside the application host. Milvus is derived from PostgreSQL document chunks and can be rebuilt with the knowledge reindex action after restore.

Perform a restore drill before first production release and at least quarterly. Verify user login, project counts, a document download, knowledge reindex, one chat request, queue completion and audit continuity. Keep database and object snapshots from the same backup run.
