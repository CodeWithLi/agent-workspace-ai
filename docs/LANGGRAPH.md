# LangGraph 多 Agent 工作流

## 状态结构

`ProjectState`：

```json
{
  "user_input": "",
  "project": {},
  "requirements": {},
  "architecture": {},
  "tasks": [],
  "tests": {},
  "documents": [],
  "messages": [],
  "report": "",
  "agent_snapshot": {},
  "execution_plan": {},
  "plan_version": 1,
  "plan_revisions": [],
  "require_plan_approval": true,
  "plan_approved": false,
  "plan_revision_count": 0,
  "plan_revision_feedback": "",
  "specialist_handoffs": [],
  "quality_gate": {},
  "revision_round": 0,
  "revision_feedback": "",
  "interventions": []
}
```

## 节点

1. Requirement Agent
2. Product Agent
3. Architect Agent
4. Planning Agent：生成经过结构校验的动态执行 DAG。
5. Plan Review：可选人工门禁，批准后才允许启动并行分支，或携带反馈退回 Planner 重做。
6. Specialist Branches：根据已批准 DAG 按拓扑波次执行 2 至 4 个专业分支，同波并行并生成结构化 Handoff。
7. Quality Gate：合并确定性检查和测试 Agent 评审，最多触发一轮自动修订。
8. Project Manager Agent
9. Tester Agent
10. Report Generator

工作流由 LangGraph `StateGraph`、`START`、条件边和 `END` 构建，不使用手写顺序分支。创建工作流时按发起者角色冻结各 Agent 的 Prompt、模型、Prompt 版本、可用工具、知识权限、人工审批配置和并发限制，同时冻结专业分支重试策略；架构师读取真实 PRD，动态专家读取需求与架构，项目经理和测试工程师消费完整 Handoff 与质量门禁证据，避免运行中配置漂移和“多个 Agent 实际各说各话”。每个节点开始和完成时分别写入 `workflow_events`，完成时同步更新 `state_json` 和下一个节点，因此 worker 崩溃后可以从最后一个已提交节点恢复。

服务端从四类专业角色的冻结快照生成确定性能力目录。角色固有能力与当前启用工具映射为能力集合；知识检索只有在 `knowledge_access=true` 且 `knowledge_search` 可用时存在；缺少 Agent、并发额度或全部专业工具的角色标记为不合格。Planner 只接收本次合格角色及其能力、工具、知识权限和并发额度；少于两个合格角色，或用户明确要求的知识检索/通知投递能力在目录中不存在时，都在调用模型前失败。每个 assignment 必须声明 `required_capabilities` 和 `selection_reason`，所需能力必须是该角色冻结能力的子集，整份计划还必须覆盖从用户目标推导出的明确领域能力。模型选择不可用角色、虚构能力或遗漏明确领域能力时，服务端丢弃候选并生成保留这些能力的确定性降级计划；降级计划也无法满足时明确失败，不会静默缩小需求。旧快照没有工具字段时使用角色历史默认工具恢复，旧计划没有能力元数据时由服务端补齐角色基线能力和可审计理由。

项目页在启动前调用只读团队预检，展示目标所需能力、每名专业 Agent 的可用状态和阻断原因。真正的 `/workflow/run` 在项目互斥检查后用同一确定性规则重新检查，并把通过检查的配置快照直接交给初始状态；团队不就绪时发生在排队和计费之前，因此不会为注定无法编排的需求消耗额度或触发 Requirement、Product、Architect 模型调用。

每个 assignment 可通过 `depends_on` 引用同一计划内的前置角色。Pydantic 合同拒绝重复、自依赖、未知依赖和环；缺少 `depends_on` 的旧快照按空依赖兼容。项目 UI 创建运行时开启 `require_plan_approval`，图在 `plan_review` 持久化暂停。每次规划都向 `plan_revisions` 追加不可变版本快照；UI 可比较版本、检查拓扑波次、所需能力和组队依据，并展开冻结工具、完整能力、知识权限与并发额度。用户可选择任一历史版本执行 `APPROVE` 或 `REVISE`。服务端只接受版本号，读取并在批准时重新校验能力合同；`REVISE` 必须携带反馈，并以所选版本作为 `planning` 的基线生成新版本。`APPROVE` 设置 `plan_approved` 后进入专业分支，`specialists` 节点再次校验批准标志和冻结能力，防止恢复、状态篡改或客户端绕过门禁。

