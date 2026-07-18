# Operations Runbook

## Signals

- Liveness: `GET /health/live` only proves that the API process can serve requests.
- Readiness: `GET /health/ready` checks PostgreSQL, Redis, MinIO, Milvus, LLM configuration/connectivity and optional SMTP connectivity.
- Metrics: `GET /metrics` exposes HTTP rate/latency/in-progress requests plus workflow, knowledge and notification queue gauges.
- Every HTTP response includes `X-Request-ID`; application logs are one JSON object per line with the same ID.

Alert on sustained readiness failures, HTTP 5xx rate, p95 latency, `FAILED` queue states, workflows stuck in `RUNNING`, documents stuck in `INDEXING`, notification failures, database storage and backup age. Treat any `COMPENSATION_FAILED` workflow or non-zero `agent_workspace_saga_steps{status="COMPENSATION_FAILED"}` as a business-consistency incident. Track `agent_workspace_saga_compensation_duration_seconds` for rollback latency.

RAG-specific metrics are `agent_workspace_rag_index_duration_seconds`, `agent_workspace_rag_index_chunks`, `agent_workspace_rag_embedding_chunks_total`, `agent_workspace_rag_search_duration_seconds`, `agent_workspace_rag_search_results`, `agent_workspace_rag_query_rewrite_total` and `agent_workspace_rag_reranker_total`. The embedding counter's `source` label distinguishes `generated`, `reused`, `generated_parent`, and `reused_parent`; a same-content reindex should reuse both child and parent vectors. Alert on a rising `failed`/`fallback` ratio, search p95 above the deployment SLO, indexing timeouts, or a sustained zero-result increase. Correlate provider cost and token volume through `llm_usage.operation` values `embedding`, `query_rewrite` and `rerank`.

## RAG Reindex And Rollback

1. Run `python scripts/evaluate_rag_chunking.py --enforce-gates --output .run/rag-evaluation.json` and retain the report with the release artifact. The command exits non-zero on retrieval regression, insufficient Context Precision gain, lost heading metadata, token growth or p95 over 100 ms.
2. Trigger `POST /api/v1/knowledge/documents/{id}/reindex` with a unique `request_id`. The current `ACTIVE` version must remain queryable while the new version is `STAGING`.
3. Wait for `INDEXED`, then inspect `GET /api/v1/knowledge/documents/{id}/index-versions` and a fixed set of search/citation probes. Do not activate a `FAILED` version.
4. To roll back, call `POST /api/v1/knowledge/documents/{id}/index-versions/{version}/activate`. Confirm that the target is `ACTIVE`, the previous version is `SUPERSEDED`, and search results report the expected `index_version`.
5. If activation fails while Milvus is strict, keep the current version active, repair Milvus, and retry. Do not edit version statuses directly in PostgreSQL.

After a Milvus schema change or restore, treat PostgreSQL `embeddings` as the source of truth, create a new collection name, and reindex all documents. For the v4 multi-vector schema, verify that `parent_vector_json` is populated before enabling `RAG_MULTI_VECTOR_ENABLED`. Delete the old collection only after tenant-isolation probes, result counts, citations and rollback have passed.

## RAG Release Evidence

Every RAG release must retain three artifacts or links: the deterministic `.run/rag-evaluation.json`, a green `CI / rag-integration` run, and both `.run/rag-end-to-end-baseline.json` and `.run/rag-end-to-end.json` from `RAG External Quality Gate`. The candidate report must contain a passing `ab_comparison`, not only absolute scores. Releases that change parsing or OCR also require a green `RAG Docling Integration` run and `.run/rag-parser-comparison.json` from `RAG Parser Benchmark`; all four backend reports must share one corpus hash. A skipped workflow, local fallback result, missing backend/resource metric, or configuration-error report is not passing evidence.

The external report contains per-case retrieved citations and answers. Review judge reasons for every failed case; do not lower thresholds until the underlying retrieval or grounding failure is understood. Treat answers, retrieved document text and judge output as potentially sensitive and keep artifacts private with the configured 30-day retention.

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
