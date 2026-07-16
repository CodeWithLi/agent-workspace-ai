# RAG 设计

本文件是兼容入口，权威设计见 [RAG.md](RAG.md)。

生产检索同时执行 BM25 风格稀疏召回、embedding 稠密召回和 Milvus ANN，使用排名融合与轻量 rerank，经过相似度阈值后将 TopK 文本和文档引用交给统一 LLM Gateway。Milvus 或外部 embedding 不可用时可显式使用 PostgreSQL 向量与本地 embedding 降级，但不会伪造引用。
