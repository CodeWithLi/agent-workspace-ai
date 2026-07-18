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
4. Planning Agent：生成经过结构校验的动态执行计划。
5. Plan Review：可选人工门禁，批准后才允许启动并行分支，或携带反馈退回 Planner 重做。
6. Specialist Branches：根据已批准计划并行执行 2 至 4 个专业分支并生成结构化 Handoff。
7. Quality Gate：合并确定性检查和测试 Agent 评审，最多触发一轮自动修订。
8. Project Manager Agent
9. Tester Agent
10. Report Generator

工作流由 LangGraph `StateGraph`、`START`、条件边和 `END` 构建，不使用手写顺序分支。创建工作流时冻结各角色的 Prompt、模型、并发限制和 Prompt 版本；架构师读取真实 PRD，动态专家读取需求与架构，项目经理和测试工程师消费完整 Handoff 与质量门禁证据，避免运行中配置漂移和“多个 Agent 实际各说各话”。每个节点开始和完成时分别写入 `workflow_events`，完成时同步更新 `state_json` 和下一个节点，因此 worker 崩溃后可以从最后一个已提交节点恢复。

规划器只允许选择 `test_engineer`、`operations_analyst`、`knowledge_admin`、`notification_secretary`，无效模型输出使用确定性默认计划。项目 UI 创建运行时开启 `require_plan_approval`，图在 `plan_review` 持久化暂停；`APPROVE` 设置 `plan_approved` 后进入专业分支，`REVISE` 必须携带反馈并从 `planning` 重新生成计划。`specialists` 节点再次校验批准标志，防止恢复或客户端绕过门禁。专业分支通过 `asyncio.gather` 并行执行；质量门禁检查角色覆盖、交付内容、成功标准和并行广度，再合并独立评审结果。自动修订仍未通过时，工作流暂停在 `quality_review`，人工反馈只重跑指定分支。

除通用 `NODE_STARTED/NODE_COMPLETED` 外，事件流还会记录 `PLAN_CREATED`、`PLAN_APPROVED`、`PLAN_REVISION_REQUESTED`、`BRANCH_STARTED`、`BRANCH_COMPLETED`、`QUALITY_GATE_PASSED`、`REVISION_REQUESTED` 和 `QUALITY_GATE_FAILED`，前端可据此展示计划、交接、质量分数和人工修订状态。计划事件 payload 只保留分支数、轮次和反馈字符数，反馈正文不会进入事件或审计详情。人工重试时，父运行写入 `RETRY_CREATED`，新子运行写入 `RETRY_QUEUED/QUEUED`；运行干预写入 `PAUSE_REQUESTED`、`PAUSED` 和 `INTERVENTION_APPLIED`。

## 运行追踪与成本归属

`/traces` 运行追踪中心复用 `workflow_runs`、`workflow_events`、`llm_usage` 和 `agents`，不复制工作流状态或新增影子遥测表。服务端将事件配对为四类 Span：创建到首次启动的排队、`NODE_STARTED/NODE_COMPLETED` 节点、`BRANCH_STARTED/BRANCH_COMPLETED` 并行分支，以及 `PAUSED` 到重新入队/继续之间的人工等待。未闭合 Span 使用当前时间或工作流终态时间计算，并保留 `ACTIVE`、`PAUSED`、`FAILED`、`CANCELLED` 状态。

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
`POST /api/v1/workflow/continue` 可在 `plan_review` 接收 `APPROVE/REVISE` 决策、在 `quality_review` 接收修订方向，或在 `report` 前接收最终确认意见，随后重新入队。最终报告写入 `reports` 表。项目页先从 `GET /workflow/{id}/events/history` 恢复最近事件，再以 `Last-Event-ID` 连接 `GET /workflow/{id}/events`；凭证过期时只执行一次共享刷新，断线后按服务端提示指数退避重连，已确认游标不会重复应用。

继续操作只允许对 `PAUSED` 运行执行一次；任务创建按标题幂等，重复继续返回 `409`，不会重复落任务或报告。

### 操作员安全干预

`POST /api/v1/workflow/{id}/pause` 不会中断正在进行的模型调用，也不会留下半个节点状态。暂停请求与节点提交都锁定同一 `workflow_runs` 行：如果请求先提交，`begin_node/complete_node` 在最近边界发现请求；如果节点先提交，请求会在下一节点开始前被发现。`complete_node` 总是先原子持久化 `state_json`、`current_node` 和 `NODE_COMPLETED`，再抛出受控暂停信号，worker 随后释放租约并转为 `PAUSED`。

暂停请求使用 `pause_request_id` 幂等，保存请求人、时间和最长 1000 字的原因。恢复时必须提供最长 4000 字的指令；平台把原因、指令和恢复节点追加到最近 10 条 `interventions`，并将该结构化上下文传给需求、产品、架构、规划、专业分支、质量门禁、项目计划、测试和报告 Agent。追踪事件只公开干预类型和字符数，不返回原因或指令正文。

排队运行可以在 worker 认领前立即暂停。若请求到达时最终报告节点已提交并进入 `completed`，平台记录 `PAUSE_SKIPPED` 并正常完成，避免出现无法恢复的 `PAUSED/completed` 组合。取消优先于暂停；失败补偿和取消终态会清理未应用的暂停元数据。

创建工作流时锁定项目记录，并检查是否已有 `QUEUED/RUNNING/CANCELLING/PAUSED` 工作流。同一 `request_id` 重试返回已有结果，其他并发工作流返回 `409`。自动重试不重复扣费，达到最大尝试次数或取消后按当前消费流水幂等退款。

终态失败的人工重试不会修改原 `workflow_runs` 行。平台创建带 `parent_workflow_id`、`retry_from_node` 和递增 `retry_sequence` 的新运行，复制冻结的 Agent 配置、人工反馈和最后已提交状态，并创建独立消费流水；子运行失败只退还自己的账单，也可继续创建孙运行。源运行的 `FAILED` 状态、结束时间、错误、事件、模型用量和账单保持不变，追踪中心因此可以分别比较每次尝试。

Saga 补偿可能把 `current_node` 回退到更早的写节点。重试前会比较最近一次 `NODE_STARTED` 与回退节点；确认发生回退时，只移除该检查点及后续的任务、测试、报告文档和对应消息，保留更早的需求、PRD、架构、执行计划、专业 Handoff 与质量门禁证据。

dispatcher 使用 PostgreSQL `FOR UPDATE SKIP LOCKED` 支持多副本。`locked_at` 超过租约的运行会被重新认领；取消在节点边界生效，避免提交半个节点的状态。

运行中的 worker 使用 `lease_token` fencing，并以租约时长三分之一为周期续租。所有节点提交和 Saga 写入都会锁定工作流行并校验 token；旧 worker 即使在超时后恢复，也不能提交业务写入。

实现文件：`backend/app/langgraph/workflow.py`、`backend/app/observability.py`、`backend/app/services/trace_alerts.py`、`frontend/src/views/TraceCenterView.vue`、`frontend/src/components/TraceComparisonDialog.vue`、`frontend/src/components/TraceHealthPanel.vue`。
