# RAG Goal 完成审计

更新时间：2026-07-18

本文件按 Goal 的原始完成条件记录证据。`已实现` 仅表示代码和本地测试存在；需要真实外部服务或业务语料的项目，在绿色 artifact 到位前保持 `待外部证据`。不能用 skipped test、本地 fallback 或工作流定义代替运行结果。

| 要求 | 当前状态 | 权威证据 |
|---|---|---|
| GitHub 高 Star 候选、许可证、活跃度、格式能力与集成成本比较 | 已实现 | `docs/RAG_PIPELINE_ADR.md`；候选链接到 LangChain、LlamaIndex、RAGFlow、Docling、Unstructured、MinerU、Chonkie 官方仓库 |
| 不按 Star 盲选，使用项目语料 A/B | 已实现，真实业务样本待复核 | 固定仓库语料分块门禁与 `RAG Model Quality Gate #10` 的完整模型 A/B 均绿色 |
| `ParsedDocument -> DocumentElement -> KnowledgeChunk` 统一模型 | 已实现 | `backend/app/rag/types.py`、解析/分块单元与属性测试 |
| Markdown/DOCX/PDF 结构、表格、代码、标题和页码 | 已实现 | `backend/app/rag/parsers.py`、`tests/test_rag_processing.py` |
| 高级版面/OCR、bbox 与阅读顺序 | 已实现，真实服务已验证 | Docling Serve 1.26.0 lossless JSON `1.26-json-v1`：本地及远程真实 DOCX 表格、扫描 PDF OCR、页码/bbox 测试通过 |
| 中文/英文 token 边界、父子/递归/语义/表格专用分块 | 已实现 | `backend/app/rag/chunking.py`、Chonkie 可选语义策略、token/property/table 测试 |
| 稳定 chunk ID、元素/页码/标题元数据与可追溯引用 | 已实现 | chunking、chunk API、引用过滤测试 |
| 批量 embedding、父向量、增量复用与模型变更重算 | 已实现 | `backend/app/rag/service.py`、`tests/test_knowledge_jobs.py` |
| 幂等任务、重试、失败清理、原子激活、版本回滚 | 已实现 | 版本化索引测试、Milvus 故障注入测试、Alembic `0016 -> 0015 -> 0016` 本地往返 |
| BM25 + child dense + parent dense、RRF、查询改写、过滤 | 已实现，真实服务已验证 | `service.py`、`vector_store.py`、Milvus 协议测试；`CI #7/#8` 的 PostgreSQL + Milvus v4 job 绿色 |
| Cross-Encoder rerank、父块扩展、去重、token 限界 | 已实现，固定真实模型已验证 | 固定 mMARCO Cross-Encoder、两阶段相关性门槛及 fallback 测试；`RAG Model Quality Gate #10` 绿色 |
| 引用校验、忠实回答与拒答 | 已实现，固定真实模型已验证 | 确定性引用、限定词保真与严格 judge JSON 测试；Run #10 的忠实度、引用、答案断言和拒答均为 `1.0` |
| 项目/owner 隔离及过滤下推 | 已实现，真实服务已验证 | SQL 权限过滤、Milvus `owner_id`/`document_id` ANN 表达式测试；真实隔离 job 已绿色 |
| 提示注入、文件签名、解压/页数/元素/chunk 资源限制 | 已实现 | parser/chunker 安全测试与运行时配置校验 |
| 指标、成本、延迟与运维告警 | 已实现，固定真实模型已验证 | Prometheus、`llm_usage`、运维手册；Run #10 业务 p95 `76.10 s`、judge p95 `272.54 s`、本地模型 API 成本 `0` |
| 后台策略、索引版本、重建、激活与回滚 | 已实现 | API、runtime setting、Knowledge UI 与 E2E 测试 |
| native/Docling/Unstructured/MinerU 同样本比较 | 已实现，Linux 全矩阵已验证 | `RAG Parser Benchmark #2` 在同一 corpus hash 上完成四后端报告，严格 comparison gate 绿色并留存 artifact |
| 脱敏业务语料自定义评测入口 | 已实现，待业务语料运行 | 分块和端到端脚本支持 `--cases`/`--documents-dir`；递归纳入干扰文档，校验 case 与路径，记录原始及解析后 corpus SHA-256、解析器版本并禁止跨语料 A/B；操作见 `docs/RAG_BUSINESS_CORPUS.md` |
| 真实业务复杂 PDF/DOCX/中文表格/公式/代码验证 | 缺失 | 需要业务方提供脱敏样本；仓库合成样本不能替代 |
| 新方案显著优于 `900/140` | 已证明（固定仓库语料） | Run #10：Recall `0.8333 -> 1.0`、MRR `0.75 -> 1.0`、nDCG `0.7718 -> 1.0`、Context Precision `0.3667 -> 0.6583`，全部防回归门禁绿色 |

