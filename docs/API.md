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
- `GET /evaluations/failure-insights`：仅管理员读取按 Agent 角色隔离的有效负反馈聚类、脱敏计数、优先级、相似启用用例和 `COVERED|PARTIAL|GAP` 回归覆盖结论
- `GET /evaluations/feedback?status=PENDING|CONVERTED|DISMISSED|ALL`：仅管理员筛选当前负反馈及历史复核结果；用户身份伪匿名化，输入、回答、评论和复核说明在响应前脱敏
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

反馈评测接口只接受当前仍为 `rating=-1` 的助手消息。同一反馈最多生成一个评测用例；转化和忽略均以 `request_id` 幂等，已被其他请求复核时返回 `409`。原始来源输入、回答和评论只保存在受控冻结快照中；管理员反馈响应使用伪匿名身份和脱敏正文，审计详情只记录资源 ID 和 Agent 角色。通过创建、编辑或反馈转化进入评测集的文本统一执行邮箱、手机号、证件号、银行卡、IP 和凭据脱敏。

失败洞察只纳入 `PENDING` 与 `CONVERTED` 负反馈，已忽略项不参与。聚类在脱敏后按 Agent 角色隔离计算，最多分析最近 500 条待复核与 500 条已转用例反馈并显式返回截断状态。来源反馈已关联的启用用例优先证明覆盖；其他启用用例只按相似共同信号给出部分或完整覆盖建议，不改变核心角色覆盖门禁。

评测运行要求当前测试集覆盖所有已配置的核心协作角色；缺少任一角色时创建运行返回 `422`。worker 完成和 Challenger 发布会再次使用冻结测试集与当前核心 Agent 配置校验覆盖，防止运行期间新增角色或历史绿灯绕过门禁。

基础套件按角色提供产品验收、可恢复架构、风险驱动测试、灰度运营和可执行交付计划模板。生成接口仅补当前没有启用用例的角色，返回新增角色、用例 ID 和最新覆盖状态；并发请求通过核心 Agent 行锁串行复核。

Prompt 调优只接受 `COMPLETED` 或 `FAILED` 运行中实际未通过、回退、执行错误，或导致均分/安全门禁失败的结果。显式提交多个结果时必须全部可调优、属于同一 Agent 和同一冻结 Prompt 版本；团队运行存在多个失败角色时，客户端必须明确选择目标结果。响应和任务详情仅对管理员开放。Reviewer 拒绝会在配置上限内把意见交回 Optimizer 返修，并在详情返回逐轮摘要；任务完成只产生 `AgentPromptVersion(DRAFT)`，进入 Challenger 继续使用现有 `/evaluations/runs`，不能借调优接口发布。

## 工作流与知识库

- `POST /workflow/preflight`：只读检查给定项目和工作目标所需的专业能力，返回四类专业 Agent 的资格、当前能力视图、阻断原因及同项目 Team Performance Profile；不扣费、不创建运行。
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

`POST /workflow/preflight` 与运行入口使用同一套确定性团队就绪规则：至少两个合格专业 Agent，并覆盖工作目标明确要求的领域能力。响应中的 `team_performance_profile` 来自最近 50 个同项目终态运行，且 `configuration_scope=CURRENT_CONFIGURATION`；只有与当前 Agent ID、Prompt、模型、工具、知识/记忆权限和并发额度一致的角色样本进入 `branch_sample_count`，旧配置或缺失快照样本进入 `excluded_branch_sample_count`。每个角色返回最终成功/失败、重试、修订、质量失败、可靠性、分支中位耗时、平均模型成本、排除数和 `INSUFFICIENT|LOW|MEDIUM|HIGH` 证据等级。`POST /workflow/run` 不信任此前的客户端结果，而是在项目互斥检查后重新冻结配置与绩效证据并复核；只有通过后才预扣额度和创建队列运行，同一次运行继续复用这份快照，避免检查、规划与审批使用不同数据。

