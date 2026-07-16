# Agent 设计

所有 Agent 统一通过 `backend/app/core/llm.py:get_llm()` 使用 OpenAI-compatible LLM，不允许独立初始化模型。

## 路由

- 用户显式 `agent_id`：最高优先级，不存在时返回 404，不静默降级。
- 文本明确提及角色：置信度 0.99。
- 其余消息使用角色专属加权意图词；接近的候选降低置信度并保留原因。
- 无明确意图交给产品经理澄清。
- 已有会话固定 Agent；切换角色要求新会话，避免角色和 Memory 漂移。

## 工具

8 个默认角色通过 Tool Registry 使用 `context_search`、`knowledge_search`、`task_create`、`requirement_create`、`report_generate`、`notification_create`、`meeting_summary`、`architecture_generate`、`testcase_create`、`analytics_report`。

运行时允许集合 = 代码角色硬白名单 ∩ 数据库启用白名单 ∩ 用户角色。数据库存在配置时，空集合表示全部禁用，不会回退到 Agent 声明。读取项目上下文可自动执行；写任务、报告、通知等工具必须命中明确动作意图。工具名称和资源 ID 写入审计日志，不复制聊天正文。

`knowledge_access=false` 会在运行时移除 `knowledge_search`，不能只靠 Prompt 约束。用户还必须拥有 `agents:read`；涉及项目写入时叠加 `projects:write` 和项目成员角色。

## 人工审批

- 产品经理、项目经理、架构师、会议纪要员和通知秘书默认开启人工确认，可由管理员逐 Agent 调整。
- 当前聊天中的 `task_create` 在执行前写入 `agent_actions`，相同会话和输入复用同一条待审批记录。
- 批准使用数据库行锁；执行前重新检查发起者状态、项目写权限、代码硬白名单和数据库工具权限。
- 已执行或已拒绝动作不能再次决策；审批和拒绝均写入审计日志。

## 并发与幂等

- 每个 Agent 配置 `concurrency_limit`，API 和 StateGraph 节点统一申请执行槽位。
- PostgreSQL/Redis 部署使用带过期时间的 Redis Sorted Set 租约，支持多 Uvicorn 实例；活跃租约会周期续期，异常和断连在 `finally` 释放，进程崩溃由租约过期恢复。
- Redis 不可用时退化到按 Agent 隔离的进程内动态限流器，运行中修改并发上限仍会立即生效；降级模式保持单实例正确性，但不承诺跨实例限流。
- 每次聊天创建唯一 `agent_runs.request_id`，重复请求不会重复推理或扣费。

## Token 计费

平台采用固定成本预扣，不伪装为模型供应商的精确 token usage。余额通过数据库条件 `UPDATE` 原子扣减；执行失败生成唯一退款流水，重复失败回调不会重复退款。

## Memory

- 短期：最近 20 条中按 12,000 字符预算截取。
- 用户偏好：Redis。
- 项目：PostgreSQL，普通记忆固定窗口，旧内容合并为每个项目/Agent 唯一滚动摘要，摘要最大 4,000 字符。