专业分支使用确定性拓扑排序分波执行：同一波通过 `asyncio.gather` 并行，下一波只接收 `depends_on` 指定的直接上游 Handoff，避免把无关产物塞入所有 Prompt。服务端为每条新 Handoff 规范化并封存完整计划、计划版本、assignment、修订轮次、直接上游输出指纹和自身输入/输出 SHA-256 指纹；Quality Gate 按拓扑顺序重新计算，正文被改写、计划漂移或仍引用旧上游的下游都会被识别并定向返修。没有封存字段的历史快照仍可读取，新旧 Handoff 可以在检查点恢复期间共存。每个尝试批次结束后原子持久化成功 Handoff、消息和失败事件；如果全部失败都属于 `LLMRetryableError`、Agent 并发饱和或超时，运行只对失败角色执行有界指数退避，退避后再次检查租约、暂停和取消，再开始下一批次。网关只把网络/超时、408/409/429、5xx 和畸形成功响应归为 `LLMRetryableError`。

认证、请求配置、业务或依赖等确定性错误以及局部次数耗尽不会再让成功分支跟随整条 worker 失败。当前波次先原子提交成功 Handoff 和失败摘要，再将图停在 `specialist_review`：`RETRY` 必须携带修复指令，保留同修订轮次的成功 Handoff，只执行失败角色及尚未完成的传递下游；`REPLAN` 清空旧专业 Handoff、质量门禁和修订状态，以原计划和人工意见返回 Planner，并强制新计划进入 `plan_review`。失败正文只存在受控工作流快照，事件和追踪仅公开角色、波次、尝试、失败/可重试计数与恢复次数。任何已成功角色都不会重复执行。质量门禁请求修订上游角色时，运行时计算传递下游闭包并一并重跑，防止下游继续使用过期结论；只修订叶子角色时不会扩大执行范围。

质量门禁先检查角色覆盖、交付内容、Handoff 证据链、成功标准和专业广度，再用 `asyncio.gather` 并行调用测试、运营和架构三个互不可见结论的 Reviewer。至少两份合法结构化合同构成 quorum；有效票按 Reviewer 自身分数、结论与阻塞项归约，最终分数取确定性分数与有效 Reviewer 分数中位数的较低值，并要求多数票通过。单个调用异常或合同无效只弃权，低于 quorum 则抛出专用错误，由 worker 在同一 `quality_gate` 检查点重试并持久化脱敏人数。账本合同包含共同决策、来源角色、审查置信度、冲突双方立场、解决状态、待确认问题和责任角色；服务端过滤计划外角色，精确去重多 Reviewer 的相同结论，并在任一阻塞冲突或阻塞问题仍开放时把评分封顶为 79、强制 `passed=false`、推导定向返修角色。自动修订仍未通过时，工作流暂停在 `quality_review`；后续节点消费同一仲裁账本，不重新猜测结论。

除通用 `NODE_STARTED/NODE_COMPLETED/NODE_FAILED` 外，事件流还会记录 `PLAN_CREATED`、`PLAN_APPROVED`、`PLAN_REVISION_REQUESTED`、`WAVE_STARTED`、`WAVE_COMPLETED`、`WAVE_CHECKPOINTED`、`WAVE_RESTORED`、`BRANCH_STARTED`、`BRANCH_COMPLETED`、`BRANCH_FAILED`、`BRANCH_RETRY_SCHEDULED`、`SPECIALIST_REVIEW_REQUIRED`、`SPECIALIST_RETRY_REQUESTED`、`SPECIALIST_REPLAN_REQUESTED`、`QUALITY_GATE_PASSED`、`REVISION_REQUESTED` 和 `QUALITY_GATE_FAILED`。事件 API 与追踪共用 payload 允许列表，只返回版本号、来源版本、波次、角色、依赖角色、分支数、成功/失败/可重试计数、恢复次数、证据链封存状态与上游数量、Reviewer 总数/有效数/quorum/通过票/分歧数、决策/冲突/开放阻塞计数、修订轮次、worker/分支尝试和退避时长等运行元数据。Reviewer 原始正文和无效输出不持久化，只有归一化摘要、票型与账本进入受控状态；完整指纹、Handoff、失败与恢复指令、决策与冲突正文、错误、Prompt、质量问题与人工反馈不会进入 SSE 或追踪响应。人工检查点重试仍创建不可变子运行；分支恢复则在原运行的已提交波次上继续。

项目页在加载时回放最近的持久化事件，并在 SSE 更新后按角色重新归约状态；`workflow_attempt`、`branch_attempt`、`will_retry`、退避秒数和 `WAVE_RESTORED.roles` 共同区分等待、执行中、等待重试、失败、检查点恢复和已交接。SSE 中断或刷新不会把已知 Agent 退回“等待执行”。完成或恢复的分支可展开 Handoff 并查看来源指纹；质量门禁下方先展示三名 Reviewer 的关注域、有效性、票型、评分、摘要、quorum 和分歧数，再展示共同决策、冲突与待确认责任。失败门禁仍提供定向重试与重新规划。移动端使用相同文字、图标和元数据，不依赖 hover 或单一颜色。追踪中的质量节点归属 `reviewer_panel`，三个模型调用仍分别归属实际 Agent。

