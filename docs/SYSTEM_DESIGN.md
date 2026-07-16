# 系统架构设计

## 架构概览

系统采用前后端分离架构：

- Vue3 前端负责工作台、项目空间、聊天和知识库操作。
- FastAPI 后端提供 REST API、JWT 认证、Agent 编排和 RAG 服务。
- PostgreSQL 存储用户、项目、Agent、会话、消息、任务、知识库文档。
- Redis 预留用于缓存、会话和异步任务状态。
- MinIO 用于对象文件存储，当前实现提供本地文件降级。
- Milvus 用于向量检索，当前实现保留服务依赖并提供本地词法检索降级。

## 后端模块

- `api/`：HTTP 路由。
- `agent/`：默认 Agent、LLM 客户端、聊天服务。
- `langgraph/`：多 Agent StateGraph 工作流。
- `rag/`：文件解析、文本切割、检索回答。
- `tools/`：Agent 工具函数。
- `core/`：配置、数据库、安全、日志。

## 异常处理与日志

FastAPI 全局异常处理返回统一错误信息，并通过标准日志记录堆栈。业务异常使用 `HTTPException` 返回明确状态码。
