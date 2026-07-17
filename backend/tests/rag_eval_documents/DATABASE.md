# 数据库设计

Alembic 是生产数据库结构的权威来源：`backend/alembic/versions/`。`database/init.sql` 保留为结构参考，不再由 Docker 自动执行。

## 核心表

- `users`、`user_sessions`：用户、角色、权限、refresh 会话与撤销状态。
- `projects`、`project_members`：项目活动/归档状态与 `owner/editor/viewer` 成员授权。
- `agents`、`agent_tools`、`agent_prompt_versions`：AI 员工当前配置、不可变发布历史、人工审批、并发上限和运行时工具白名单。
- `agent_actions`：待审批工具输入、执行结果、决策人和决策时间；状态为 `PENDING/EXECUTED/REJECTED`。
- `agent_runs`：带唯一请求 ID 的 Agent 执行、计费引用、状态、耗时和错误。
- `conversations`、`messages`、`message_feedback`：用户隔离的单人/团队会话、每条发言所属 Agent 与阶段、重新生成关系、工具调用和回答反馈。
- `tasks`、`task_comments`、`requirements`：真人/Agent 指派、标准截止时间、评论和需求状态。
- `documents`、`embeddings`：异步索引状态、内容哈希、版本/标签/来源、文本块、Milvus ID 和降级向量。
- `meetings`、`reports`、`notifications`：协作产物；通知记录接收者、调度时间、投递锁、重试和错误。
- `memory`：项目/Agent 长期记忆和单条滚动摘要。
- `workflow_runs`、`workflow_events`：LangGraph 队列、节点快照、租约、取消/重试状态和 SSE 事件源。
- `workflow_saga_steps`：写工具的输入快照、幂等键、执行结果、补偿动作、合法状态历史、执行/补偿次数和错误；`(workflow_id, idempotency_key)` 唯一。
- `workflow_artifact_publications`：工作流产物到报告或知识文档的幂等发布记录。
- `token_transactions`、`recharge_orders`：余额变更账本与模拟充值单；余额通过条件更新防止并发透支。
- `system_setting_overrides`：加密密钥和非敏感运行时配置覆盖；修改记录写入审计日志。
- `llm_usage`：供应商 token、模型、耗时、usage 来源和估算成本。
- `evaluation_cases`、`evaluation_runs`、`evaluation_results`：回归数据集、运行汇总和逐用例结果。
- `audit_logs`：认证、权限、Agent 工具、文档和工作流关键动作。

## 迁移

当前迁移头为 `20260717_0013`，其中包含版本化 RAG 索引与工作流 Saga 执行日志。

```bash
cd backend
alembic upgrade head
alembic check
```

初始迁移对空库执行静态建表；检测到历史 `users` 表时进入旧库接管分支，补齐新表、兼容列和项目 owner 成员关系。