Requirement 节点将产品经理输出解析为 `requirements.contract`：包含目标用户、范围内/外、约束、假设，以及带稳定 `AC-xx`、优先级和证据要求的验收标准。架构师与测试工程师独立返回 `ACCEPT|CHALLENGE|ABSTAIN`，归约结果存入 `requirements.consensus`。合法质疑触发一次产品经理修订；服务端拒绝无效或 SHA-256 指纹未变化的修订，并仅对有效新合同重新评审。最终 `CHALLENGED` 会强制 `require_plan_approval=true`，`INCOMPLETE` 保留证据但不把模型故障伪装成质疑。`REQUIREMENTS_CONSENSUS_REACHED` 事件只公开验收标准数、状态、来源、评审票数和修订有效性，不返回合同、问题或建议正文；缺少新字段的历史运行仍按原状态读取。

`POST /workflow/run` 需要唯一 `request_id`，返回 `202 QUEUED`；创建时按发起者角色冻结 Agent 的 Prompt、模型、版本、启用工具、知识权限和并发限制。Planner 只接收本次冻结快照中合格的专业角色及能力目录；少于两个合格角色，或用户明确要求的知识检索/通知投递能力不可用时不调用模型。设置 `require_plan_approval=true` 后，Planner 生成结构化执行计划即暂停，批准前不会启动专业分支。计划中的每个 assignment 声明 `required_capabilities`、`selection_reason`，并可使用 `depends_on` 引用同一计划内的前置角色；服务端拒绝不可用角色、能力越权、明确领域能力遗漏、重复、自依赖、未知依赖和环，批准及调度时都会复核。缺少能力元数据或依赖字段的旧计划由服务端补齐基线能力并按无依赖处理。同一拓扑波次内并行执行，后续波次接收直接上游 Handoff。新 Handoff 在服务端写入 `plan_version`、`upstream_fingerprints`、`input_fingerprint` 和 `output_fingerprint`；Quality Gate 会根据当前计划和拓扑重新计算这些值，阻断被修改或引用旧上游的交接，缺少这些字段的历史快照保持兼容。Quality Gate 并行调用测试、运营和架构 Reviewer；至少两份合法 JSON 合同构成 quorum，有效评分取中位数且有效票必须多数通过，确定性检查和任一开放阻塞项仍可否决。单 Reviewer 异常按弃权处理，低于 quorum 时 worker 从质量节点重试。每个尝试批次都会原子提交已成功 Handoff 和消息；瞬时分支错误只重试失败角色，确定性错误或局部重试耗尽进入 `specialist_review`。事件公开脱敏的退避、恢复、证据链和 Reviewer 计数，不公开完整指纹或评审正文。创建运行时冻结局部重试参数；每次重规划追加不可变快照并重新审批。同一项目存在活动工作流时拒绝第二条；幂等请求不重复扣费。后台 worker 按节点和专业波次持久化快照，取消或真正终态失败才进入补偿与幂等退款。

每个计划版本包含三个彼此隔离的 Planner 候选视角。服务端只接受通过能力和 DAG 合同的候选，并记录五项总计 100 分的确定性检查；架构师仲裁只能选择已有 `candidate_id`，不能通过响应改写计划。每个候选另含 `performance_evidence`：结构分保持 `/100`，样本充足角色的收缩可靠性只产生 `-5..+5` 调整，成本与关键路径投影要求全部分配角色有观测；能力合同和必需角色不受历史表现影响。仲裁失败时按承诺状态、调整后决策分、结构分和稳定 ID 选择，全部候选无效时使用能力感知的服务端计划。响应状态中的 `plan_deliberation` 和 `plan_revisions[].deliberation` 保存候选、绩效证据、结构指纹、评分、选择依据和少数意见；缺少绩效字段的历史运行仍按结构分兼容。选择历史 `plan_version` 批准或重规划时，服务端同步切换计划与仲裁证据。`PLAN_DELIBERATED` 事件只公开候选数量、不同结构数、无效候选数、选中 ID、仲裁模式、结构分、决策分、可靠性调整、证据等级和角色计数，不返回候选正文。

