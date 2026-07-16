# RAG 知识库

## 入库

文件校验（PDF、DOCX、Markdown、TXT，默认不超过 25 MB） -> 解析 -> 边界感知切片 -> 批量 Embedding -> PostgreSQL 持久化降级向量 -> Milvus ANN 索引 -> MinIO 对象存储。

## 检索

1. 对可访问项目内的文本块计算 BM25 风格稀疏分数。
2. 查询向量优先走 Milvus cosine ANN；Milvus 不可用时读取 PostgreSQL 的持久化向量。
3. 对 sparse 和 dense 排名进行加权融合，再按词项覆盖率 rerank。
4. 应用 `min_score` 阈值与 `top_k`，无匹配时不让 LLM 编造答案。
5. LLM 只能基于选中上下文回答，并输出 `文件名#chunk-N` 引用。

项目文档对项目成员共享；未关联项目的个人文档仅 owner 可检索。删除文档会同步删除 MinIO 对象、数据库块和 Milvus 向量。

开发环境可使用本地 feature hashing 与本地文件回退。生产必须配置：

```env
LLM_FALLBACK_ENABLED=false
STORAGE_FALLBACK_ENABLED=false
EMBEDDING_API_KEY=...
EMBEDDING_BASE_URL=...
EMBEDDING_MODEL=...
```
