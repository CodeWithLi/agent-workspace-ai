# Agent Workspace AI

企业级 AI 数字员工项目协作平台。支持真实项目成员权限、8 类 AI 员工、连续会话、工具执行、多 Agent 工作流、混合 RAG、任务、会议、报告和审计日志。

## 技术栈

- 前端：Vue 3、Vite、TypeScript、Element Plus、Pinia、Vue Router、Axios、ECharts、Markdown、SSE
- 后端：FastAPI、SQLAlchemy、Pydantic、Alembic
- AI：统一 OpenAI-compatible LLM Gateway、LangChain、LangGraph
- 数据：PostgreSQL、Redis、Milvus、MinIO
- 部署：Docker Compose、Nginx

## 一键启动

```bash
cp .env.example .env
docker compose up --build
```

访问地址：

- 前端：http://localhost:5173
- Swagger：http://localhost:8000/docs
- MinIO 控制台：http://localhost:9001

开发环境未配置 `LLM_API_KEY` 时会启用明确标识的本地回退，便于完整走通业务。连接智谱 GLM：

```env
LLM_PROVIDER=zhipu
LLM_API_KEY=your-key
LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
LLM_MODEL=glm-4-flash
EMBEDDING_MODEL=embedding-3
```

## 关键设计

- 认证：30 分钟 JWT access token；HttpOnly refresh cookie；服务端会话轮换、撤销和审计。
- 项目协作：`owner/editor/viewer` 权限；项目级任务、Agent、工作流和知识库统一鉴权。
- Agent 路由：显式选择优先；明确角色名优先；加权意图匹配；会话开始后固定角色，防止漂移。
- 工具安全：代码硬白名单与数据库白名单取交集；禁用工具不会配置回退；写工具要求明确动作意图。
- Memory：短期上下文有字符预算；项目记忆固定窗口；每个项目/Agent 仅一条滚动摘要。
- RAG：BM25 风格稀疏检索 + embedding dense 检索 + Milvus ANN + 排名融合 + 阈值过滤 + 引用。
- 存储：MinIO 对象生命周期；开发可显式回退本地；删除文档同步清理对象和 Milvus 数据。
- 数据库：Alembic 静态基线迁移；Docker 启动 API 前自动执行 `alembic upgrade head`。
- 可观测性：健康/就绪探针、安全响应头、结构化日志、管理员审计日志。

## 本地开发

```bash
cd backend
pip install -r requirements.txt
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

```bash
cd frontend
npm install
npm run dev
```

验证：

```bash
cd backend
pytest -q
alembic upgrade head
alembic check

cd ../frontend
npm run build
```

## 文档

架构、API、Agent、LangGraph、RAG、数据库和部署说明见 [`docs/`](docs/)。
