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
- `documents`：异步任务状态、内容哈希、文档版本/标签/来源、活动与待构建索引版本、当前 parser/chunker 和块统计。
- `document_elements`：按索引版本保存标题、段落、表格、代码等解析元素，以及标题路径、页码、字符范围和稳定 ID。
- `document_index_versions`：每次构建的 parser、chunker、embedding 配置、状态、规模、错误和激活时间；`(document_id, version)` 唯一。
- `embeddings`：按索引版本保存 child/parent 块、稳定 ID、标题/页码元数据、Milvus ID，以及 child/parent PostgreSQL 降级向量。
- `meetings`、`reports`、`notifications`：协作产物；通知记录接收者、调度时间、投递锁、重试和错误。
- `memory`：项目/Agent 长期记忆和单条滚动摘要。
- `workflow_runs`、`workflow_events`：LangGraph 队列、节点快照、租约、取消状态、不可变父子重试谱系、安全暂停元数据和 SSE 事件源；`pause_request_id` 提供请求幂等，`intervention_count` 记录已生效干预次数。
- `workflow_saga_steps`：写工具的输入快照、幂等键、执行结果、补偿动作、合法状态历史、执行/补偿次数和错误；`(workflow_id, idempotency_key)` 唯一。
- `workflow_artifact_publications`：工作流产物到报告或知识文档的幂等发布记录。
- `product_prototypes`、`product_prototype_versions`：原型元数据、活动版本和不可变 DSL/Agent 轨迹/质量证据。
- `prototype_review_comments`：按原型版本和页面保存待处理/已解决评审意见及解决人。
- `prototype_test_cases`、`product_prototype_materializations`：批准版本生成的结构化验收用例和幂等交付记录；任务通过 `source_prototype_*` 字段反向追溯来源。
- `token_transactions`、`recharge_orders`：余额变更账本与模拟充值单；余额通过条件更新防止并发透支。
- `system_setting_overrides`：加密密钥和非敏感运行时配置覆盖；修改记录写入审计日志。
- `llm_usage`：供应商 token、模型、耗时、usage 来源和估算成本。
- `evaluation_cases`：跨 Agent 角色的评测用例、证据规则、Rubric、阈值和权重；删除操作采用归档以保留历史。
- `evaluation_suite_revisions`：按内容指纹去重的不可变测试集快照。
- `evaluation_runs`、`evaluation_results`：持久化异步运行、冻结 Agent 版本、租约进度、基线门禁、逐案例多维分数与证据。
- `audit_logs`：认证、权限、Agent 工具、文档和工作流关键动作。

## 迁移

当前迁移头为 `20260718_0022`；工作流安全干预位于 `20260718_0022`，不可变重试谱系位于 `20260718_0021`，持久化追踪告警位于 `20260718_0020`。以 `alembic heads` 的输出为准，不要手工跳过中间迁移。

```bash
cd backend
alembic upgrade head
alembic check
```

初始迁移对空库执行静态建表；检测到历史 `users` 表时进入旧库接管分支，补齐新表、兼容列和项目 owner 成员关系。

RAG 重建先写入新的 `STAGING` 版本。只有解析、embedding、PostgreSQL 持久化和 Milvus 写入全部成功后，事务才把新版本切为 `ACTIVE` 并把旧版本标为 `SUPERSEDED`。失败不得删除活动版本；回滚从 PostgreSQL 保存的向量重建 Milvus 数据后再原子切换活动版本。
