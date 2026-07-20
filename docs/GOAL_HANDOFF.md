# 多 Agent 长期目标续跑交接

> 更新时间：2026-07-20（Asia/Shanghai）
> 用途：当前电脑停止执行或更换后，在新电脑恢复同一长期目标。
> 本文只记录可提交信息，不包含 `.env`、密钥、数据库数据或本机 IDE 配置。

## 1. 长期目标

把 `agent-workspace-ai` 持续完善为可供真实用户使用、具有吸引力且可审计的完整多 Agent 产品。优先保证：

1. 多 Agent 规划、执行、交接、评审和返修不是演示流程，而是可恢复、可追溯、可验证的真实工作流。
2. AI 产品经理可生成可预览、可交互、可形成验收用例的产品原型。
3. 每轮只合入经过验证的稳定增量，并上传 GitHub。
4. 不以 Token 或单次执行时长为约束，但不能以“无限优化”代替明确验收标准。

长期目标没有绝对的“完美终点”。下次应先完成本文 P0，形成新的稳定里程碑，再从 P1 中逐项选择。

## 2. 仓库恢复信息

- GitHub：`https://github.com/CodeWithLi/agent-workspace-ai.git`
- 分支：`main`
- 当前远端提交：`bb89e31c33893b0cf8f518d3bb6458cd4b0ff51f`
- 当前提交说明：`feat(handoff): 升级 Handoff 合同至 v4 版本支持精确引用验证`
- Codex 目标任务 ID：`019f6fe2-0a25-7e50-a970-0b7891145d26`
- 本机 `.idea/` 未跟踪，属于本机配置，不应提交。

新电脑恢复：

```powershell
git clone https://github.com/CodeWithLi/agent-workspace-ai.git
cd agent-workspace-ai
git checkout main
git pull --ff-only origin main
git rev-parse HEAD
```

`git rev-parse HEAD` 应至少包含上述提交；如果 GitHub 已有后续提交，以远端最新 `main` 为准。

## 3. 当前已完成状态

项目当前已经具有账号权限、项目空间、Agent 路由与会话、混合 RAG、工具审批、真实 LangGraph 工作流、动态团队规划、在线计划审批、检查点恢复、质量门禁、AI 原型、评测发布、Prompt 调优、追踪告警和管理后台等主链路。完整能力清单见 `docs/PRODUCT_EVALUATION.md`。

本轮最新完成 Handoff v4：

- Planner 分支继续认领并完整覆盖稳定的 `AC-xx`。
- 每条 evidence 除 `criterion_ids`、`source_refs` 外，必须为每个来源提供 `source_ref + quote`。
- quote 长度为 12-1000 字；服务端归一化空白后，要求它是当前 PRD、系统设计或直接上游 Handoff 权威材料的精确子串。
- Specialist 生成时接收有界权威材料；解析器首次校验，Quality Gate 按当前 DAG 重建材料后再次校验。
- v4 输入、输出和结构化合同使用独立指纹版本；伪造原文、材料变化、字段篡改和过期上游均会触发定向返修。
- 项目页可渐进展开“已核验原文”，同时保留 Handoff v1-v3 历史兼容。
- SSE/追踪只公开 cited handoff 与 verified citation 数量，不公开 quote 或完整指纹。

本轮已执行的定向验证：

- Handoff v4 有效引用、伪造引用及材料变化用例：通过。
- Specialist 依赖波次与上游 Handoff 工作流用例：通过。
- 前端 `vue-tsc` 类型检查：通过。

本轮之前最近一次全量基线为：后端 `301 passed, 7 skipped`；前端 unit `28 passed`；typecheck、ESLint、build 通过；Playwright `60 passed, 2 skipped`。该基线早于 Handoff v4，不能替代 P0 的全量回归。

## 4. P0：新电脑恢复后必须先完成

### P0-1 全量回归 Handoff v4

目标：证明当前远端 `main` 在全套测试中稳定，而不只是在定向用例中通过。

```powershell
cd backend
python -m pytest -q

cd ..\frontend
npm ci
npm run test:unit
npm run typecheck
npm run lint
npm run build
npx playwright install
npx playwright test
```

验收：

- 无新增失败；跳过项必须是已有、可解释的环境跳过。
- Handoff v1、v2、v3 兼容用例与 v4 精确引用用例同时通过。
- 项目页桌面、375px 竖屏、844×390 横屏均无横向溢出；引用来源和 quote 可读。
- `.idea/`、`.env`、本地数据库和测试产物不进入提交。

### P0-2 真实模型与恢复路径验收

目标：使用真实 LLM 验证 Prompt 能稳定生成合法 citations，并验证失败不会静默放行。