## 运行追踪与成本归属

`/traces` 运行追踪中心复用 `workflow_runs`、`workflow_events`、`llm_usage` 和 `agents`，不复制工作流状态或新增影子遥测表。服务端将事件配对为四类 Span：创建到首次启动的排队、按节点与 `workflow_attempt` 配对的 `NODE_STARTED/NODE_COMPLETED|NODE_FAILED` 节点、以角色、修订轮次、`workflow_attempt` 和 `branch_attempt` 配对的 `BRANCH_STARTED/BRANCH_COMPLETED|BRANCH_FAILED` 并行分支，以及 `PAUSED` 到重新入队/继续之间的人工等待。失败尝试独立闭合为 `FAILED`，不会吞掉后续成功重试；跨版本运行的旧开始事件可与带尝试号的完成事件回退配对。未闭合 Span 使用当前时间或工作流终态时间计算，并保留 `ACTIVE`、`PAUSED`、`FAILED`、`CANCELLED` 状态。

模型调用先按 `workflow_id` 关联，再使用 Agent 角色和调用完成时间归属到最具体的并行分支；无法匹配分支时才归属外层节点，因此同一调用不会在分支与父节点重复累计。运行详情分别展示总耗时、排队、Agent 计算、人工等待和剩余协调开销。汇总中的运行数、状态、Token、成本和趋势是数据库聚合；P95、Agent 性能与节点瓶颈为显式标记截断的最近样本分析。

跨运行基线对比只接受同一项目的两次已结束运行。指标使用 5% 相对容差与最小绝对变化过滤噪声，分别对齐运行结果、端到端阶段、Agent 角色及节点/分支聚合；结论区分 `IMPROVED`、`REGRESSED`、`MIXED` 和 `UNCHANGED`。Token 或成本降低只表示效率改善，不替代内容质量评测。

SLO 健康度只使用已结束的成功或失败运行，按当前追踪权限和时间/项目范围计算成功率、P95 端到端耗时、单次平均成本与错误预算。少于最小样本数时返回 `INSUFFICIENT_DATA`，避免用少量运行作出稳定性结论；满足样本要求后区分 `HEALTHY`、`AT_RISK` 和 `BREACHED`。管理员可通过现有运行时设置热更新目标与最小样本数。

异常检测不会把不同项目混为同一基线。每个新运行只与同项目更早的终态运行比较，使用中位数和 MAD 的稳健上界识别耗时与成本偏离，同时保留失败和静态 SLO 超限信号。结果最多返回最近 20 条异常元数据，可直接下钻到运行详情，不持久化 Prompt 或产物内容。

后台告警扫描器按配置周期重新计算最近终态运行，将异常信号幂等持久化到 `trace_alerts`。健康接口仍只返回最近 20 条即时诊断；持久化扫描则在过滤已有 `workflow_id` 后每轮最多回填 100 条，因此历史异常不会因展示上限而永久遗漏，也不会在首次部署时无界发送通知。

告警处理采用 `OPEN -> ACKNOWLEDGED -> RESOLVED` 单向状态机，并允许直接从 `OPEN` 解决。确认人、解决人、时间和处理说明均持久化并进入审计日志；已解决告警不会因后续扫描重新打开。管理员可处理全平台告警，普通成员只能处理本人发起且仍有项目访问权的运行告警。创建时发送站内通知，可选接入现有 SMTP 异步投递队列。

追踪属于运行元数据视图：响应不读取或返回 `state_json`、Prompt、人工反馈和产物正文，事件 payload 使用字段允许列表。管理员可查看全平台运行，普通成员只能查看本人发起且仍可访问对应项目的运行。

## Saga 写操作一致性

任务创建和最终报告创建不是普通节点输出，而是持久化到 `workflow_saga_steps` 的可补偿步骤。状态只允许按以下路径迁移：

`PENDING -> EXECUTING -> COMPLETED -> COMPENSATING -> COMPENSATED`

执行或补偿失败分别进入 `FAILED`、`COMPENSATION_FAILED`，重试只能从对应失败状态继续。每一步执行前保存输入和幂等键，业务写入与 `COMPLETED` 状态在同一数据库事务提交；进程中断后读取执行日志续跑，不依赖模型上下文。