## 当前验收证据

- 后端全量测试在当前 RAG 代码上的最近完整结果：`204 passed, 7 skipped`；skip 仅对应需要独立真实服务的可选集成路径。
- 前端当前验证：ESLint 通过、`10 passed` unit tests、TypeScript/Vite production build 通过。
- 固定语料门禁通过：标题元数据 `0 -> 1.0`，最大 chunk `676 -> 391 tokens`，索引 token `7201 -> 6990`，Context Precision `0.1972 -> 0.2250`。
- 自定义语料入口本地回归通过：`10 passed`；RAG 解析、分块、检索、向量库、reranker 和索引任务专项回归为 `69 passed, 2 skipped`。默认固定语料的新 corpus SHA-256 为 `6c19a309...80930`，分块门禁绿色。
- native parser 基准：成功率 `0.6667`、marker recall `0.6667`、结构 recall `0.3333`、阅读顺序 `0.6667`、PDF 页码覆盖 `0.5`、bbox 覆盖 `0`。
- Docling Serve 1.26.0 真实集成测试：DOCX 表格与扫描 PDF OCR 通过；同样本质量分 `1.0`、p95 `12.79 s`、峰值内存 `2,112.6 MB`、本地环境加模型 `2,592.67 MB`。
- MinerU 3.4.4 pipeline 同样本质量分 `1.0`、p95 `60.41 s`、峰值内存 `1,811.98 MB`、本地环境加模型 `2,678.15 MB`；实测发现并补齐其未声明的 `six` 依赖。
- Unstructured 0.24.1 的 DOCX 单项通过；本机 Xeon E5-2680 v2 无 AVX2，ONNX Windows wheel 在 PDF 路径原生加载失败，不能据此给出候选质量结论。
- 远程 `CI #6` 的 compose/frontend 已通过；backend 与 rag-integration 都在加载 `tests/conftest.py` 时因 `ModuleNotFoundError: No module named 'app'` 以 pytest 退出码 `4` 失败，尚未执行测试逻辑。workflow 已统一改用 `python -m pytest`，修复结果仍须以新的远程运行证明。
- 远程 [`CI #7`](https://github.com/CodeWithLi/agent-workspace-ai/actions/runs/29629583160) 与 [`CI #8`](https://github.com/CodeWithLi/agent-workspace-ai/actions/runs/29629841019) 整套绿色；真实 PostgreSQL + Milvus v4 的多向量、owner 隔离、并发和 p95 集成 job 已执行通过。
- 远程 [`RAG Docling Integration #2`](https://github.com/CodeWithLi/agent-workspace-ai/actions/runs/29629854246) 绿色；官方 v1.26.0 CPU 镜像固定到不可变 digest，真实 DOCX 表格和扫描 PDF OCR 测试通过。
- 远程 [`RAG Parser Benchmark #2`](https://github.com/CodeWithLi/agent-workspace-ai/actions/runs/29629969071) 全矩阵及严格 comparison gate 绿色，artifact 保留 30 天。共同 corpus hash 为 `70e00e55...3dea1c`；质量排序为 MinerU `1.0000`、Docling `0.9167`、Unstructured `0.9167`、native `0.4792`。
- 远程 [`RAG Model Quality Gate #10`](https://github.com/CodeWithLi/agent-workspace-ai/actions/runs/29644078245) 在提交 `c945780` 上绿色；artifact ID `8429990285`，SHA-256 `574cbff039e1a83d6f90d23c440e4d3f492fb47b08b26f7d858422e75eb657f9`。Candidate Recall/MRR/nDCG/Context Recall/引用目标/忠实度/答案相关性/引用正确率/答案断言/拒答均为 `1.0`，Context Precision `0.6583`，业务 p95 `76.10 s`，A/B 全部通过。
- 所有 workflow 通过 `actionlint 1.7.12`，Python compile 与 `git diff --check` 通过。

## 阻止 Goal 完成的证据缺口

1. 自定义业务语料接入、生产解析器调用、解析指纹和 A/B 同语料校验已经完成；仍必须由业务方提供脱敏复杂文档，并按 `docs/RAG_BUSINESS_CORPUS.md` 复跑解析、检索、引用和拒答门禁。固定仓库语料和自动生成边界样本不能证明真实业务分布。

上述真实业务样本验收完成前，Goal 必须保持 active。
