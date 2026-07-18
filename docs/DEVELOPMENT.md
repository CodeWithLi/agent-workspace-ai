# 开发计划

## 第一阶段：初始化项目结构

完成前端、后端、数据库、Docker、docs 目录。

## 第二阶段：数据库和用户系统

完成 SQLAlchemy 模型、初始化 SQL、注册、登录、JWT、用户信息。

## 第三阶段：项目空间

完成项目创建、项目详情、项目任务列表与创建。

## 第四阶段：Agent 系统

完成默认 Agent 初始化、Agent 列表、聊天、流式输出。

## 第五阶段：LangGraph 流程

完成 `StateGraph` 多 Agent 工作流和状态输出。

## 第六阶段：RAG 知识库

完成文档上传、解析、切割、索引记录、搜索和增强回答。

## 第七阶段：Vue 页面

完成登录、工作台、项目空间、AI 聊天、知识库页面。

## 第八阶段：Docker 部署

完成 PostgreSQL、Redis、Milvus、MinIO、后端、前端一键启动。

## 生产化补强

已完成 refresh 会话轮换、项目成员授权、Agent 意图路由、Memory 限界、混合 RAG、真实 StateGraph、工具人工审批、通知投递 worker、管理员用户中心、Alembic 迁移、审计和桌面/移动端浏览器验收。

已完成 Token 钱包与模拟充值、原子扣费和幂等退款、Agent 运行记录与僵死回收、Redis 并发租约续期、动态本地限流、多 Agent 工作流互斥与计费、Python/Jinja 管理后台、可读工作流产物视图和跨域 SSE API 基址统一。测试数量随功能演进，不在文档中固化；本地使用 `pytest -q`、前端 unit/E2E 和 RAG 评测脚本确认当前状态。

AI 原型工作室使用产品经理定义、JSON Schema 约束的交互架构、确定性结构修复、测试 Agent 门禁和有界返修闭环。结构修复只补齐安全导航链与必要主操作，不改写业务字段和文案；每个模型与本地修复步骤都会写入版本轨迹。开发机后端不在默认 `8000` 端口时，可在启动 Vite 前设置 `VITE_API_PROXY`，例如 `VITE_API_PROXY=http://127.0.0.1:8002 npm run dev`。

解析器同样本基准的本地 native 烟测：

```bash
pip install -r backend/requirements.txt -r backend/requirements-rag-parser-benchmark.txt
python scripts/benchmark_rag_parsers.py generate --output-dir .run/parser-corpus
python scripts/benchmark_rag_parsers.py run --backend native --corpus-dir .run/parser-corpus --output .run/parser-native.json
```

Docling、Unstructured 和 MinerU 的隔离环境、模型与资源测量由 `RAG Parser Benchmark` 工作流负责。本地未安装某个解析器时生成的失败报告仅用于验证异常路径，不能作为发布证据。