工作流达到最大重试次数或被取消时，按序号逆序补偿：先删除本工作流创建且未被修改的报告，再删除本工作流创建且未被修改的任务。检测到人工修改时拒绝自动删除，工作流进入 `COMPENSATION_FAILED`，阻止同项目启动新工作流并等待人工核对。不可逆的产物发布保持在人工确认和工作流完成之后。

## 暂停与继续

`POST /api/v1/workflow/run` 返回 `202 QUEUED`，后台 dispatcher 认领并执行，默认在 `report` 前进入 `PAUSED`。
`POST /api/v1/workflow/continue` 可在 `plan_review` 接收 `APPROVE/REVISE` 决策和可选 `plan_version`、在 `specialist_review` 接收 `RETRY/REPLAN` 与必填恢复指令、在 `quality_review` 接收修订方向，或在 `report` 前接收最终确认意见，随后重新入队。不同门禁不接受彼此的决策类型，`plan_version` 只能用于计划审批；缺失指令、非法决策或版本返回 `422`。最终报告写入 `reports` 表。项目页先从 `GET /workflow/{id}/events/history` 恢复最近事件，再以 `Last-Event-ID` 连接 `GET /workflow/{id}/events`；凭证过期时只执行一次共享刷新，断线后按服务端提示指数退避重连，已确认游标不会重复应用。

继续操作只允许对 `PAUSED` 运行执行一次；任务创建按标题幂等，重复继续返回 `409`，不会重复落任务或报告。

### 操作员安全干预

`POST /api/v1/workflow/{id}/pause` 不会中断正在进行的模型调用，也不会留下半个节点状态。暂停请求与提交都锁定同一 `workflow_runs` 行：如果请求先提交，普通节点在最近节点边界暂停，专业分支则先完成当前拓扑波次并提交成功 Handoff；如果节点或波次先提交，请求会在下一边界被发现。`complete_node` 原子持久化节点状态和 `NODE_COMPLETED`，`checkpoint_node` 原子持久化专业波次状态及其事件；两者都在提交后抛出受控暂停信号，worker 随后释放租约并转为 `PAUSED`。取消状态会在提交前检查并优先终止，不会让暂停覆盖取消。

暂停请求使用 `pause_request_id` 幂等，保存请求人、时间和最长 1000 字的原因。恢复时必须提供最长 4000 字的指令；平台把原因、指令和恢复节点追加到最近 10 条 `interventions`，并将该结构化上下文传给需求、产品、架构、规划、专业分支、质量门禁、项目计划、测试和报告 Agent。追踪事件只公开干预类型和字符数，不返回原因或指令正文。

排队运行可以在 worker 认领前立即暂停。若请求到达时最终报告节点已提交并进入 `completed`，平台记录 `PAUSE_SKIPPED` 并正常完成，避免出现无法恢复的 `PAUSED/completed` 组合。取消优先于暂停；失败补偿和取消终态会清理未应用的暂停元数据。

创建工作流时锁定项目记录，并检查是否已有 `QUEUED/RUNNING/CANCELLING/PAUSED` 工作流。同一 `request_id` 重试返回已有结果，其他并发工作流返回 `409`。自动重试不重复扣费，达到最大尝试次数或取消后按当前消费流水幂等退款。

终态失败的人工重试不会修改原 `workflow_runs` 行。平台创建带 `parent_workflow_id`、`retry_from_node` 和递增 `retry_sequence` 的新运行，复制冻结的 Agent 配置、人工反馈和最后已提交状态，并创建独立消费流水；子运行失败只退还自己的账单，也可继续创建孙运行。源运行的 `FAILED` 状态、结束时间、错误、事件、模型用量和账单保持不变，追踪中心因此可以分别比较每次尝试。

Saga 补偿可能把 `current_node` 回退到更早的写节点。重试前会比较最近一次 `NODE_STARTED` 与回退节点；确认发生回退时，只移除该检查点及后续的任务、测试、报告文档和对应消息，保留更早的需求、PRD、架构、执行计划、专业 Handoff 与质量门禁证据。

dispatcher 使用 PostgreSQL `FOR UPDATE SKIP LOCKED` 支持多副本。`locked_at` 超过租约的运行会被重新认领；取消在节点边界生效，避免提交半个节点的状态。

运行中的 worker 使用 `lease_token` fencing，并以租约时长三分之一为周期续租。所有节点提交和 Saga 写入都会锁定工作流行并校验 token；旧 worker 即使在超时后恢复，也不能提交业务写入。

实现文件：`backend/app/langgraph/workflow.py`、`backend/app/observability.py`、`backend/app/services/trace_alerts.py`、`frontend/src/views/TraceCenterView.vue`、`frontend/src/components/TraceComparisonDialog.vue`、`frontend/src/components/TraceHealthPanel.vue`。
