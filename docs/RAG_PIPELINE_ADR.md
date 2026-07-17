# RAG 文档处理与分块选型 ADR

状态：进行中  
日期：2026-07-17

## 背景

当前实现使用 900 字符窗口和 140 字符重叠，仅在窗口后半段识别换行或中文句号。PDF 页码、DOCX 标题、Markdown 标题、表格、代码块和来源位置在切割前被抹平，切割长度也与 Embedding 模型的 token 限制无关。

## GitHub 候选快照

以下数据于 2026-07-17 从 GitHub 仓库页面核验。Star 反映社区规模，不直接代表本项目文档集上的效果。

| 项目 | Star | 许可证 | 最近发布 | 提交数 | 初步结论 |
|---|---:|---|---|---:|---|
| LangChain | 142k | MIT | langchain-core 1.4.9，2026-07-08 | 16,428 | 已在项目依赖中，适合作为确定性文本分割基础 |
| RAGFlow | 85.3k | Apache-2.0 | v0.26.4，2026-07-07 | 7,449 | 适合作为能力和评测参考，不整体替换现有平台 |
| MinerU | 74.9k | Apache-2.0 加附加条款 | 3.4.4，2026-07-10 | 5,712 | 纳入复杂中文 PDF 基准，但上线前必须完成许可审查 |
| Docling | 63.3k | 代码 MIT，模型另行授权 | v2.113.0，2026-07-14 | 1,231 | 首选高级解析候选，使用独立 worker 隔离资源 |
| LlamaIndex | 50.9k | MIT | v0.14.23，2026-06-24 | 7,857 | 采用父子块和句子窗口思路，不引入完整框架 |
| Unstructured | 15.2k | Apache-2.0 | 0.24.1，2026-07-11 | 1,909 | Docling 的解析对照组及格式降级候选 |
| Chonkie | 4.5k | MIT | v1.7.0，2026-07-07 | 2,201 | 保留为离线分块对照，不进入当前生产依赖 |

### 能力与集成成本

| 项目 | 中英文 | PDF / OCR | DOCX / Markdown | 表格 / 代码 | 结构元数据 | 本项目集成成本 |
|---|---|---|---|---|---|---|
| LangChain text splitters | 可配置中英文分隔符 | 不负责解析/OCR | 有 Markdown/HTML/代码 splitter | 依赖输入结构 | 基础 metadata | 低，现有依赖已包含 |
| LlamaIndex node parsers | 依赖 tokenizer/模型 | 依赖 reader | 支持多种 node parser | 有 Markdown Element 等扩展 | 父子、层级、窗口关系丰富 | 中高，引入完整框架与现有编排重叠 |
| RAGFlow DeepDoc | 中文场景成熟 | 版面、表格、OCR | 多办公格式 | 强 | 完整文档知识图谱式元数据 | 极高，属于完整平台替换 |
| Docling | 多语言 | PDF 版面、OCR、模型管线 | 支持 DOCX、Markdown 等 | 强 | DoclingDocument、页码、bbox、标题层级 | 高，标准依赖包含 Torch/模型，宜独立部署 |
| Unstructured | 多语言 | partition_pdf 与 OCR 策略 | 多格式 partition | Element 类型保留 | Element metadata、页码、坐标 | 中高，PDF/OCR extras 较重 |
| MinerU | 中文 PDF 强 | 版面、公式、表格、OCR | 重点是 PDF | 强 | 页码、bbox、阅读顺序 | 高，模型/硬件/自定义许可均需治理 |
| Chonkie | 分隔符可配置 | 不负责解析 | 对纯文本分块 | Code/Table chunker 可选 | 不恢复源文档结构 | 低，但本轮实测未胜出 |

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

数据集使用仓库内 6 份真实设计和运维文档、6 个固定查询及逐字证据。当前结果：

| 策略 | chunks | Recall@5 | MRR | nDCG@5 | 标题元数据覆盖 | 最大 Token | 首次分块耗时 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 旧 900/140 字符窗口 | 15 | 0.8333 | 0.7500 | 0.7718 | 0% | 607 | 7.04 ms |
| 结构化父子分块 v1 | 27 | 0.8333 | 0.7500 | 0.7718 | 100% | 381 | 134.53 ms |
| Chonkie Sentence 1.7.0 | 17 | 0.8333 | 0.7500 | 0.7311 | 0% | 397 | 1893.89 ms |

本轮只能证明结构元数据和 Token 上限改善，不能证明召回提升。Chonkie 在该数据集未胜出，因此只保留在 `requirements-rag-eval.txt` 和离线评测适配器中，不进入生产依赖。

Docling 2.113.0 的 `standard` 依赖包含 Torch、TorchVision、Docling IBM Models、RapidOCR 等组件。隔离 Python 3.13 环境安装 `docling-slim[convert-core,feat-chunking,format-docx,format-markdown,format-pdf]` 用时约 134 秒；`HybridChunker` 可以导入，但 `DocumentConverter` 仍在模块加载阶段硬依赖 Torch。官方 Docling Serve 1.26 CPU 镜像约 4.4 GB。因此高级 Docling/MinerU 解析必须隔离为独立 worker 或服务，不能直接增加 API 容器的冷启动、镜像和内存负担。

## 尚未完成的验证

- 使用项目真实 PDF、DOCX、Markdown、中文表格、扫描件和代码文档建立脱敏评测集。
- 比较 Docling、MinerU、Unstructured 的解析成功率、结构准确率、耗时、峰值内存、镜像体积和许可证约束。
- 比较递归、结构、语义和父子分块的 Recall@K、nDCG、Context Precision/Recall 与引用正确率。
- 验证新 Milvus schema、双版本索引、原子激活、回滚和跨项目隔离。

在上述验证完成前，本 ADR 不把任何单一外部库描述为“最佳”。