每个合法候选在仲裁前由其 assignment 对应的冻结专业 Agent 并发生成执行承诺。`commitments` 包含角色、`ACCEPT|CHALLENGE|ABSTAIN`、结构化状态、置信度、摘要、缺失输入、依赖风险和修改建议，并汇总为 `READY|CHALLENGED|INCOMPLETE`。三个独立候选都未就绪且存在合法 `CHALLENGE` 时，服务端按接受数、质疑数、确定性评分和稳定 ID 选择来源候选，调用 Planner 一次生成 `origin=negotiated_repair` 的第四候选；重复指纹或无效合同被拒绝，合法修复只重新收集自己的执行承诺。存在 `READY` 候选时服务端拒绝架构师选择其他状态；修复后仍无 `READY` 候选时自动把 `require_plan_approval` 设为 true。人工计划 `REVISE` 会把所选版本的结构化质疑连同人工意见注入下一轮 Planner。`PLAN_COMMITMENTS_COLLECTED` 与 `PLAN_NEGOTIATION_REPAIRED` 事件只公开候选、来源、修复有效性、就绪、接受、质疑和弃权计数，不公开承诺正文、置信度或具体问题。

追踪接口中，管理员可汇总和查看全平台工作流；普通成员只查看本人发起且当前仍有项目读取权限的工作流。指定无权访问的 `project_id`、跨租户运行或无权限的对比对象统一返回 `404`。基线对比要求两个不同运行属于同一项目且均已结束，否则返回 `400`。总运行数、状态、Token、成本和每日趋势使用完整数据库聚合；P95、Agent 分布、节点瓶颈和 SLO 健康度使用有上限的最近样本，截断时 `window.analysis_truncated=true`。异常检测使用同项目较旧运行的中位数绝对偏差（MAD）构造动态上界，并同时报告失败和静态 SLO 超限。追踪、健康和对比响应不返回 `state_json`、Prompt、人工反馈或产物正文，事件 payload 只公开角色、轮次、下一节点、质量分数等允许的运行元数据。

告警状态只能按 `OPEN -> ACKNOWLEDGED -> RESOLVED` 前进，也允许 `OPEN` 直接解决；已解决告警不可退回。`workflow_id` 唯一约束和嵌套事务保证多副本扫描不会重复创建告警或通知。新告警默认发送站内通知；开启 `OBSERVABILITY_ALERT_EMAIL_ENABLED` 后同时进入现有邮件投递队列。创建、确认和解决均写入审计日志，告警内容不保存 Prompt、错误正文、工作流状态或产物。

## AI 原型工作室

- `GET /prototypes`、`GET /prototypes/{prototype_id}`：查询当前用户可访问的原型及不可变版本历史。
- `POST /prototypes/generate`：从项目、可选需求和自然语言目标生成带可执行用户旅程的交互原型。
- `POST /prototypes/{prototype_id}/regenerate`：根据修订意见创建新版本，不覆盖历史版本。
- `POST /prototypes/{prototype_id}/versions/{version}/activate`：切换活动版本；切换到其他版本会把审批状态重置为 `DRAFT`。
- `PATCH /prototypes/{prototype_id}`、`DELETE /prototypes/{prototype_id}`：更新状态或删除原型。
- `GET|POST /prototypes/{prototype_id}/comments`：读取或创建当前版本的页面级评审意见。
- `PATCH /prototypes/{prototype_id}/comments/{comment_id}`：解决或重新打开评审意见。
- `POST /prototypes/{prototype_id}/materialize`：将已批准版本幂等转换为实现任务、单页验收用例和端到端旅程用例。

原型 DSL 的 `journeys` 为新生成合同的必填字段。每一步引用真实 `screen_id`、可执行的按钮或链接、操作说明和预期页面；服务端拒绝未知控件、非连续步骤及与导航目标不一致的结果，质量门禁要求所有页面被步骤起点或预期到达页覆盖。历史版本没有 `journeys` 时兼容读取为空列表，重新生成时进入新合同。

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
