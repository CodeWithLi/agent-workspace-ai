# Agent Workspace AI

企业级 AI 数字员工项目协作平台。支持真实项目成员权限、8 类 AI 员工、连续会话、可审批工具执行、多 Agent 工作流、混合 RAG、Token 钱包、任务、会议、通知、报告和审计日志。

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
- Python 管理后台：http://localhost:8000/admin
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
- 项目协作：`owner/editor/viewer` 项目角色叠加 `agents:read/projects:write/knowledge:write` 全局权限。
- Agent 路由：显式选择优先；明确角色名优先；加权意图匹配；会话开始后固定角色，防止漂移。
- 工具安全：代码硬白名单与数据库白名单取交集；禁用工具不会配置回退；写工具要求明确动作意图，敏感 Agent 的任务写入先生成幂等审批单。
- Agent 并发：Redis 租约信号量提供跨进程并发上限并周期续租，Redis 不可用时退化为按 Agent 隔离的动态本地限流器；运行记录可审计，僵死运行自动退款。
- Token：新用户赠送额度、固定成本预扣、余额原子更新、失败幂等退款、模拟充值和完整流水。
- 多 Agent：各 StateGraph 节点读取对应 Agent 的 Prompt、模型和并发策略；同一项目只允许一条未结束工作流，暂停时可按产物评审后继续。
- Memory：短期上下文有字符预算；项目记忆固定窗口；每个项目/Agent 仅一条滚动摘要。
- RAG：BM25 风格稀疏检索 + embedding dense 检索 + Milvus ANN + 排名融合 + 阈值过滤 + 引用。
- 存储：MinIO 对象生命周期；开发可显式回退本地；删除文档同步清理对象和 Milvus 数据。
- 数据库：Alembic 静态基线迁移；Docker 启动 API 前自动执行 `alembic upgrade head`。
- 可观测性：健康/就绪探针、安全响应头、结构化日志、管理员审计日志。
- 通知：站内通知和 SMTP 邮件异步投递、定时发送、失败重试、锁超时恢复和取消。

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
