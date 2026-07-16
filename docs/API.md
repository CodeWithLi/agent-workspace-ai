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
- `GET|POST /projects/{project_id}/members`：查看成员、owner 邀请或改角色。
- `DELETE /projects/{project_id}/members/{member_id}`
- `GET|POST /projects/{project_id}/tasks`
- `PATCH /projects/{project_id}/tasks/{task_id}`

项目角色：`owner`、`editor`、`viewer`。读取允许全部成员；写操作同时要求非 viewer 和 `projects:write` 全局权限。

## Agent 与聊天

- `GET /agents`
- `GET /agents/{agent_id}/tools`
- `PATCH /agents/{agent_id}`：管理员配置 Prompt、模型、Memory、知识库访问和审批策略。
- `PATCH /agents/{agent_id}/tools/{tool_id}`：仅管理员。
- `GET /agents/actions`：查看本人待审批/已决工具动作，管理员可查看全部。
- `POST /agents/actions/{action_id}/approve`
- `POST /agents/actions/{action_id}/reject`
- `POST /agents/route`：返回 Agent、置信度和可解释原因。
- `POST /agents/chat`
- `POST /agents/chat/stream`：真实上游 SSE。
- `GET /agents/conversations`
- `GET /agents/conversations/{conversation_id}/messages`

SSE 事件：`thinking`、`tool`、`token`、`error`、`done`。`done` 包含 `conversation_id`、`agent_id` 和 `agent_name`。

用户必须拥有 `agents:read`。审批执行前会重新检查项目写权限、Agent 硬白名单、数据库工具启停和发起者状态；重复审批返回 `409`。

## 工作流与知识库

- `POST /workflow/run`
- `POST /workflow/continue`
- `GET /knowledge/documents`
- `POST /knowledge/upload`
- `POST /knowledge/search`
- `DELETE /knowledge/documents/{document_id}`

知识库上传和删除要求 `knowledge:write`；查询和检索只要求项目读取权限。

## 其他

- `GET /dashboard/stats`
- `GET /search?q=...`
- `GET|POST /requirements`
- `GET|POST /meetings`
- `GET|POST /reports`
- `GET|POST /notifications`
- `POST /notifications/{notification_id}/send`
- `POST /notifications/{notification_id}/cancel`
- `GET /settings`：仅管理员。
- `GET /audit`：仅管理员，支持 `action`、`project_id`、`limit` 过滤。
- `GET /health`、`GET /health/ready`
