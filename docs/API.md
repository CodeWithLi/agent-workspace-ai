# API 文档

基础路径：`/api/v1`。除注册、登录、刷新外，业务接口使用 `Authorization: Bearer <access_token>`。

## 认证

- `POST /auth/register`：注册并签发 access token、HttpOnly refresh cookie。
- `POST /auth/login`：登录并创建服务端会话。
- `POST /auth/refresh`：轮换 refresh 会话并签发新 access token。
- `POST /auth/logout`：撤销当前 refresh 会话。
- `GET /users/me`：当前用户。
- `GET /users`：管理员查询用户。
- `PATCH /users/{user_id}`：管理员更新角色、状态和权限。
- `POST /users/{user_id}/revoke-sessions`：撤销用户全部 refresh 会话。

## 项目与任务

- `GET|POST /projects`
- `GET /projects/{project_id}`
- `PATCH|DELETE /projects/{project_id}`：更新、归档或由 owner 删除项目。
- `GET|POST /projects/{project_id}/members`：查看成员、owner 邀请或改角色。
- `DELETE /projects/{project_id}/members/{member_id}`
- `GET|POST /projects/{project_id}/tasks`
- `PATCH /projects/{project_id}/tasks/{task_id}`
- `DELETE /projects/{project_id}/tasks/{task_id}`
- `GET|POST /projects/{project_id}/tasks/{task_id}/comments`
- `GET /projects/{project_id}/activity`

项目角色：`owner`、`editor`、`viewer`。读取允许全部成员；写操作同时要求非 viewer 和 `projects:write` 全局权限。

## Agent 与聊天

- `GET /agents`
- `GET /agents/{agent_id}/tools`
- `PATCH /agents/{agent_id}`：已弃用；有配置变更时返回 `409`，客户端应创建草稿并进入评测发布。
- `GET|POST /agents/{agent_id}/versions`
- `POST /agents/{agent_id}/versions/{version_id}/publish`：已弃用并返回 `409`，不能绕过评测门禁。
- `POST /agents/{agent_id}/versions/{version}/rollback`：已弃用并返回 `409`，回滚应创建候选草稿后评测，或使用评测发布记录的 rollback API。
- `PATCH /agents/{agent_id}/tools/{tool_id}`：仅管理员。
- `GET /agents/actions`：查看本人待审批/已决工具动作，管理员可查看全部。
- `POST /agents/actions/{action_id}/approve`
- `POST /agents/actions/{action_id}/reject`
- `POST /agents/route`：返回 Agent、置信度和可解释原因。
- `POST /agents/chat`
- `POST /agents/chat/stream`：真实上游 SSE。
- `POST /agents/discussion/stream`：五阶段多 Agent 团队讨论 SSE。
- `GET /agents/conversations`
- `GET /agents/conversations/{conversation_id}/messages`
- `POST /agents/messages/{message_id}/feedback`
- `POST /agents/messages/{message_id}/regenerate`
- `GET|POST /evaluations/cases`、`PATCH|DELETE /evaluations/cases/{id}`
- `POST /evaluations/cases/bootstrap`：仅管理员为缺失的核心 Agent 角色幂等生成可编辑基础用例；锁定角色后复核覆盖，不覆盖已有用例
- `GET /evaluations/coverage`：仅管理员读取核心多 Agent 角色、各角色启用用例数、缺失角色、覆盖率和门禁就绪状态
- `GET /evaluations/feedback?status=PENDING|CONVERTED|DISMISSED|ALL`：仅管理员筛选当前负反馈及历史复核结果
- `POST /evaluations/feedback/{feedback_id}/promote`：仅管理员使用唯一 `request_id` 将负反馈幂等转为启用用例，并冻结来源证据
- `POST /evaluations/feedback/{feedback_id}/dismiss`：仅管理员使用唯一 `request_id` 和复核原因幂等忽略候选项
- `POST /evaluations/runs`、`GET /evaluations/runs`、`GET /evaluations/runs/{id}`；创建 Challenger 时同时提交 `baseline_run_id` 与 `candidate_version_id`
- `POST /evaluations/runs/{id}/cancel`、`POST /evaluations/runs/{id}/retry`
- `POST /evaluations/runs/{id}/publish`：幂等发布已通过门禁且生产版本未漂移的 Challenger
- `POST /evaluations/releases/{id}/rollback`：幂等创建恢复版本并保留原发布证据
- `POST /evaluations/optimization-jobs`：仅管理员使用唯一 `request_id`、失败运行、同一 Agent 的失败结果 ID 发起持久化 Prompt 调优；发布门禁失败时，即使案例通过自身阈值，低于全局均分阈值或触发安全硬门禁的结果仍可作为调优证据
- `GET /evaluations/optimization-jobs`、`GET /evaluations/optimization-jobs/{id}`：仅管理员读取任务状态、Reviewer 结论、安全检查、冻结证据摘要和生成的草稿
- `POST /evaluations/optimization-jobs/{id}/cancel`、`POST /evaluations/optimization-jobs/{id}/retry`：仅管理员取消活动任务，或基于原冻结证据重试失败、已取消及安全拒绝任务
- `POST /evaluations/run` 保留为兼容入口；新客户端应使用带 `request_id` 的异步 `/evaluations/runs`。

