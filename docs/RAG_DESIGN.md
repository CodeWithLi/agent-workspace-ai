# RAG 知识库设计

## 流程

1. 上传文件
2. Document Loader 解析 PDF、Word、Markdown
3. Text Splitter 切割文本
4. Embedding
5. Milvus 存储
6. Retriever 检索
7. LLM 生成回答

## 当前实现

MVP 版本完成上传、解析、切割、数据库持久化和检索增强回答。Docker Compose 已包含 Milvus 与 MinIO 服务。为保证无云密钥环境可运行，当前检索提供本地词法检索降级，后续可将 `KnowledgeChunk.vector_id` 接入真实 Milvus 向量 ID。

## 支持格式

- PDF
- Word
- Markdown
- 纯文本
