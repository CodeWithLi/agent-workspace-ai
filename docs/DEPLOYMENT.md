# 部署说明

## Docker Compose

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
```

服务：PostgreSQL、Redis、MinIO、etcd、Milvus、FastAPI、Nginx/Vue。后端容器先执行 `alembic upgrade head`，成功后才启动 Uvicorn；`/health/ready` 检查 PostgreSQL、Redis、MinIO、Milvus、LLM 和 SMTP 状态。

复杂 PDF、扫描件和版面表格可启用隔离的 Docling Serve CPU 服务：

```bash
docker compose --profile advanced-rag up -d docling
```

将 `RAG_PARSER_BACKEND=auto` 和 `DOCLING_SERVE_URL=http://docling:5001` 配置给 API。`auto` 在 Docling 不可用时按 `RAG_PARSER_FALLBACK_ENABLED` 决定是否降级到原生解析。Docling CPU 镜像约 4.4 GB，应单独设置 CPU/内存限制，不要安装进 API 镜像。

## 生产配置

```env
ENVIRONMENT=production
AUTO_CREATE_SCHEMA=false
SECRET_KEY=<至少32字符的随机值>
FIRST_SUPERUSER_EMAIL=admin@company.com
ALLOW_REGISTRATION=false
REGISTRATION_EMAIL_DOMAINS=["company.com"]
TRUSTED_HOSTS=["ai.company.com"]
LLM_API_KEY=...
LLM_FALLBACK_ENABLED=false
STORAGE_FALLBACK_ENABLED=false
VECTOR_FALLBACK_ENABLED=false
EMBEDDING_API_KEY=...
EMBEDDING_BASE_URL=...
EMBEDDING_MODEL=...
RAG_CHUNK_OVERLAP_TOKENS=100
RAG_MULTI_VECTOR_ENABLED=true
MILVUS_COLLECTION=knowledge_chunks_v4
RERANKER_ENABLED=true
RERANKER_BASE_URL=http://reranker:8080/rerank
RERANKER_MODEL=bge-reranker-v2-m3
RAG_PARSER_BACKEND=auto
DOCLING_SERVE_URL=http://docling:5001
SMTP_HOST=smtp.company.com
SMTP_PORT=587
SMTP_USERNAME=...
SMTP_PASSWORD=...
SMTP_FROM_EMAIL=ai@company.com
WELCOME_AI_TOKENS=1000
CHAT_TOKEN_COST=10
DISCUSSION_TOKEN_COST=50
WORKFLOW_TOKEN_COST=100
RECHARGE_TOKENS_PER_YUAN=100
AGENT_CONCURRENCY_ACQUIRE_TIMEOUT=3
AGENT_CONCURRENCY_LEASE_SECONDS=180
WORKFLOW_WORKER_ENABLED=true
WORKFLOW_POLL_SECONDS=1
WORKFLOW_LEASE_SECONDS=900
WORKFLOW_MAX_ATTEMPTS=2
PROTOTYPE_GENERATION_WORKER_ENABLED=true
PROTOTYPE_GENERATION_POLL_SECONDS=1
PROTOTYPE_GENERATION_LEASE_SECONDS=300
PROTOTYPE_GENERATION_MAX_ATTEMPTS=3
PROTOTYPE_GENERATION_RETRY_BASE_SECONDS=5
PROTOTYPE_GENERATION_RETRY_MAX_SECONDS=300
PROTOTYPE_GENERATION_SHUTDOWN_GRACE_SECONDS=15
POSTGRES_PASSWORD=...
DATABASE_URL=postgresql+psycopg://postgres:<url-encoded-password>@postgres:5432/agent_workspace_ai
MINIO_ACCESS_KEY=...
MINIO_SECRET_KEY=...
```

生产配置不满足上述安全约束时，应用会拒绝启动。refresh token 仅写入 `HttpOnly + Secure + SameSite=Lax` cookie，access token 默认 30 分钟，refresh 会话默认 30 天且每次刷新轮换。

通知 worker 默认随 API 进程启动。多副本通过 PostgreSQL `FOR UPDATE SKIP LOCKED` 争抢任务；邮件失败按指数退避重试。生产环境必须配置 SMTP，并监控 `notification.failed` 审计事件。

工作流 dispatcher 同样支持多副本认领。租约应大于单个模型调用的最长超时；滚动发布时实例会等待当前节点完成，异常退出后的任务由其他实例从最后一个已提交节点恢复。