SSE 事件：`thinking`、`tool`、`token`、`error`、`done`。`done` 包含 `conversation_id`、`agent_id` 和 `agent_name`。

团队讨论事件为 `discussion_start`、`speaker_start`、`token`、`speaker_done`、`error`、`done`。每个发言事件包含实际 `agent_id`、名称和阶段；阶段顺序为产品范围、技术架构、质量审查、发布运营、最终方案。后续 Agent 的 Prompt 包含本轮此前全部发言，最终方案由项目经理综合。讨论会话可通过原 `conversation_id` 继续追问，但不能与单人会话模式混用。

聊天请求必须包含客户端生成的唯一 `request_id`。平台创建 `agent_runs` 运行记录、预扣固定 Token，并在失败或流式连接异常时幂等退款；重复请求返回 `409`。并发达到 Agent 上限时返回 `429`。

用户必须拥有 `agents:read`。审批执行前会重新检查项目写权限、Agent 硬白名单、数据库工具启停和发起者状态；重复审批返回 `409`。

反馈评测接口只接受当前仍为 `rating=-1` 的助手消息。同一反馈最多生成一个评测用例；转化和忽略均以 `request_id` 幂等，已被其他请求复核时返回 `409`。来源输入、回答和评论只出现在管理员反馈响应及冻结快照中，审计详情只记录资源 ID 和 Agent 角色。

评测运行要求当前测试集覆盖所有已配置的核心协作角色；缺少任一角色时创建运行返回 `422`。worker 完成和 Challenger 发布会再次使用冻结测试集与当前核心 Agent 配置校验覆盖，防止运行期间新增角色或历史绿灯绕过门禁。

基础套件按角色提供产品验收、可恢复架构、风险驱动测试、灰度运营和可执行交付计划模板。生成接口仅补当前没有启用用例的角色，返回新增角色、用例 ID 和最新覆盖状态；并发请求通过核心 Agent 行锁串行复核。

Prompt 调优只接受 `COMPLETED` 或 `FAILED` 运行中实际未通过、回退、执行错误，或导致均分/安全门禁失败的结果。显式提交多个结果时必须全部可调优、属于同一 Agent 和同一冻结 Prompt 版本；团队运行存在多个失败角色时，客户端必须明确选择目标结果。响应和任务详情仅对管理员开放。Reviewer 拒绝会在配置上限内把意见交回 Optimizer 返修，并在详情返回逐轮摘要；任务完成只产生 `AgentPromptVersion(DRAFT)`，进入 Challenger 继续使用现有 `/evaluations/runs`，不能借调优接口发布。

## 工作流与知识库

