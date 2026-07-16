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

## 暂停与继续

`POST /api/v1/workflow/run` 默认在 `report` 前暂停，返回 `PAUSED`。
`POST /api/v1/workflow/continue` 接收人工反馈后继续生成最终报告，并写入 `reports` 表。

实现文件：`backend/app/langgraph/workflow.py`。
