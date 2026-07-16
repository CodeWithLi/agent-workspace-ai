# 数据库设计

Alembic 是生产数据库结构的权威来源：`backend/alembic/versions/`。`database/init.sql` 保留为结构参考，不再由 Docker 自动执行。

## 核心表

- `users`、`user_sessions`：用户、角色、权限、refresh 会话与撤销状态。
- `projects`、`project_members`：项目与 `owner/editor/viewer` 成员授权。
- `agents`、`agent_tools`：AI 员工定义、人工审批策略和运行时工具白名单。
- `agent_actions`：待审批工具输入、执行结果、决策人和决策时间；状态为 `PENDING/EXECUTED/REJECTED`。
- `conversations`、`messages`：用户隔离的连续会话、工具调用和执行说明。
- `tasks`、`requirements`：任务状态和需求分析。
- `documents`、`embeddings`：对象元数据、文本块、Milvus ID 和降级向量。
- `meetings`、`reports`、`notifications`：协作产物；通知记录接收者、调度时间、投递锁、重试和错误。
- `memory`：项目/Agent 长期记忆和单条滚动摘要。
- `workflow_runs`：LangGraph 状态快照、暂停和继续。
- `audit_logs`：认证、权限、Agent 工具、文档和工作流关键动作。

## 迁移

```bash
cd backend
alembic upgrade head
alembic check
```

初始迁移对空库执行静态建表；检测到历史 `users` 表时进入旧库接管分支，补齐新表、兼容列和项目 owner 成员关系。
