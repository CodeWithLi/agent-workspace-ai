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
  "specialist_handoffs": [],
  "quality_gate": {},
  "revision_round": 0,
  "revision_feedback": ""
}
```

## 节点

1. Requirement Agent
2. Product Agent
3. Architect Agent
4. Planning Agent：生成经过结构校验的动态执行计划。
5. Specialist Branches：并行执行 2 至 4 个专业分支并生成结构化 Handoff。
6. Quality Gate：合并确定性检查和测试 Agent 评审，最多触发一轮自动修订。
7. Project Manager Agent
8. Tester Agent
9. Report Generator

工作流由 LangGraph `StateGraph`、`START`、条件边和 `END` 构建，不使用手写顺序分支。创建工作流时冻结各角色的 Prompt、模型、并发限制和 Prompt 版本；架构师读取真实 PRD，动态专家读取需求与架构，项目经理和测试工程师消费完整 Handoff 与质量门禁证据，避免运行中配置漂移和“多个 Agent 实际各说各话”。每个节点开始和完成时分别写入 `workflow_events`，完成时同步更新 `state_json` 和下一个节点，因此 worker 崩溃后可以从最后一个已提交节点恢复。

规划器只允许选择 `test_engineer`、`operations_analyst`、`knowledge_admin`、`notification_secretary`，无效模型输出使用确定性默认计划。专业分支通过 `asyncio.gather` 并行执行；质量门禁检查角色覆盖、交付内容、成功标准和并行广度，再合并独立评审结果。自动修订仍未通过时，工作流暂停在 `quality_review`，人工反馈只重跑指定分支。

除通用 `NODE_STARTED/NODE_COMPLETED` 外，事件流还会记录 `PLAN_CREATED`、`BRANCH_STARTED`、`BRANCH_COMPLETED`、`QUALITY_GATE_PASSED`、`REVISION_REQUESTED` 和 `QUALITY_GATE_FAILED`，前端可据此展示计划、交接、质量分数和人工修订状态。

## 运行追踪与成本归属

`/traces` 运行追踪中心复用 `workflow_runs`、`workflow_events`、`llm_usage` 和 `agents`，不复制工作流状态或新增影子遥测表。服务端将事件配对为四类 Span：创建到首次启动的排队、`NODE_STARTED/NODE_COMPLETED` 节点、`BRANCH_STARTED/BRANCH_COMPLETED` 并行分支，以及 `PAUSED` 到重新入队/继续之间的人工等待。未闭合 Span 使用当前时间或工作流终态时间计算，并保留 `ACTIVE`、`PAUSED`、`FAILED`、`CANCELLED` 状态。

模型调用先按 `workflow_id` 关联，再使用 Agent 角色和调用完成时间归属到最具体的并行分支；无法匹配分支时才归属外层节点，因此同一调用不会在分支与父节点重复累计。运行详情分别展示总耗时、排队、Agent 计算、人工等待和剩余协调开销。汇总中的运行数、状态、Token、成本和趋势是数据库聚合；P95、Agent 性能与节点瓶颈为显式标记截断的最近样本分析。

跨运行基线对比只接受同一项目的两次已结束运行。指标使用 5% 相对容差与最小绝对变化过滤噪声，分别对齐运行结果、端到端阶段、Agent 角色及节点/分支聚合；结论区分 `IMPROVED`、`REGRESSED`、`MIXED` 和 `UNCHANGED`。Token 或成本降低只表示效率改善，不替代内容质量评测。

追踪属于运行元数据视图：响应不读取或返回 `state_json`、Prompt、人工反馈和产物正文，事件 payload 使用字段允许列表。管理员可查看全平台运行，普通成员只能查看本人发起且仍可访问对应项目的运行。

## Saga 写操作一致性

任务创建和最终报告创建不是普通节点输出，而是持久化到 `workflow_saga_steps` 的可补偿步骤。状态只允许按以下路径迁移：

`PENDING -> EXECUTING -> COMPLETED -> COMPENSATING -> COMPENSATED`

执行或补偿失败分别进入 `FAILED`、`COMPENSATION_FAILED`，重试只能从对应失败状态继续。每一步执行前保存输入和幂等键，业务写入与 `COMPLETED` 状态在同一数据库事务提交；进程中断后读取执行日志续跑，不依赖模型上下文。

工作流达到最大重试次数或被取消时，按序号逆序补偿：先删除本工作流创建且未被修改的报告，再删除本工作流创建且未被修改的任务。检测到人工修改时拒绝自动删除，工作流进入 `COMPENSATION_FAILED`，阻止同项目启动新工作流并等待人工核对。不可逆的产物发布保持在人工确认和工作流完成之后。

## 暂停与继续

`POST /api/v1/workflow/run` 返回 `202 QUEUED`，后台 dispatcher 认领并执行，默认在 `report` 前进入 `PAUSED`。
`POST /api/v1/workflow/continue` 可在 `quality_review` 接收修订方向，或在 `report` 前接收最终确认意见，随后重新入队。最终报告写入 `reports` 表。项目页先从 `GET /workflow/{id}/events/history` 恢复最近事件，再以 `Last-Event-ID` 连接 `GET /workflow/{id}/events`；凭证过期时只执行一次共享刷新，断线后按服务端提示指数退避重连，已确认游标不会重复应用。

继续操作只允许对 `PAUSED` 运行执行一次；任务创建按标题幂等，重复继续返回 `409`，不会重复落任务或报告。

创建工作流时锁定项目记录，并检查是否已有 `QUEUED/RUNNING/CANCELLING/PAUSED` 工作流。同一 `request_id` 重试返回已有结果，其他并发工作流返回 `409`。自动重试不重复扣费，达到最大尝试次数或取消后按当前消费流水幂等退款；终态失败的人工重试创建新的幂等消费流水。

dispatcher 使用 PostgreSQL `FOR UPDATE SKIP LOCKED` 支持多副本。`locked_at` 超过租约的运行会被重新认领；取消在节点边界生效，避免提交半个节点的状态。

运行中的 worker 使用 `lease_token` fencing，并以租约时长三分之一为周期续租。所有节点提交和 Saga 写入都会锁定工作流行并校验 token；旧 worker 即使在超时后恢复，也不能提交业务写入。

实现文件：`backend/app/langgraph/workflow.py`、`backend/app/observability.py`、`frontend/src/views/TraceCenterView.vue`、`frontend/src/components/TraceComparisonDialog.vue`。
