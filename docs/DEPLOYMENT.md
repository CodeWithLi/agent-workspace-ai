# 部署说明

## Docker Compose

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
```

服务：PostgreSQL、Redis、MinIO、etcd、Milvus、FastAPI、Nginx/Vue。后端容器先执行 `alembic upgrade head`，成功后才启动 Uvicorn；`/health/ready` 检查 PostgreSQL 和 Redis。

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
EMBEDDING_API_KEY=...
SMTP_HOST=smtp.company.com
SMTP_PORT=587
SMTP_USERNAME=...
SMTP_PASSWORD=...
SMTP_FROM_EMAIL=ai@company.com
```

生产配置不满足上述安全约束时，应用会拒绝启动。refresh token 仅写入 `HttpOnly + Secure + SameSite=Lax` cookie，access token 默认 30 分钟，refresh 会话默认 30 天且每次刷新轮换。

通知 worker 默认随 API 进程启动。多副本通过 PostgreSQL `FOR UPDATE SKIP LOCKED` 争抢任务；邮件失败按指数退避重试。生产环境必须配置 SMTP，并监控 `notification.failed` 审计事件。

## 发布检查

```bash
cd backend
pytest -q
alembic upgrade head
alembic check

cd ../frontend
npm ci
npm run build

docker compose config
docker compose up -d --build
```

当前开发机器若无 Docker CLI，只能完成代码、迁移和本地 HTTP 验证；正式发布必须在有 Docker 的主机执行最后两条命令，并确认所有容器 healthy。
