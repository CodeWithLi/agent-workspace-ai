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
  "agent_snapshot": {}
}
```

## 节点

1. Requirement Agent
2. Product Agent
3. Architect Agent
4. Project Manager Agent
5. Tester Agent
6. Report Generator

工作流由 LangGraph `StateGraph`、`START`、条件边和 `END` 构建，不使用手写顺序分支。创建工作流时冻结各角色的 Prompt、模型、并发限制和 Prompt 版本；架构师读取真实 PRD，项目经理读取 PRD 与系统设计，测试工程师读取前三阶段产物，避免运行中配置漂移和“多个 Agent 实际各说各话”。每个节点开始和完成时分别写入 `workflow_events`，完成时同步更新 `state_json` 和下一个节点，因此 worker 崩溃后可以从最后一个已提交节点恢复。

## Saga 写操作一致性

任务创建和最终报告创建不是普通节点输出，而是持久化到 `workflow_saga_steps` 的可补偿步骤。状态只允许按以下路径迁移：

`PENDING -> EXECUTING -> COMPLETED -> COMPENSATING -> COMPENSATED`

执行或补偿失败分别进入 `FAILED`、`COMPENSATION_FAILED`，重试只能从对应失败状态继续。每一步执行前保存输入和幂等键，业务写入与 `COMPLETED` 状态在同一数据库事务提交；进程中断后读取执行日志续跑，不依赖模型上下文。

工作流达到最大重试次数或被取消时，按序号逆序补偿：先删除本工作流创建且未被修改的报告，再删除本工作流创建且未被修改的任务。检测到人工修改时拒绝自动删除，工作流进入 `COMPENSATION_FAILED`，阻止同项目启动新工作流并等待人工核对。不可逆的产物发布保持在人工确认和工作流完成之后。

## 暂停与继续

`POST /api/v1/workflow/run` 返回 `202 QUEUED`，后台 dispatcher 认领并执行，默认在 `report` 前进入 `PAUSED`。
`POST /api/v1/workflow/continue` 接收人工反馈后重新入队，最终报告写入 `reports` 表。项目页先读取 `GET /workflow/{id}/events/history` 恢复最近事件，再以 `Last-Event-ID` 连接 `GET /workflow/{id}/events`；SSE 提供重连间隔和心跳，并在连接期间持续复核用户与项目权限。

继续操作只允许对 `PAUSED` 运行执行一次；任务创建按标题幂等，重复继续返回 `409`，不会重复落任务或报告。

创建工作流时锁定项目记录，并检查是否已有 `QUEUED/RUNNING/CANCELLING/PAUSED` 工作流。同一 `request_id` 重试返回已有结果，其他并发工作流返回 `409`。自动重试不重复扣费，达到最大尝试次数或取消后按当前消费流水幂等退款；终态失败的人工重试创建新的幂等消费流水。

dispatcher 使用 PostgreSQL `FOR UPDATE SKIP LOCKED` 支持多副本。`locked_at` 超过租约的运行会被重新认领；取消在节点边界生效，避免提交半个节点的状态。

运行中的 worker 使用 `lease_token` fencing，并以租约时长三分之一为周期续租。所有节点提交和 Saga 写入都会锁定工作流行并校验 token；旧 worker 即使在超时后恢复，也不能提交业务写入。

实现文件：`backend/app/langgraph/workflow.py`。
