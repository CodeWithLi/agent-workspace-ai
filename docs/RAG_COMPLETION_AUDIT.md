# RAG Goal 完成审计

更新时间：2026-07-18

本文件按 Goal 的原始完成条件记录证据。`已实现` 仅表示代码和本地测试存在；需要真实外部服务或业务语料的项目，在绿色 artifact 到位前保持 `待外部证据`。不能用 skipped test、本地 fallback 或工作流定义代替运行结果。

| 要求 | 当前状态 | 权威证据 |
|---|---|---|
| GitHub 高 Star 候选、许可证、活跃度、格式能力与集成成本比较 | 已实现 | `docs/RAG_PIPELINE_ADR.md`；候选链接到 LangChain、LlamaIndex、RAGFlow、Docling、Unstructured、MinerU、Chonkie 官方仓库 |
| 不按 Star 盲选，使用项目语料 A/B | 部分完成 | `scripts/evaluate_rag_chunking.py` 的固定仓库语料门禁已通过；真实外部 A/B 尚待绿色报告 |
| `ParsedDocument -> DocumentElement -> KnowledgeChunk` 统一模型 | 已实现 | `backend/app/rag/types.py`、解析/分块单元与属性测试 |
| Markdown/DOCX/PDF 结构、表格、代码、标题和页码 | 已实现 | `backend/app/rag/parsers.py`、`tests/test_rag_processing.py` |
| 高级版面/OCR、bbox 与阅读顺序 | 已实现，真实服务已验证 | Docling Serve 1.26.0 lossless JSON `1.26-json-v1`：本地及远程真实 DOCX 表格、扫描 PDF OCR、页码/bbox 测试通过 |
| 中文/英文 token 边界、父子/递归/语义/表格专用分块 | 已实现 | `backend/app/rag/chunking.py`、Chonkie 可选语义策略、token/property/table 测试 |
| 稳定 chunk ID、元素/页码/标题元数据与可追溯引用 | 已实现 | chunking、chunk API、引用过滤测试 |
| 批量 embedding、父向量、增量复用与模型变更重算 | 已实现 | `backend/app/rag/service.py`、`tests/test_knowledge_jobs.py` |
| 幂等任务、重试、失败清理、原子激活、版本回滚 | 已实现 | 版本化索引测试、Milvus 故障注入测试、Alembic `0016 -> 0015 -> 0016` 本地往返 |
| BM25 + child dense + parent dense、RRF、查询改写、过滤 | 已实现，真实服务已验证 | `service.py`、`vector_store.py`、Milvus 协议测试；`CI #7/#8` 的 PostgreSQL + Milvus v4 job 绿色 |
| Cross-Encoder rerank、父块扩展、去重、token 限界 | 已实现，外部模型待证据 | reranker/context 单元测试；`RAG External Quality Gate` 尚无报告 |
| 引用校验、忠实回答与拒答 | 已实现，judge 待证据 | 确定性引用测试与严格 judge JSON 解析；真实 judge 指标尚无报告 |
| 项目/owner 隔离及过滤下推 | 已实现，真实服务已验证 | SQL 权限过滤、Milvus `owner_id`/`document_id` ANN 表达式测试；真实隔离 job 已绿色 |
| 提示注入、文件签名、解压/页数/元素/chunk 资源限制 | 已实现 | parser/chunker 安全测试与运行时配置校验 |
| 指标、成本、延迟与运维告警 | 已实现 | Prometheus 指标、`llm_usage`、`docs/OPERATIONS.md`；真实 p95/成本报告待外部门禁 |
| 后台策略、索引版本、重建、激活与回滚 | 已实现 | API、runtime setting、Knowledge UI 与 E2E 测试 |
| native/Docling/Unstructured/MinerU 同样本比较 | 已实现，Linux 全矩阵已验证 | `RAG Parser Benchmark #2` 在同一 corpus hash 上完成四后端报告，严格 comparison gate 绿色并留存 artifact |
| 真实业务复杂 PDF/DOCX/中文表格/公式/代码验证 | 缺失 | 需要业务方提供脱敏样本；仓库合成样本不能替代 |
| 新方案显著优于 `900/140` | 未证明 | 离线 Context Precision `0.1972 -> 0.2250`，但 Recall/MRR/nDCG 均仍为 `0.6667`；外部 A/B 要求至少一个主检索指标提升 `0.05`，尚无报告 |

