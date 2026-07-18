# Agent Workspace AI

企业级 AI 数字员工项目协作平台。支持真实项目成员权限、8 类 AI 员工、连续会话、可见的多 AI 团队讨论、可审批工具执行、多 Agent 工作流、混合 RAG、Token 钱包、任务、会议、通知、报告和审计日志。

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
- 团队讨论：产品经理、架构师、测试工程师、运营分析师依次评审共享上下文，项目经理裁决冲突并生成最终方案；讨论阶段不执行写工具。
- 工具安全：代码硬白名单与数据库白名单取交集；禁用工具不会配置回退；写工具要求明确动作意图，敏感 Agent 的任务写入先生成幂等审批单。
- Agent 并发：Redis 租约信号量提供跨进程并发上限并周期续租，Redis 不可用时退化为按 Agent 隔离的动态本地限流器；运行记录可审计，僵死运行自动退款。
- Token：新用户赠送额度、固定成本预扣、余额原子更新、失败幂等退款、模拟充值和完整流水。
- 多 Agent：各 StateGraph 节点读取对应 Agent 的 Prompt、模型和并发策略；运行中可请求在已提交节点边界安全暂停，将操作员恢复指令传递给后续全部 Agent；失败重试创建不可变子运行并保留父运行证据、独立计费和检查点谱系。
- 受治理的动态编排：Planner 生成结构化角色、依赖、交付物和成功标准，服务端校验无环 DAG，并按拓扑波次执行同波并行 Agent、向下游注入直接上游 Handoff；每个尝试批次提交耐久检查点，瞬时 provider/并发错误只对失败 Agent 执行有界指数退避，确定性错误才升级到 worker 恢复，成功分支不会重复。项目页可审查波次后再批准，并从持久化事件恢复每个 Agent 的执行、重试、失败、检查点恢复和交接状态；重规划追加不可变版本，可比较、批准或基于任一历史版本继续修订，上游返修会自动传播到全部下游。
- Prompt 调优：管理员可把门禁失败证据交给 Optimizer Agent 生成提案，再由独立 Reviewer Agent 与确定性规则检查角色漂移、注入、工具越权、评测迎合和治理绕过；拒绝意见会触发有界返修，通过后只创建草稿，仍须 Challenger 评测才能发布。
- Saga 一致性：工作流冻结 Agent 配置并逐级交接真实产物；写工具使用持久化执行日志、幂等键、租约 fencing 和逆序补偿，回滚冲突进入人工处理而不是交给模型猜测。
- Memory：短期上下文有字符预算；项目记忆固定窗口；每个项目/Agent 仅一条滚动摘要。
- RAG：BM25 风格稀疏检索 + embedding dense 检索 + Milvus ANN + 排名融合 + 阈值过滤 + 引用。
- 存储：MinIO 对象生命周期；开发可显式回退本地；删除文档同步清理对象和 Milvus 数据。
- 数据库：Alembic 静态基线迁移；Docker 启动 API 前自动执行 `alembic upgrade head`。
- 可观测性：健康/就绪探针、结构化日志、运行追踪、跨运行基线对比、可热更新 SLO、错误预算、MAD 异常检测、持久化告警处理闭环和管理员审计日志。
- 通知：站内通知和 SMTP 邮件异步投递、定时发送、失败重试、锁超时恢复和取消。

## 本地开发

本机单独安装 PostgreSQL、Redis、Milvus 和 MinIO 时，使用精简依赖配置：

```powershell
Copy-Item backend/dependencies.env.example backend/dependencies.env
```

Linux/macOS：

```bash
cp backend/dependencies.env.example backend/dependencies.env
```

通常只需修改文件中的 `CHANGE_ME`。Redis、Milvus 使用默认本机端口；需要邮件通知时再填写四项 SMTP 配置。`dependencies.env` 已被 Git 忽略，后端会在 `.env` 之后自动读取它。

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
npm ci
npm run lint
npm run typecheck
npm run test:coverage
npm run build
npm run test:e2e
```

仓库 CI 使用 PostgreSQL 16 实跑 Alembic 至最新版本，并对前端桌面与 390px 移动视口执行核心 Playwright 流程。

## 文档

架构、API、Agent、LangGraph、RAG、数据库和部署说明见 [`docs/`](docs/)。
