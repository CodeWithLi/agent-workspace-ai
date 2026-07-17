# RAG 知识库

## 入库

上传请求只执行文件校验、SHA-256 去重、元数据落库和 MinIO 保存，随后返回 `202 QUEUED`。后台 dispatcher 通过 PostgreSQL 租约认领任务，执行解析 -> 边界感知切片 -> 批量 Embedding -> PostgreSQL 持久化降级向量 -> Milvus ANN 索引。失败任务自动重试，终态失败可人工重试；已完成文档可重建索引。

默认解析器会保留 Markdown 标题/表格/代码块、DOCX 标题样式/表格和 PDF 页码。高级版面、表格和 OCR 可启用独立 Docling Serve CPU worker：

```bash
docker compose --profile advanced-rag up -d docling
```

随后将 `RAG_PARSER_BACKEND` 设为 `auto` 或 `docling`。`auto` 仅在配置 Docling URL 时调用高级解析；失败后是否使用原生解析由 `RAG_PARSER_FALLBACK_ENABLED` 控制。Docling CPU 镜像约 4.4 GB，不能与 API 进程合并部署。

项目文档按项目共享，个人文档按 owner 隔离。相同作用域与相同内容哈希只保存一次；同名但内容不同的文件递增版本号。标签、来源、错误、尝试次数和索引完成时间保存在文档记录中。

## 检索

1. 对可访问项目内的文本块计算 BM25 风格稀疏分数。
2. 查询向量优先走 Milvus cosine ANN；启用 `RAG_MULTI_VECTOR_ENABLED` 时同时召回 child 与 parent 向量，Milvus 不可用时读取 PostgreSQL 的持久化向量。
3. 对 sparse、child dense 和可选 parent dense 排名进行 RRF 融合，再按词项覆盖率 rerank。
4. 应用 `min_score` 阈值与 `top_k`，无匹配时不让 LLM 编造答案。
5. LLM 只能基于选中上下文回答，并输出 `文件名#chunk-N` 引用；引用可通过 chunk API 定位原始片段。

检索前可由 LLM 生成最多 3 个结构化同义/中英查询；输出不是合法 JSON 时退回原查询。候选经过 sparse/dense 融合、查询覆盖率门禁和可选 Cross-Encoder `/rerank`。同一父块只保留一个 child 结果，回答上下文扩展到父块并受总 Token 预算限制。文档内容被视为不可信数据，不能覆盖系统指令；模型生成的未知引用会被移除。

项目文档对项目成员共享；未关联项目的个人文档仅 owner 可检索。删除文档会同步删除 MinIO 对象、数据库块和 Milvus 向量。

开发环境可使用本地 feature hashing 与本地文件回退。生产必须配置：

```env
LLM_FALLBACK_ENABLED=false
STORAGE_FALLBACK_ENABLED=false
EMBEDDING_API_KEY=...
EMBEDDING_BASE_URL=...
EMBEDDING_MODEL=...
KNOWLEDGE_WORKER_ENABLED=true
KNOWLEDGE_LEASE_SECONDS=300
KNOWLEDGE_MAX_ATTEMPTS=3
RAG_MULTI_VECTOR_ENABLED=true
MILVUS_COLLECTION=knowledge_chunks_v4
```

## 评测门禁

1. `python scripts/evaluate_rag_chunking.py --enforce-gates` 使用固化的真实仓库文档快照，对比旧 `900/140` 与结构化分块，阻止 Recall/MRR/nDCG/引用退化、Context Precision 提升不足、token 膨胀和本地 p95 越线。
2. 普通 CI 的 `rag-integration` 作业启动真实 PostgreSQL、MinIO、etcd 和 Milvus，执行 v4 BM25+child dense+parent dense hybrid、4 并发 p95 门禁，并验证两个个人知识库 owner 之间没有泄漏。
3. `RAG External Quality Gate` 手动工作流先运行旧 `900/140` 基线，再以相同语料和外部服务运行真实多语 child/parent embedding、语义分块、查询改写、Cross-Encoder reranker、回答模型和 judge 模型。候选方案的 Recall/MRR/nDCG/Context Precision 不得显著退化，且至少一个主检索指标需提升 `0.05`；同时衡量答案忠实度、答案相关性、引用正确率、拒答、端到端 p95 与估算成本。父内容去重后单独计入 embedding token 与成本。该脚本要求 `LLM_FALLBACK_ENABLED=false`，缺少外部配置时以退出码 `2` 拒绝评测。
4. `RAG Docling Integration` 每周使用真实 Docling Serve CPU 镜像验证 DOCX 标题/表格和图片型 PDF OCR。模型、镜像或 OCR 失败会阻断该工作流，不允许原生 parser fallback 掩盖问题。

外部答案门禁命令：

```bash
python scripts/evaluate_rag_end_to_end.py \
  --require-reranker \
  --enforce-gates \
  --output .run/rag-end-to-end.json
```
