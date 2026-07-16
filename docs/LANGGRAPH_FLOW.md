# LangGraph 流程

## State

```json
{
  "user_input": "",
  "project_info": {},
  "tasks": [],
  "documents": [],
  "messages": []
}
```

## 工作流

1. 用户需求输入
2. 需求分析节点
3. 产品经理 Agent
4. 架构师 Agent
5. 项目经理 Agent
6. 测试 Agent
7. 生成项目报告

实现位置：`backend/app/langgraph/workflow.py`。

系统优先使用 LangGraph `StateGraph`，当依赖不可用时降级为顺序执行，保证本地开发可运行。
