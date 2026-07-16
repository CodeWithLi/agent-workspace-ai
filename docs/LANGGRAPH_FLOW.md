# LangGraph 流程

本文件是兼容入口，权威设计见 [LANGGRAPH.md](LANGGRAPH.md)。

真实执行链为：Requirement → Product → Architect → Project Manager → Tester → 人工确认 → Report。实现使用 LangGraph `StateGraph`，状态持久化到 PostgreSQL，可在报告节点前暂停并通过 API 继续。
