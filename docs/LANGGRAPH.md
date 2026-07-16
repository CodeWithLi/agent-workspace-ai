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
  "report": ""
}
```

## 节点

1. Requirement Agent
2. Product Agent
3. Architect Agent
4. Project Manager Agent
5. Tester Agent
6. Report Generator

工作流由 LangGraph `StateGraph`、`START`、条件边和 `END` 构建，不使用手写顺序分支。每个节点读取数据库中对应 AI 员工的 System Prompt、模型与并发限制，前一节点产物进入后一节点上下文。业务状态持久化在 `state_json`，运行状态和当前节点保存在 `workflow_runs`。

## 暂停与继续

`POST /api/v1/workflow/run` 默认在 `report` 前暂停，返回 `PAUSED`。
`POST /api/v1/workflow/continue` 接收人工反馈后继续生成最终报告，并写入 `reports` 表。

继续操作只允许对 `PAUSED` 运行执行一次；任务创建按标题幂等，重复继续返回 `409`，不会重复落任务或报告。

创建工作流时锁定项目记录，并检查是否已有 `RUNNING/PAUSED` 工作流。同一 `request_id` 重试返回已有结果，其他并发工作流返回 `409`。工作流只在首次创建时预扣固定 Token，继续执行不二次扣费；初始节点或人工确认后的报告节点失败都会按原消费流水幂等退款。

实现文件：`backend/app/langgraph/workflow.py`。
