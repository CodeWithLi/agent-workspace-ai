# 部署说明

## Docker Compose

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
```

服务：PostgreSQL、Redis、MinIO、etcd、Milvus、FastAPI、Nginx/Vue。后端容器先执行 `alembic upgrade head`，成功后才启动 Uvicorn；`/health/ready` 检查 PostgreSQL、Redis、MinIO、Milvus、LLM 和 SMTP 状态。

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
POSTGRES_PASSWORD=...
DATABASE_URL=postgresql+psycopg://postgres:<url-encoded-password>@postgres:5432/agent_workspace_ai
MINIO_ACCESS_KEY=...
MINIO_SECRET_KEY=...
```

生产配置不满足上述安全约束时，应用会拒绝启动。refresh token 仅写入 `HttpOnly + Secure + SameSite=Lax` cookie，access token 默认 30 分钟，refresh 会话默认 30 天且每次刷新轮换。

通知 worker 默认随 API 进程启动。多副本通过 PostgreSQL `FOR UPDATE SKIP LOCKED` 争抢任务；邮件失败按指数退避重试。生产环境必须配置 SMTP，并监控 `notification.failed` 审计事件。

工作流 dispatcher 同样支持多副本认领。租约应大于单个模型调用的最长超时；滚动发布时实例会等待当前节点完成，异常退出后的任务由其他实例从最后一个已提交节点恢复。

管理员可在系统设置页覆盖模型、Embedding、RAG、计费、注册、通知与运行控制参数。数据库、Redis、MinIO、Milvus 地址及 `SECRET_KEY` 属于启动级配置，只能由部署环境提供。运行时密钥使用 `SECRET_KEY` 派生密钥加密保存，轮换 `SECRET_KEY` 前必须先清除或重新写入这些密钥。多副本每 15 秒刷新一次数据库覆盖值。

Python 管理后台使用 `/admin`，仅 `admin` 角色可登录。它使用 8 小时 HttpOnly Cookie、`SameSite=Strict` 和 CSRF Token。生产入口必须使用 HTTPS，并限制后台网络来源。

## 发布检查

```bash
cd backend
pytest -q
alembic upgrade head
alembic check

cd ../frontend
npm ci
npm run lint
npm run typecheck
npm run test:coverage
npm run build
npm run test:e2e

docker compose -f docker-compose.yml -f docker-compose.prod.yml config
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

当前开发机器若无 Docker CLI，只能完成代码、迁移和本地 HTTP 验证；正式发布必须在有 Docker 的主机执行最后两条命令，并确认所有容器 healthy。

生产 overlay 移除 PostgreSQL、Redis、MinIO、Milvus 与 API 的宿主机端口，强制关键密钥、禁用降级、限制资源并将 API 根文件系统设为只读。HTTPS 由 frontend 前置的可信反向代理或负载均衡器终止。

日志、指标、告警建议与备份恢复步骤见 [OPERATIONS.md](OPERATIONS.md)。