## 当前验收证据

- 后端全量测试最近一次结果：`123 passed, 2 skipped`；两个 skip 需要真实 PostgreSQL/Milvus 和 Docling。
- 前端当前验证：ESLint 通过、`10 passed` unit tests、TypeScript/Vite production build 通过。
- 固定语料门禁通过：标题元数据 `0 -> 1.0`，最大 chunk `676 -> 391 tokens`，索引 token `7201 -> 6990`，Context Precision `0.1972 -> 0.2250`。
- native parser 基准：成功率 `0.6667`、marker recall `0.6667`、结构 recall `0.3333`、阅读顺序 `0.6667`、PDF 页码覆盖 `0.5`、bbox 覆盖 `0`。
- Docling Serve 1.26.0 真实集成测试：DOCX 表格与扫描 PDF OCR 通过；同样本质量分 `1.0`、p95 `12.79 s`、峰值内存 `2,112.6 MB`、本地环境加模型 `2,592.67 MB`。
- MinerU 3.4.4 pipeline 同样本质量分 `1.0`、p95 `60.41 s`、峰值内存 `1,811.98 MB`、本地环境加模型 `2,678.15 MB`；实测发现并补齐其未声明的 `six` 依赖。
- Unstructured 0.24.1 的 DOCX 单项通过；本机 Xeon E5-2680 v2 无 AVX2，ONNX Windows wheel 在 PDF 路径原生加载失败，不能据此给出候选质量结论。
- 远程 `CI #6` 的 compose/frontend 已通过；backend 与 rag-integration 都在加载 `tests/conftest.py` 时因 `ModuleNotFoundError: No module named 'app'` 以 pytest 退出码 `4` 失败，尚未执行测试逻辑。workflow 已统一改用 `python -m pytest`，修复结果仍须以新的远程运行证明。
- 远程 [`CI #7`](https://github.com/CodeWithLi/agent-workspace-ai/actions/runs/29629583160) 与 [`CI #8`](https://github.com/CodeWithLi/agent-workspace-ai/actions/runs/29629841019) 整套绿色；真实 PostgreSQL + Milvus v4 的多向量、owner 隔离、并发和 p95 集成 job 已执行通过。
- 远程 [`RAG Docling Integration #2`](https://github.com/CodeWithLi/agent-workspace-ai/actions/runs/29629854246) 绿色；官方 v1.26.0 CPU 镜像固定到不可变 digest，真实 DOCX 表格和扫描 PDF OCR 测试通过。
- 远程 [`RAG Parser Benchmark #2`](https://github.com/CodeWithLi/agent-workspace-ai/actions/runs/29629969071) 全矩阵及严格 comparison gate 绿色，artifact 保留 30 天。共同 corpus hash 为 `70e00e55...3dea1c`；质量排序为 MinerU `1.0000`、Docling `0.9167`、Unstructured `0.9167`、native `0.4792`。
- 所有 workflow 通过 `actionlint 1.7.12`，Python compile 与 `git diff --check` 通过。

## 阻止 Goal 完成的证据缺口

1. `RAG External Quality Gate` 必须使用真实多语 embedding、semantic chunker、reranker、回答模型和 judge，且相对旧方案至少一个主检索指标提升 `0.05`。仓库当前没有 Actions Secrets，本地也仅配置了 LLM，缺少独立 embedding 与 reranker 服务配置。
2. 必须加入业务方脱敏复杂文档并复跑解析、检索、引用和拒答门禁。

上述两项全部满足前，Goal 必须保持 active。