- `POST /workflow/run`
- `GET /workflow?project_id=...`
- `GET /workflow/{workflow_id}`
- `GET /workflow/{workflow_id}/events/history`：按时间顺序读取最近 1-200 条持久化事件，用于页面刷新恢复；payload 只返回允许列表中的运行元数据。
- `GET /workflow/{workflow_id}/events`：支持 `Last-Event-ID`、服务端重试间隔和心跳的持久化进度 SSE；连接期间持续复核用户与项目权限，错误、Prompt、Handoff 与人工反馈正文不会进入流。
- `GET /workflow/{workflow_id}/saga-steps`：查看写工具执行快照、状态、补偿次数和人工介入原因。
- `POST /workflow/{workflow_id}/pause`：使用唯一 `request_id` 和暂停原因请求安全暂停。排队运行立即进入 `PAUSED`；专业分支运行在当前拓扑波次检查点提交后暂停，其他节点在节点提交后暂停，相同请求幂等返回。
- `POST /workflow/continue`：恢复计划审批、失败分支、质量门禁、报告确认或操作员暂停。`plan_review` 接受 `APPROVE|REVISE` 和可选 `plan_version`；`specialist_review` 只接受带 `human_feedback` 的 `RETRY|REPLAN`，前者保留成功 Handoff 并定向继续失败分支及下游，后者清空旧分支产物、返回 Planner 并强制新版本重新审批。不同门禁的决策类型不可混用。客户端不能提交或覆盖计划快照；操作员暂停必须提供恢复指令，该指令会持久化到结构化运行上下文并传递给后续 Agent。
- `POST /workflow/{workflow_id}/cancel`
- `POST /workflow/{workflow_id}/retry`：仅接受 `FAILED` 源运行和唯一 `request_id`；源运行保持只读，接口独立扣费并从失败检查点创建新的 `QUEUED` 子运行。相同源运行与 `request_id` 返回同一子运行，项目存在其他活动运行时返回 `409`。
- `POST /workflow/{workflow_id}/retry-compensation`：仅用于 `COMPENSATION_FAILED`，人工核对业务数据后重试确定性补偿。
- `POST /workflow/{workflow_id}/publish`：将指定工作流产物发布为报告或项目知识文档。
- `GET /traces/overview?days=7&project_id=...&status=...`：汇总运行状态、端到端时延、Token、预估成本、每日趋势、Agent 性能、节点瓶颈和最近运行；`days` 为 1-90。
- `GET /traces/health?days=7&project_id=...`：按当前用户的追踪范围计算成功率、P95 耗时、单次平均成本、错误预算和异常运行；SLO 与异常敏感度由管理员在系统设置中热更新。
- `POST /traces/alerts/sync?days=30&project_id=...`：幂等扫描当前追踪范围，将尚未持久化的异常运行写入告警表并返回本次创建数量。
- `GET /traces/alerts?days=30&project_id=...&status=OPEN&severity=CRITICAL`：读取持久化告警、状态汇总和安全的异常信号元数据。
- `POST /traces/alerts/bulk`：批量执行 `ACKNOWLEDGE` 或 `RESOLVE`；解决操作必须提供最长 500 字的 `resolution_note`。
- `GET /traces/compare?baseline_id=...&candidate_id=...`：比较同一项目的两次已结束运行，返回运行结果、耗时、Token、成本、模型调用、Agent 和节点/分支聚合变化。
- `GET /traces/{workflow_id}`：返回排队、节点、并行分支和人工等待 Span，以及模型调用、安全事件元数据和 `parent_workflow_id/retry_from_node/retry_sequence` 重试谱系。节点和分支事件按 `workflow_attempt` 隔离 worker 尝试，失败尝试独立闭合，不会与后续成功重试误配。
- `GET /knowledge/documents`
- `POST /knowledge/upload`
- `POST /knowledge/search`
- `PATCH /knowledge/documents/{document_id}`：修改标签和来源。
- `GET /knowledge/documents/{document_id}/chunks/{chunk_index}`：定位引用片段。
- `GET /knowledge/documents/{document_id}/index-versions`：按版本倒序返回 parser、chunker、embedding、块数量、状态和激活时间。
- `POST /knowledge/documents/{document_id}/index-versions/{index_version}/activate`：使用 `request_id` 激活历史索引；目标版本的 PostgreSQL 向量会先重新写入 Milvus，当前版本保留为 `SUPERSEDED`。
- `POST /knowledge/documents/{document_id}/retry`
- `POST /knowledge/documents/{document_id}/reindex`
- `DELETE /knowledge/documents/{document_id}`

知识库上传和删除要求 `knowledge:write`；查询和检索只要求项目读取权限。上传返回 `202 QUEUED`，相同范围的重复内容返回 `409` 和已有文档 ID。

`POST /knowledge/search` 支持 `project_id`、`document_ids`、`tags`、`source_labels`、`top_k` 和 `min_score`。结果包含稳定 chunk ID、索引版本、标题路径、页码、sparse/dense/hybrid/rerank 分数和引用；个人文档只能由 owner 检索，项目文档要求当前项目成员身份。

`POST /workflow/run` 需要唯一 `request_id`，返回 `202 QUEUED`；设置 `require_plan_approval=true` 后，Planner 生成结构化执行计划即暂停，批准前不会启动专业分支。计划中的每个 assignment 可使用 `depends_on` 引用同一计划内的前置角色；服务端拒绝重复、自依赖、未知依赖和环，缺少该字段的旧计划按无依赖处理。同一拓扑波次内并行执行，后续波次接收直接上游 Handoff。新 Handoff 在服务端写入 `plan_version`、`upstream_fingerprints`、`input_fingerprint` 和 `output_fingerprint`；Quality Gate 会根据当前计划和拓扑重新计算这些值，阻断被修改或引用旧上游的交接，缺少这些字段的历史快照保持兼容。每个尝试批次都会原子提交已成功 Handoff 和消息；`LLMRetryableError`（网络/超时、408/409/429、5xx 或畸形成功响应）、Agent 并发饱和和超时只重试失败角色。确定性错误或局部重试耗尽会提交当前成功 Handoff 后进入 `specialist_review`，不会让整个 worker 失败；事件使用 `workflow_attempt` 区分 worker 尝试、使用 `branch_attempt` 区分局部尝试，并公开脱敏的退避、恢复和证据链验证元数据，不公开完整指纹。创建运行时冻结局部重试参数；每次重规划追加不可变快照，失败分支触发的重规划必须重新审批。同一项目存在活动工作流时拒绝创建第二条；同一请求重试返回原工作流，不重复扣费。后台 worker 按节点和专业波次持久化快照，取消或真正的终态失败才进入补偿与幂等退款。