AI 原型生成使用独立的持久化 dispatcher。API 只负责把任务写入 PostgreSQL 并返回 `202`；worker 通过带 fencing token 的租约认领任务，阶段进度和终态由 SSE 恢复。租约心跳必须持续运行，`PROTOTYPE_GENERATION_LEASE_SECONDS` 应大于心跳间隔并覆盖短暂数据库抖动；滚动发布超过关机宽限后，未完成任务会由其他实例在租约过期后接管。生产环境应监控原型任务队列、失败率、重试次数和租约恢复事件。

管理员可在系统设置页覆盖模型、Embedding、RAG、计费、注册、通知与运行控制参数。数据库、Redis、MinIO、Milvus 地址及 `SECRET_KEY` 属于启动级配置，只能由部署环境提供。运行时密钥使用 `SECRET_KEY` 派生密钥加密保存，轮换 `SECRET_KEY` 前必须先清除或重新写入这些密钥。多副本每 15 秒刷新一次数据库覆盖值。

当前 Milvus 混合检索 schema 使用 collection `knowledge_chunks_v4`，包含 child dense、parent dense、BM25 sparse、原文、`owner_id` 和 `index_version` 字段。`owner_id` 是个人知识库 ANN 阶段的强制过滤条件，不能依赖数据库二次过滤代替。旧 collection 不能原地兼容：发布时创建新 collection，保留 PostgreSQL `embeddings.vector_json` 和 `parent_vector_json`，再通过知识库重建操作逐文档回填；启用多向量前必须完成重建并验证新 collection，之后才能删除旧 collection。生产环境 `VECTOR_FALLBACK_ENABLED=false`，任何 Milvus 写入失败都必须让新索引保持未激活状态。

Python 管理后台使用 `/admin`，仅 `admin` 角色可登录。它使用 8 小时 HttpOnly Cookie、`SameSite=Strict` 和 CSRF Token。生产入口必须使用 HTTPS，并限制后台网络来源。

## 发布检查

```bash
cd backend
pytest -q
alembic upgrade head
alembic check
cd ..
python scripts/evaluate_rag_chunking.py --enforce-gates --output .run/rag-evaluation.json

cd frontend
npm ci
npm run lint
npm run typecheck
npm run test:coverage
npm run build
npm run test:e2e

docker compose -f docker-compose.yml -f docker-compose.prod.yml config
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

GitHub Actions 还包含以下 RAG 专用门禁：

- `CI / rag-integration`：自动启动真实 PostgreSQL 与 Milvus，验证 hybrid schema、个人数据隔离、4 并发查询和 p95 `<= 3000 ms`。
- `RAG Docling Integration`：手动或每周运行真实 Docling DOCX 表格与扫描 PDF OCR。
- `RAG Parser Benchmark`：手动或每月在相同语料哈希上比较 native、Docling、Unstructured 与 MinerU，并保留质量、延迟、内存和部署体积报告。
- `RAG External Quality Gate`：手动运行真实 embedding/reranker/LLM judge。仓库需要配置 `RAG_EVAL_LLM_*`、`RAG_EVAL_EMBEDDING_*`、`RAG_EVAL_RERANKER_*` 和可选 `RAG_EVAL_JUDGE_MODEL` secrets；成本单价和 embedding 维度使用同名前缀的 repository variables。

外部质量工作流的默认门槛为 Recall@5 `>= 0.8`、Faithfulness `>= 0.9`、judge 引用正确率 `>= 0.95`、拒答准确率 `= 1.0`、端到端 p95 `<= 5000 ms`。未配置 secrets、启用 fallback、judge 返回非严格 JSON 或 reranker 健康检查失败都会以非零退出码失败。

当前开发机器若无 Docker CLI，只能完成代码、迁移和本地 HTTP 验证；正式发布必须在有 Docker 的主机执行最后两条命令，并确认所有容器 healthy。

RAG 发布还必须使用脱敏的真实 PDF/DOCX/Markdown/扫描件跑解析与检索 A/B，验证跨语言 embedding、外部 reranker、Docling OCR、Milvus hybrid、引用忠实度和 p95 延迟。仓库内稀疏基线只用于确定性回归，不能替代这些发布门禁。

生产 overlay 移除 PostgreSQL、Redis、MinIO、Milvus 与 API 的宿主机端口，强制关键密钥、禁用降级、限制资源并将 API 根文件系统设为只读。HTTPS 由 frontend 前置的可信反向代理或负载均衡器终止。

日志、指标、告警建议与备份恢复步骤见 [OPERATIONS.md](OPERATIONS.md)。
