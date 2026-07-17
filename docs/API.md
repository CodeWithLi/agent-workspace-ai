# API 文档

基础路径：`/api/v1`。除注册、登录、刷新外，业务接口使用 `Authorization: Bearer <access_token>`。

## 认证

- `POST /auth/register`：注册并签发 access token、HttpOnly refresh cookie。
- `POST /auth/login`：登录并创建服务端会话。
- `POST /auth/refresh`：轮换 refresh 会话并签发新 access token。
- `POST /auth/logout`：撤销当前 refresh 会话。
- `GET /users/me`：当前用户。
- `GET /users`：管理员查询用户。
- `PATCH /users/{user_id}`：管理员更新角色、状态和权限。
- `POST /users/{user_id}/revoke-sessions`：撤销用户全部 refresh 会话。

## 项目与任务

- `GET|POST /projects`
- `GET /projects/{project_id}`
- `PATCH|DELETE /projects/{project_id}`：更新、归档或由 owner 删除项目。
- `GET|POST /projects/{project_id}/members`：查看成员、owner 邀请或改角色。
- `DELETE /projects/{project_id}/members/{member_id}`
- `GET|POST /projects/{project_id}/tasks`
- `PATCH /projects/{project_id}/tasks/{task_id}`
- `DELETE /projects/{project_id}/tasks/{task_id}`
- `GET|POST /projects/{project_id}/tasks/{task_id}/comments`
- `GET /projects/{project_id}/activity`

项目角色：`owner`、`editor`、`viewer`。读取允许全部成员；写操作同时要求非 viewer 和 `projects:write` 全局权限。

## Agent 与聊天

- `GET /agents`
- `GET /agents/{agent_id}/tools`
- `PATCH /agents/{agent_id}`：管理员配置 Prompt、模型、Memory、知识库访问和审批策略。
- `GET|POST /agents/{agent_id}/versions`
- `POST /agents/{agent_id}/versions/{version_id}/publish`
- `POST /agents/{agent_id}/versions/{version}/rollback`
- `PATCH /agents/{agent_id}/tools/{tool_id}`：仅管理员。
- `GET /agents/actions`：查看本人待审批/已决工具动作，管理员可查看全部。
- `POST /agents/actions/{action_id}/approve`
- `POST /agents/actions/{action_id}/reject`
- `POST /agents/route`：返回 Agent、置信度和可解释原因。
- `POST /agents/chat`
- `POST /agents/chat/stream`：真实上游 SSE。
- `POST /agents/discussion/stream`：五阶段多 Agent 团队讨论 SSE。
- `GET /agents/conversations`
- `GET /agents/conversations/{conversation_id}/messages`
- `POST /agents/messages/{message_id}/feedback`
- `POST /agents/messages/{message_id}/regenerate`
- `GET|POST /evaluations/cases`、`DELETE /evaluations/cases/{id}`
- `POST /evaluations/run`、`GET /evaluations/runs`

SSE 事件：`thinking`、`tool`、`token`、`error`、`done`。`done` 包含 `conversation_id`、`agent_id` 和 `agent_name`。

团队讨论事件为 `discussion_start`、`speaker_start`、`token`、`speaker_done`、`error`、`done`。每个发言事件包含实际 `agent_id`、名称和阶段；阶段顺序为产品范围、技术架构、质量审查、发布运营、最终方案。后续 Agent 的 Prompt 包含本轮此前全部发言，最终方案由项目经理综合。讨论会话可通过原 `conversation_id` 继续追问，但不能与单人会话模式混用。

聊天请求必须包含客户端生成的唯一 `request_id`。平台创建 `agent_runs` 运行记录、预扣固定 Token，并在失败或流式连接异常时幂等退款；重复请求返回 `409`。并发达到 Agent 上限时返回 `429`。

用户必须拥有 `agents:read`。审批执行前会重新检查项目写权限、Agent 硬白名单、数据库工具启停和发起者状态；重复审批返回 `409`。

## 工作流与知识库