追踪接口中，管理员可汇总和查看全平台工作流；普通成员只查看本人发起且当前仍有项目读取权限的工作流。指定无权访问的 `project_id`、跨租户运行或无权限的对比对象统一返回 `404`。基线对比要求两个不同运行属于同一项目且均已结束，否则返回 `400`。总运行数、状态、Token、成本和每日趋势使用完整数据库聚合；P95、Agent 分布、节点瓶颈和 SLO 健康度使用有上限的最近样本，截断时 `window.analysis_truncated=true`。异常检测使用同项目较旧运行的中位数绝对偏差（MAD）构造动态上界，并同时报告失败和静态 SLO 超限。追踪、健康和对比响应不返回 `state_json`、Prompt、人工反馈或产物正文，事件 payload 只公开角色、轮次、下一节点、质量分数等允许的运行元数据。

告警状态只能按 `OPEN -> ACKNOWLEDGED -> RESOLVED` 前进，也允许 `OPEN` 直接解决；已解决告警不可退回。`workflow_id` 唯一约束和嵌套事务保证多副本扫描不会重复创建告警或通知。新告警默认发送站内通知；开启 `OBSERVABILITY_ALERT_EMAIL_ENABLED` 后同时进入现有邮件投递队列。创建、确认和解决均写入审计日志，告警内容不保存 Prompt、错误正文、工作流状态或产物。

## AI 原型工作室

- `GET /prototypes`、`GET /prototypes/{prototype_id}`：查询当前用户可访问的原型及不可变版本历史。
- `POST /prototypes/generate`：从项目、可选需求和自然语言目标生成可交互原型。
- `POST /prototypes/{prototype_id}/regenerate`：根据修订意见创建新版本，不覆盖历史版本。
- `POST /prototypes/{prototype_id}/versions/{version}/activate`：切换活动版本；切换到其他版本会把审批状态重置为 `DRAFT`。
- `PATCH /prototypes/{prototype_id}`、`DELETE /prototypes/{prototype_id}`：更新状态或删除原型。
- `GET|POST /prototypes/{prototype_id}/comments`：读取或创建当前版本的页面级评审意见。
- `PATCH /prototypes/{prototype_id}/comments/{comment_id}`：解决或重新打开评审意见。
- `POST /prototypes/{prototype_id}/materialize`：将已批准版本幂等转换为实现任务和结构化验收用例。

批准要求当前版本通过自动质量门禁且没有待处理评审意见。创建或重新打开当前版本的评审意见要求 `projects:write` 和非 viewer 项目角色；对已批准版本执行该操作会原子撤销批准并回到 `REVIEW`，归档版本禁止修改评审。`materialize` 要求客户端提供唯一 `request_id`；幂等键绑定原型及其具体版本，同一版本重复调用返回已有交付结果，不重复创建任务或用例，跨版本复用返回 `409`。

## Token 钱包

- `GET /billing/wallet`：余额、价格和最近流水。
- `POST /billing/recharge`：模拟充值，按配置比例换取 AI Token，要求唯一 `request_id`。
- `GET /billing/orders`：模拟充值单。
- `POST /billing/admin/adjust`：管理员增减 Token。
- `GET /billing/usage`：供应商 token、模型、耗时、来源和估算成本。

默认新用户 1,000 Token、聊天 10 Token、团队讨论 50 Token、完整工作流 100 Token、1 元模拟充值兑换 100 Token，均可通过环境变量或配置中心调整。

## 其他

- `GET /dashboard/stats`
- `GET /search?q=...`
- `GET|POST /requirements`
- `PATCH|DELETE /requirements/{id}`
- `GET|POST /meetings`
- `PATCH|DELETE /meetings/{id}`、`POST /meetings/{id}/tasks`
- `GET|POST /reports`
- `PATCH|DELETE /reports/{id}`
- `GET|POST /notifications`
- `POST /notifications/{notification_id}/send`
- `POST /notifications/{notification_id}/cancel`
- `GET|PATCH /settings`：管理员读取或更新运行时配置；密钥只返回配置状态。
- `POST /settings/test-connection`：测试 LLM、Embedding、Reranker、Docling、Redis、Milvus、MinIO 或 SMTP。
- `GET /audit`：仅管理员，支持 `action`、`project_id`、`limit` 过滤。
- `GET /health`、`GET /health/ready`

Python 服务端管理后台位于 `/admin`，使用独立管理员 Cookie 和 CSRF 校验，不属于 `/api/v1`。
