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
2. 查询向量优先走 Milvus cosine ANN；Milvus 不可用时读取 PostgreSQL 的持久化向量。
3. 对 sparse 和 dense 排名进行加权融合，再按词项覆盖率 rerank。
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
```
