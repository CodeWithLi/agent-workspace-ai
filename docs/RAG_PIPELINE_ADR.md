# RAG 文档处理与分块选型 ADR

状态：进行中  
日期：2026-07-17

## 背景

当前实现使用 900 字符窗口和 140 字符重叠，仅在窗口后半段识别换行或中文句号。PDF 页码、DOCX 标题、Markdown 标题、表格、代码块和来源位置在切割前被抹平，切割长度也与 Embedding 模型的 token 限制无关。

## GitHub 候选快照

以下数据于 2026-07-17 从 GitHub 仓库页面核验。Star 反映社区规模，不直接代表本项目文档集上的效果。

| 项目 | Star | 许可证 | 最近发布 | 提交数 | 初步结论 |
|---|---:|---|---|---:|---|
| [LangChain](https://github.com/langchain-ai/langchain) | 142k | MIT | langchain-core 1.4.9，2026-07-08 | 16,428 | 已在项目依赖中，适合作为确定性文本分割基础 |
| [RAGFlow](https://github.com/infiniflow/ragflow) | 85.3k | Apache-2.0 | v0.26.4，2026-07-07 | 7,449 | 适合作为能力和评测参考，不整体替换现有平台 |
| [MinerU](https://github.com/opendatalab/MinerU) | 74.9k | Apache-2.0 加附加条款 | 3.4.4，2026-07-10 | 5,712 | 纳入复杂中文 PDF 基准，但上线前必须完成许可审查 |
| [Docling](https://github.com/docling-project/docling) | 63.3k | 代码 MIT，模型另行授权 | v2.113.0，2026-07-14 | 1,231 | 首选高级解析候选，使用独立 worker 隔离资源 |
| [LlamaIndex](https://github.com/run-llama/llama_index) | 50.9k | MIT | v0.14.23，2026-06-24 | 7,857 | 采用父子块和句子窗口思路，不引入完整框架 |
| [Unstructured](https://github.com/Unstructured-IO/unstructured) | 15.2k | Apache-2.0 | 0.24.1，2026-07-11 | 1,909 | Docling 的解析对照组及格式降级候选 |
| [Chonkie](https://github.com/chonkie-inc/chonkie) | 4.5k | MIT | v1.7.0，2026-07-07 | 2,201 | 作为可选语义边界策略依赖；结构、表格和代码仍由本项目模型保留 |

### 能力与集成成本

| 项目 | 中英文 | PDF / OCR | DOCX / Markdown | 表格 / 代码 | 结构元数据 | 本项目集成成本 |
|---|---|---|---|---|---|---|
| LangChain text splitters | 可配置中英文分隔符 | 不负责解析/OCR | 有 Markdown/HTML/代码 splitter | 依赖输入结构 | 基础 metadata | 低，现有依赖已包含 |
| LlamaIndex node parsers | 依赖 tokenizer/模型 | 依赖 reader | 支持多种 node parser | 有 Markdown Element 等扩展 | 父子、层级、窗口关系丰富 | 中高，引入完整框架与现有编排重叠 |
| RAGFlow DeepDoc | 中文场景成熟 | 版面、表格、OCR | 多办公格式 | 强 | 完整文档知识图谱式元数据 | 极高，属于完整平台替换 |
| Docling | 多语言 | PDF 版面、OCR、模型管线 | 支持 DOCX、Markdown 等 | 强 | DoclingDocument、页码、bbox、标题层级 | 高，标准依赖包含 Torch/模型，宜独立部署 |
| Unstructured | 多语言 | partition_pdf 与 OCR 策略 | 多格式 partition | Element 类型保留 | Element metadata、页码、坐标 | 中高，PDF/OCR extras 较重 |
| MinerU | 中文 PDF 强 | 版面、公式、表格、OCR | 重点是 PDF | 强 | 页码、bbox、阅读顺序 | 高，模型/硬件/自定义许可均需治理 |
| Chonkie | 分隔符可配置 | 不负责解析 | 对连续正文做语义分块 | Code/Table chunker 可选 | 由本项目适配层恢复标题和元素关系 | 中；需要真实 embedding，默认不启用 |

MinerU 附加条款要求：合并口径 MAU 超过 1 亿或月收入超过 2000 万美元时需另取商业许可；基于 MinerU 向第三方提供在线服务时必须显著标识。该约束必须进入部署审批，而不能只记录为“Apache-2.0”。

## 决策方向

1. 保留 FastAPI、PostgreSQL、Milvus 和现有异步索引任务，不引入第二套完整 RAG 平台。
2. 建立独立的 `ParsedDocument -> DocumentElement -> Parent/Child Chunk` 边界，业务代码不直接依赖具体解析器对象。
3. Markdown 使用 CommonMark token 流恢复标题、表格和代码块；DOCX 保留标题样式与表格；PDF 第一阶段保留页码，后续对 Docling、MinerU 和 Unstructured 做真实样本 A/B。
4. 分块长度改用模型 tokenizer 计量。使用 LangChain RecursiveCharacterTextSplitter 处理超大 Element，并在其外层实现结构分组、父子块、标题上下文和稳定 ID。
5. 解析器和 chunker 必须版本化。新索引未完成前继续服务旧索引，切换失败不得删除当前可用版本。
6. 高级语义分块、OCR 和 reranker 必须通过离线评测门禁后才能成为默认路径。

## 第一轮仓库文档 A/B

命令：

```bash
python scripts/evaluate_rag_chunking.py --include-chonkie
```

数据集使用仓库内 6 份真实设计和运维文档、8 个固定查询（6 个可回答、2 个拒答）及逐字证据。当前确定性稀疏回归结果采用 `400/100 tokens`：

| 策略 | chunks | Recall@5 | MRR | nDCG@5 | 标题元数据覆盖 | 最大 Token | 索引 Token |
|---|---:|---:|---:|---:|---:|---:|---:|
| 旧 900/140 字符窗口 | 20 | 0.6667 | 0.6667 | 0.6667 | 0% | 676 | 7,201 |
| 结构化父子分块 v2 | 33 | 0.6667 | 0.6667 | 0.6667 | 100% | 391 | 6,990 |

结构化方案的 Context Precision 从 `0.1972` 提升到 `0.2250`，拒答准确率保持 `1.0`，索引 token 减少约 `2.9%`。在 120-case 脱敏业务 release holdout 上，结构化父子分块相对旧 `900/140` 的 Recall `0.8000 -> 0.8333`、MRR `0.5843 -> 0.6622`、nDCG `0.6384 -> 0.7054`、Context Precision `0.2648 -> 0.3269`、引用目标 `0.4444 -> 0.5444`，标题元数据覆盖 `0.9952`，索引 token 仅增加 `808`。因此默认采用 `400/100` structural + parent multi-vector；Chonkie SemanticChunker 在本机对该语料的边界 embedding 耗时过高，仅保留为离线可选实验，不作为发布必经路径。

Docling 2.113.0 的 `standard` 依赖包含 Torch、TorchVision、Docling IBM Models、RapidOCR 等组件。隔离 Python 3.13 环境安装 `docling-slim[convert-core,feat-chunking,format-docx,format-markdown,format-pdf]` 用时约 134 秒；`HybridChunker` 可以导入，但 `DocumentConverter` 仍在模块加载阶段硬依赖 Torch。官方 Docling Serve 1.26 CPU 镜像约 4.4 GB。因此高级 Docling/MinerU 解析必须隔离为独立 worker 或服务，不能直接增加 API 容器的冷启动、镜像和内存负担。

## 同样本解析器基准

`RAG Parser Benchmark` 使用一个上传后共享给所有 job 的 corpus artifact，防止各后端重新生成 DOCX/PDF 时产生不同字节。样本覆盖 DOCX 标题/表格、两页文本 PDF 的标题/表格/阅读顺序，以及图片型 PDF OCR。统一报告解析成功率、marker recall、标题/表格结构 recall、阅读顺序、页码和 bbox 覆盖、p95、峰值内存与部署体积；每份报告必须携带同一个 SHA-256 corpus hash。

```bash
python scripts/benchmark_rag_parsers.py generate --output-dir .run/parser-corpus
python scripts/benchmark_rag_parsers.py run \
  --backend native \
  --corpus-dir .run/parser-corpus \
  --output .run/parser-native.json
```

当前本机 native 基线为：解析成功率 `0.6667`、marker recall `0.6667`、结构 recall `0.3333`、阅读顺序 `0.6667`、PDF 页码覆盖 `0.5`、bbox 覆盖 `0`。它正确暴露了原生解析没有扫描 PDF OCR、文本 PDF 不恢复表格/标题和 bbox 的限制。部署体积的 scope 会随报告明确记录：Docling 使用容器镜像，Unstructured 使用隔离 Python 环境，MinerU 使用隔离环境加模型缓存，不能把这些数字误写成完全相同的口径。

2026-07-18 在同一 `c3252b62...35c85` corpus hash 上完成了本地 CPU 实测。Docling 使用真实 Docling Serve 1.26.0，MinerU 使用 3.4.4 `pipeline`；两者都成功恢复 DOCX 标题/表格、两页 PDF 阅读顺序/表格/bbox 和扫描 PDF OCR。资源数字仅在各自行内口径比较，不能视为容器压缩体积的等价值。

| 后端 | 质量分 | 成功率 | p95 | 峰值内存 | 本地部署体积 | 结论 |
|---|---:|---:|---:|---:|---:|---|
| native | 0.4792 | 0.6667 | 203 ms | Windows 未采集 | 本地应用环境 | 快，但无 OCR、表格结构和 bbox |
| Docling 1.26 JSON | 1.0000 | 1.0000 | 12.79 s | 2,112.6 MB | 2,592.67 MB | 当前默认高级解析器候选 |
| MinerU 3.4.4 | 1.0000 | 1.0000 | 60.41 s | 1,811.98 MB | 2,678.15 MB | 复杂中文 PDF 的离线候选，仍需许可审批 |
| Unstructured 0.24.1 | 未完成 | DOCX 单项通过 | 未完成 | 未完成 | 约 2,116 MB，不含模型缓存 | 本机 Xeon v2 无 AVX2，ONNX Windows wheel 无法加载；必须以 Linux CI 结果判断 |

MinerU 3.4.4 的 pipeline wheel 使用了未声明的 `six` 依赖；基准专用 requirements 已显式固定 `six==1.17.0`，防止隔离 job 在模型加载前失败。本地真实 Docling 集成测试也已通过 DOCX 表格和扫描 PDF OCR。以上结果支持在当前合成边界语料上优先 Docling，但仍不能替代四后端 Linux artifact 或业务复杂文档验证。

同日，[`RAG Parser Benchmark #2`](https://github.com/CodeWithLi/agent-workspace-ai/actions/runs/29629969071) 在 Linux runner 上完成首次四后端绿色矩阵及严格 comparison gate。所有报告共享 `70e00e55...3dea1c` corpus hash；资源口径仍按各行的 artifact scope 解读。

| 后端 | 质量分 | 成功率 | 结构 recall | p95 | 峰值内存 | artifact 体积 |
|---|---:|---:|---:|---:|---:|---:|
| MinerU 3.4.4 | 1.0000 | 1.0000 | 1.0000 | 15.09 s | 3,468.1 MB | 6,468 MB |
| Docling 1.26 JSON | 0.9167 | 1.0000 | 0.6667 | 8.03 s | 1,792.0 MB | 4,734.57 MB |
| Unstructured 0.24.1 | 0.9167 | 1.0000 | 0.6667 | 25.17 s | 2,009.7 MB | 6,177 MB |
| native | 0.4792 | 0.6667 | 0.3333 | 124 ms | 51.1 MB | 646 MB |

Linux 证据表明 MinerU 在该合成边界语料上质量最高，Docling 是高级解析器中延迟最低且体积较小的选项，Unstructured 能在 Linux 正常运行但本轮没有质量或资源优势。因此保留 Docling 作为默认高级解析器候选，MinerU 作为质量优先的复杂中文 PDF 离线候选；在真实业务文档验证前不把该排序外推成普遍结论。

## 固定开源模型端到端门禁

[`RAG Model Quality Gate #10`](https://github.com/CodeWithLi/agent-workspace-ai/actions/runs/29644078245) 在提交 `c945780` 上使用固定 revision 和模型文件 SHA-256，完整执行 multilingual E5 embedding、Chonkie semantic chunking、查询改写、多向量混合召回、mMARCO Cross-Encoder rerank、Qwen2.5-1.5B 回答和 Phi-3.5 judge。Artifact ID 为 `8429990285`，下载包 SHA-256 为 `574cbff039e1a83d6f90d23c440e4d3f492fb47b08b26f7d858422e75eb657f9`。

Run #7 的完整候选诊断证明单一 rerank 阈值不可行：必须保留的 `knowledge-access` 证据最低分为 `0.1003`，不可回答 GPU 问题的库外候选最高分为 `0.1115`，区间重叠。最终选择器采用两阶段门槛：reranker 成功后所有候选先达到基础分；query coverage 低于专用下限时再达到更高 override 分。固定本地模型校准为基础分 `0.08`、coverage 下限 `0.08`、override `0.12`；外部 reranker 使用独立运行时配置。reranker 失败时保留原有 dense fallback，不把未打分尾部混入成功 rerank 结果。

| 指标 | 旧 900/140 baseline | 语义父子分块 candidate | 增益 |
|---|---:|---:|---:|
| Recall@5 | 0.8333 | 1.0000 | +0.1667 |
| MRR | 0.7500 | 1.0000 | +0.2500 |
| nDCG@5 | 0.7718 | 1.0000 | +0.2282 |
| Context Precision@5 | 0.3667 | 0.6583 | +0.2916 |
| Citation Target Accuracy | 0.6667 | 1.0000 | +0.3333 |
| Faithfulness | 0.8750 | 1.0000 | +0.1250 |
| Judge Citation Correctness | 0.8750 | 1.0000 | +0.1250 |
| Answer Assertion Accuracy | 0.6667 | 1.0000 | +0.3333 |
| Refusal Accuracy | 1.0000 | 1.0000 | 0.0000 |
| 业务 p95 | 108.28 s | 76.10 s | -32.17 s |
| Judge p95（单列，不计入业务延迟） | 490.04 s | 272.54 s | -217.50 s |

Candidate 的所有严格门禁和 A/B 比较均通过，主检索指标提升超过 `0.05`，API 模型成本为 `0`（GitHub CPU runner 上执行固定本地模型）。Judge 上下文总预算限制为 `2200 tokens`，保留每个 selected citation，完整 prompt 在确定性 tokenizer 下小于 `3000 tokens`，因此使用 4K judge context 而不再把 8K 模型分配和 judge 耗时混入业务 p95。答案后处理只允许从 rank-1 child chunk 补充遗漏的完整时间/频率证据句，并复用合法 citation；不得从 parent 或次级候选追加无关限定。

2026-07-19 在本机 Xeon E5-2680 v2（无 AVX2）开始真实业务语料 A/B 前，将固定开源模型的本地 CPU 业务 p95 SLO 冻结为 `300000ms`。baseline 与 candidate 使用相同模型 revision、运行时指纹和该阈值；质量绝对阈值、最小主指标增益 `0.05`、回退容忍 `0.01` 均不变。该主机口径不能替代托管模型工作流的 `5000ms` SLO，也不得在看到 candidate 结果后继续放宽。

## 验证状态

- 已自动从现有 PDD/抖店资料构建 33 份脱敏业务文档、90 个可回答 case 和 30 个拒答/安全 case，覆盖 Markdown/代码、DOCX、文本 PDF 和 OCR PDF；语料构建、脱敏与 hash 均可重复。
- Docling 1.26.0 在业务 parser 样本上的成功率、marker、结构、阅读顺序、页码和 bbox 均为 `1.0`；native 对 OCR PDF 失败，证明高级解析器选择有实际收益。
- 真实业务结构分块 A/B 与固定开源模型端到端 A/B 均已绿色；外部托管模型工作流仍可用于供应商验收，但不再阻塞本地回归证据。
- Milvus v4 child/parent 多向量、个人 owner 隔离、4 并发 p95 已在 `CI #7/#8` 真实服务 job 绿色；双版本索引、原子激活和回滚另有 SQLite/API/E2E 证据。
- Docling DOCX 表格与图片型 PDF OCR 已在本地及 [`RAG Docling Integration #2`](https://github.com/CodeWithLi/agent-workspace-ai/actions/runs/29629854246) 真实 1.26.0 服务通过。

在上述验证完成前，本 ADR 不把任何单一外部库描述为“最佳”。