- `POST /workflow/run`
- `POST /workflow/continue`
- `GET /workflow?project_id=...`
- `GET /workflow/{workflow_id}`
- `GET /workflow/{workflow_id}/events`：支持 `Last-Event-ID` 的持久化进度 SSE。
- `GET /workflow/{workflow_id}/saga-steps`：查看写工具执行快照、状态、补偿次数和人工介入原因。
- `POST /workflow/{workflow_id}/cancel`
- `POST /workflow/{workflow_id}/retry`：终态失败后重新扣费并入队。
- `POST /workflow/{workflow_id}/retry-compensation`：仅用于 `COMPENSATION_FAILED`，人工核对业务数据后重试确定性补偿。
- `POST /workflow/{workflow_id}/publish`：将指定工作流产物发布为报告或项目知识文档。
- `GET /knowledge/documents`
- `POST /knowledge/upload`
- `POST /knowledge/search`
- `PATCH /knowledge/documents/{document_id}`：修改标签和来源。
- `GET /knowledge/documents/{document_id}/chunks/{chunk_index}`：定位引用片段。
- `GET /knowledge/documents/{document_id}/index-versions`：按版本倒序返回 parser、chunker、embedding、块数量、状态和激活时间。
- `POST /knowledge/documents/{document_id}/index-versions/{index_version}/activate`：使用 `request_id` 激活历史索引；目标版本的 PostgreSQL 向量会先重新写入 Milvus，当前版本保留为 `SUPERSEDED`。
- `POST /knowledge/documents/{document_id}/retry`
- `POST /knowledge/documents/{document_id}/reindex`
- `DELETE /knowledge/documents/{document_id}`

知识库上传和删除要求 `knowledge:write`；查询和检索只要求项目读取权限。上传返回 `202 QUEUED`，相同范围的重复内容返回 `409` 和已有文档 ID。

`POST /knowledge/search` 支持 `project_id`、`document_ids`、`tags`、`source_labels`、`top_k` 和 `min_score`。结果包含稳定 chunk ID、索引版本、标题路径、页码、sparse/dense/hybrid/rerank 分数和引用；个人文档只能由 owner 检索，项目文档要求当前项目成员身份。

`POST /workflow/run` 需要唯一 `request_id`，返回 `202 QUEUED`。同一项目存在活动工作流时拒绝创建第二条；同一请求重试返回原工作流，不重复扣费。后台 worker 按节点持久化快照，自动重试耗尽或取消后幂等退款。

## AI 原型工作室

- `GET /prototypes`、`GET /prototypes/{prototype_id}`：查询当前用户可访问的原型及不可变版本历史。
- `POST /prototypes/generate`：从项目、可选需求和自然语言目标生成可交互原型。
- `POST /prototypes/{prototype_id}/regenerate`：根据修订意见创建新版本，不覆盖历史版本。
- `POST /prototypes/{prototype_id}/versions/{version}/activate`：切换活动版本；切换到其他版本会把审批状态重置为 `DRAFT`。
- `PATCH /prototypes/{prototype_id}`、`DELETE /prototypes/{prototype_id}`：更新状态或删除原型。
- `GET|POST /prototypes/{prototype_id}/comments`：读取或创建当前版本的页面级评审意见。
- `PATCH /prototypes/{prototype_id}/comments/{comment_id}`：解决或重新打开评审意见。
- `POST /prototypes/{prototype_id}/materialize`：将已批准版本幂等转换为实现任务和结构化验收用例。

批准要求当前版本通过自动质量门禁且没有待处理评审意见。`materialize` 要求客户端提供唯一 `request_id`；同一原型版本重复调用返回已有交付结果，不重复创建任务或用例。

## Token 钱包

- `GET /billing/wallet`：余额、价格和最近流水。
- `POST /billing/recharge`：模拟充值，按配置比例换取 AI Token，要求唯一 `request_id`。
- `GET /billing/orders`：模拟充值单。
- `POST /billing/admin/adjust`：管理员增减 Token。
- `GET /billing/usage`：供应商 token、模型、耗时、来源和估算成本。

默认新用户 1,000 Token、聊天 10 Token、团队讨论 50 Token、完整工作流 100 Token、1 元模拟充值兑换 100 Token，均可通过环境变量或配置中心调整。

## 其他

- `GET /dashboard/stats`
- `GET /search?q=...`
- `GET|POST /requirements`
- `PATCH|DELETE /requirements/{id}`
- `GET|POST /meetings`
- `PATCH|DELETE /meetings/{id}`、`POST /meetings/{id}/tasks`
- `GET|POST /reports`
- `PATCH|DELETE /reports/{id}`
- `GET|POST /notifications`
- `POST /notifications/{notification_id}/send`
- `POST /notifications/{notification_id}/cancel`
- `GET|PATCH /settings`：管理员读取或更新运行时配置；密钥只返回配置状态。
- `POST /settings/test-connection`：测试 LLM、Embedding、Reranker、Docling、Redis、Milvus、MinIO 或 SMTP。
- `GET /audit`：仅管理员，支持 `action`、`project_id`、`limit` 过滤。
- `GET /health`、`GET /health/ready`

Python 服务端管理后台位于 `/admin`，使用独立管理员 Cookie 和 CSRF 校验，不属于 `/api/v1`。
