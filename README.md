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
- 需求共识合同：产品经理不再向下游传递固定“登录/项目空间/知识库”模板，而是生成带稳定 `AC-xx` 验收编号、范围、约束、假设和证据要求的严格合同；架构师与测试工程师在彼此不可见意见下分别签署可行性和可验收性评审。合法质疑只允许产品经理修订一次，原样或无效修订被 SHA-256 指纹门禁拒绝；最终仍有质疑时即使调用方关闭审批，也会强制进入人工计划门禁。项目页可渐进查看初始质疑、最终签署和验收证据。
- 受治理的动态编排：工作流按发起者冻结工具、知识权限和并发额度，服务端据此生成能力目录；Planner 从交付完整性、风险控制和并行效率三个彼此隔离的视角生成候选，先经过能力、角色、成功合同、并行效率和交付防线五项确定性评分，再由架构师 Agent 在已验证候选中仲裁，非法候选与无效仲裁输出都不能绕过代码门禁。同项目终态运行还会形成冻结的 Team Performance Profile：只有与当前 Agent ID、Prompt、模型、工具、知识/记忆权限和并发配置一致的样本可参与，旧配置或不可验证样本仅显示排除计数；分支失败、重试、自动修订和质量门禁退回共同校准可靠性。样本充足的角色可靠性只对候选决策分产生 `-5..+5` 调整，能力合同、结构分 `/100` 与必需角色均不被历史数据改写；预检与计划审批可渐进查看样本、可靠性、耗时和成本。候选、评分、选择依据和少数意见随计划版本持久化，项目页可渐进比较。最终计划只能选择至少两个合格角色，每个分支声明所需能力、组队依据和至少一个 `AC-xx`，整份计划必须覆盖需求合同的全部验收标准；解析、批准与调度都会阻断不可用角色、虚构能力、验收责任缺失或用户明确要求的领域能力遗漏，能力不足时明确失败而不静默缩小需求。服务端校验无环 DAG，并按拓扑波次执行同波并行 Agent、向下游注入直接上游 Handoff；每条新 Handoff 都由服务端封存计划版本、输入、输出、证据上下文和直接上游 SHA-256 指纹，Quality Gate 重新计算拓扑证据链并阻断被篡改、证据失据或仍引用旧上游的交接。每个尝试批次提交耐久检查点，瞬时 provider/并发错误只对失败 Agent 执行有界指数退避，确定性错误或局部重试耗尽则暂停到分支恢复门禁。操作员可保留成功交接并定向重试失败分支，或丢弃旧分支产物退回 Planner 生成必须重新审批的新版本。测试、运营和架构三个独立 Reviewer 并行生成协作账本，以两份合法合同构成 quorum、有效评分中位数和多数票仲裁；确定性门禁及任一开放阻塞项仍可否决。项目页从持久化事件恢复每个 Agent 的能力、验收责任、选择依据、执行、重试、失败、检查点恢复、交接、来源指纹、Reviewer 分歧与决策证据，上游返修会自动传播到全部下游。
- 可验证专业交接：新分支必须返回 Handoff v3 JSON 合同，在 v2 的摘要、关键决策、验收证据、风险与负责人、开放问题和下一步行动之上，为每条证据声明 `criterion_ids` 与 `source_refs`。验收引用必须完整覆盖该分支认领的 AC，来源只能是当前 `artifact:PRD`、`artifact:SYSTEM_DESIGN` 或直接上游 `handoff:<role>`；服务端把标准定义、产物哈希和上游输出指纹组成的证据上下文一并封存。任一必需部分缺失、责任越界、未知/过期引用都会被确定性门禁返修。下游只接收受信任的结构化投影，解析失败原文仅留在受控状态供诊断。项目页默认展示摘要和计数，按需展开 AC 与人类可读来源；legacy v1/v2 保持兼容。
- 逐项验收仲裁：测试、运营和架构 Reviewer 除整体评分外，必须彼此不可见地对当前每个 `AC-xx` 返回 `PASS|FAIL|ABSTAIN`、置信度、理由和合法返修角色。每张 `PASS/FAIL` 票还必须引用 `handoff:<role>@<output_sha>#evidence:<n>` 形式的具体 evidence；服务端验证指纹属于当前封存 Handoff、evidence 覆盖同一 AC 且角色确实负责该 AC，`ABSTAIN` 不得伪造依据。随后每项独立要求两票 `PASS`；整体高分或三票整体放行都不能掩盖单项证据缺口。未达 quorum 的 AC 将评分封顶为 79 并只返修其责任分支。项目页用渐进矩阵展示逐项状态、票数、责任人、Reviewer 理由与短指纹证据锚点，SSE 仅公开票据和引用数量。
- 能力上下文隔离：Team Performance Profile 的角色总览用于启动预检和团队解释；候选评分只读取与该 assignment 的 `required_capabilities` 规范化集合完全一致的历史分支。旧工作流缺少能力元数据或没有精确匹配时不回退到角色平均值，也不生成成本/关键路径预测；每个角色最多保留 10 个稳定排序的能力上下文。
- 执行前承诺：每个候选中的实际专业 Agent 彼此不可见地审查自己的 assignment、直接依赖、冻结能力和交付边界，返回接受、质疑或弃权以及置信度、缺失输入和修改建议；若三个独立候选都未就绪且存在合法质疑，Planner 会选择承诺数最多、质疑最少、评分最高的候选进行一次自动协商修复，再由实际执行者重新承诺。重复结构、无效修复或仍未闭环的结果不会循环重试并回到人工审批；存在全员接受候选时仲裁不得选择未就绪方案，批准前不启动分支。
- 可视化启动预检：用户可在启动弹窗编辑真实工作目标，零模型调用查看四类专业 Agent 的能力、工具与就绪状态；缺少最低团队规模或明确领域能力时直接显示阻断原因，运行入口在扣费和入队前再次复核同一政策。
- 可执行原型旅程：AI 产品经理定义用户目标与关键路径，架构 Agent 将步骤绑定到真实页面和控件，测试 Agent 与确定性门禁复核路径覆盖；原型工作室可引导用户逐步体验并高亮当前操作，交付清单同步生成端到端验收用例。
- Prompt 调优：管理员可把门禁失败证据交给 Optimizer Agent 生成提案，再由独立 Reviewer Agent 与确定性规则检查角色漂移、注入、工具越权、评测迎合和治理绕过；拒绝意见会触发有界返修，通过后只创建草稿，仍须 Challenger 评测才能发布。
- 失败洞察：生产负反馈在服务端完成身份伪匿名化和邮箱、手机号、证件、银行卡、IP、Bearer/API 密钥脱敏后，按 Agent 角色与共同失败信号确定性聚类；评测实验室区分已覆盖、部分覆盖和覆盖缺口，并可从缺口直接补建回归用例。所有新建、编辑或由反馈转化的评测输入都会经过同一脱敏门禁，原始冻结证据仍保留在受控审计边界内。
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