场景：

1. PRD 与系统设计同时被引用，quote 可逐字匹配。
2. 下游引用直接上游 Handoff，且上游返修后旧引用失效、下游被定向返修。
3. 模型改写、拼接或虚构 quote 时，合同为 unstructured v4，Quality Gate 不通过。
4. worker 中断后从检查点恢复，材料重建与输出指纹保持一致。
5. Reviewer 每个 AC 的非弃权票仍绑定当前 Handoff output fingerprint 和具体 evidence 序号。

验收：至少完成一条两波 DAG 的端到端真实运行，并在项目页和追踪页人工核对证据链、引用、返修和恢复状态。

### P0-3 生产栈外部验收

目标：完成代码无法替代的部署与灾备验证。

- 使用 Docker 主机验收 PostgreSQL、Redis、Milvus、MinIO、后端和前端全栈。
- 配置真实 LLM/Embedding、SMTP、HTTPS、强随机 `SECRET_KEY` 和管理员邮箱。
- 执行 PostgreSQL、Milvus/MinIO 备份与恢复演练。
- 接入集中日志、指标告警和数据库慢查询监控。
- 按真实供应商 usage 校准固定 Token 价格。

这些工作依赖外部账号、域名、证书和密钥；没有这些输入时只能完成本地模拟，不能宣称生产验收完成。

## 5. P1：P0 稳定后继续的高价值功能

按价值和依赖顺序建议：

1. 企业身份与租户：SSO/LDAP、组织、团队、租户级数据与配额隔离。
2. 外部通知闭环：Webhook、飞书、钉钉、企业微信、升级策略、重试死信、送达回执和告警容量预测。
3. 商业化计费：真实支付、套餐、发票、月度配额、供应商 usage 对账和异常账单审计。
4. 生产协作强化：外部工单同步、运行审批策略模板、审计导出与企业留存策略。

每项都应遵循：先定义 API/权限/失败语义和验收测试，再实现；不要一次并行展开全部 P1。

## 6. 建议续跑提示词

在新电脑打开仓库后，可以直接发送：

```text
/goal 请读取 docs/GOAL_HANDOFF.md，核对当前 main 与文档中的提交状态，从 P0-1 开始继续长期目标。先运行全量回归；失败则只修复与当前迭代相关的问题。通过后完成 P0-2 的真实模型与恢复路径验收。每个稳定增量都更新 docs/GOAL_HANDOFF.md、提交并推送 GitHub；不要提交 .env、密钥、数据库数据或 .idea。
```

如果新电脑没有真实 provider 或生产环境权限，先完成所有不依赖外部凭据的验证，然后把明确阻塞项和所需输入写回本文，不要伪造通过结果。

## 7. 预计剩余运行时长

以下为连续 Agent 执行时间的粗略范围，不包含等待用户提供外部账号、域名、证书或业务规则的时间：

| 范围 | 预计时间 | 说明 |
|---|---:|---|
| P0-1 全量回归与小范围修复 | 2-4 小时 | 取决于 Playwright、Docker 依赖下载和是否发现回归 |
| P0-2 真实模型与恢复路径验收 | 4-8 小时 | 取决于模型稳定性、限流和返修轮次 |
| P0-3 生产栈、监控与备份恢复 | 8-16 小时 | 需要可用服务器及全部外部凭据 |
| 下一可对外试用的稳定里程碑 | 约 14-28 小时 | 完成 P0；可拆为 1-3 天运行 |
| P1 四组高价值增强 | 约 60-120 小时 | 建议按功能独立迭代，不应一次性合并 |

“完整且完美”的长期目标本身没有可靠的最终倒计时。可验证的近期承诺是：完成 P0 约需 **14-28 小时**；如果连 P1 当前清单也全部实现并回归，累计约需 **74-148 小时**，外部审批与凭据等待时间另计。

## 8. 换电脑前必须另外备份

GitHub 不包含以下内容：

- 当前 `.env` 和真实 API 密钥。
- PostgreSQL、Redis、Milvus、MinIO 的本地数据卷。
- Codex 本机任务历史和附件。
- 原始视频 `C:\Users\Administrator\Desktop\66ef363a1e8626f9cae56064e3cda5e5.mp4`。
- 原始图片附件 `C:\Users\Administrator\.codex\attachments\2c8a0d6d-bad0-4d0e-bb6a-89c130c0147b\image-1.png`。

如仍需这些素材或数据，请在出售电脑前单独复制到加密移动盘或可信云盘。密钥不要提交 GitHub；在新电脑从 `.env.example` 重建配置，并轮换可能已经暴露或无法确认去向的密钥。
