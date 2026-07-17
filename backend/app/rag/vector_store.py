import logging

from app.core.config import get_settings


logger = logging.getLogger(__name__)
settings = get_settings()


class VectorStoreError(RuntimeError):
    pass


class MilvusVectorStore:
    def __init__(self) -> None:
        self.connected = False
        self.supports_hybrid = False

    def connect(self) -> bool:
        if self.connected:
            return True
        try:
            from pymilvus import (
                Collection,
                CollectionSchema,
                DataType,
                FieldSchema,
                Function,
                FunctionType,
                connections,
                utility,
            )

            connections.connect(alias="default", host=settings.milvus_host, port=settings.milvus_port)
            if not utility.has_collection(settings.milvus_collection):
                fields = [
                    FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=100),
                    FieldSchema(name="document_id", dtype=DataType.INT64),
                    FieldSchema(name="project_id", dtype=DataType.INT64),
                    FieldSchema(name="index_version", dtype=DataType.INT64),
                    FieldSchema(
                        name="content",
                        dtype=DataType.VARCHAR,
                        max_length=8192,
                        enable_analyzer=True,
                        enable_match=True,
                        analyzer_params={"type": "standard"},
                    ),
                    FieldSchema(name="sparse", dtype=DataType.SPARSE_FLOAT_VECTOR),
                    FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=settings.embedding_dimensions),
                ]
                schema = CollectionSchema(fields=fields, description="Agent Workspace knowledge chunks")
                schema.add_function(
                    Function(
                        name="content_bm25",
                        function_type=FunctionType.BM25,
                        input_field_names=["content"],
                        output_field_names=["sparse"],
                    )
                )
                collection = Collection(settings.milvus_collection, schema)
                collection.create_index(
                    field_name="embedding",
                    index_params={"metric_type": "COSINE", "index_type": "AUTOINDEX", "params": {}},
                )
                collection.create_index(
                    field_name="sparse",
                    index_params={
                        "metric_type": "BM25",
                        "index_type": "SPARSE_INVERTED_INDEX",
                        "params": {"inverted_index_algo": "DAAT_MAXSCORE"},
                    },
                )
            collection = Collection(settings.milvus_collection)
            field_names = {field.name for field in collection.schema.fields}
            self.supports_hybrid = {"sparse", "content", "index_version"}.issubset(field_names)
            collection.load()
            self.connected = True
            return True
        except Exception as exc:
            self.connected = False
            self.supports_hybrid = False
            if not settings.vector_fallback_enabled:
                raise VectorStoreError("Milvus connection failed") from exc
            logger.info("Milvus unavailable, using PostgreSQL retrieval fallback: %s", exc)
            return False

    def upsert(
        self,
        vector_id: str,
        document_id: int,
        project_id: int | None,
        content: str,
        embedding: list[float],
        index_version: int = 0,
    ) -> None:
        if not self.connect():
            return
        try:
            from pymilvus import Collection

            collection = Collection(settings.milvus_collection)
            if self.supports_hybrid:
                collection.upsert(
                    [
                        {
                            "id": vector_id,
                            "document_id": document_id,
                            "project_id": project_id or 0,
                            "index_version": index_version,
                            "content": content[:8192],
                            "embedding": embedding,
                        }
                    ]
                )
            else:
                collection.upsert(
                    [
                        [vector_id],
                        [document_id],
                        [project_id or 0],
                        [content[:4096]],
                        [embedding],
                    ]
                )
            collection.flush()
        except Exception as exc:
            if not settings.vector_fallback_enabled:
                raise VectorStoreError("Milvus upsert failed") from exc
            logger.info("Milvus upsert skipped: %s", exc)

    def search(self, embedding: list[float], project_id: int | None, limit: int) -> list[dict]:
        if not self.connect():
            return []
        try:
            from pymilvus import Collection

            expression = f"project_id == {project_id}" if project_id is not None else "project_id == 0"
            output_fields = ["document_id", "project_id", "content"]
            if self.supports_hybrid:
                output_fields.append("index_version")
            rows = Collection(settings.milvus_collection).search(
                data=[embedding],
                anns_field="embedding",
                param={"metric_type": "COSINE", "params": {}},
                limit=limit,
                expr=expression,
                output_fields=output_fields,
            )[0]
            return [
                {
                    "vector_id": str(hit.id),
                    "document_id": int(hit.entity.get("document_id")),
                    "index_version": int(hit.entity.get("index_version")) if self.supports_hybrid else 0,
                    "content": hit.entity.get("content"),
                    "score": max(0.0, float(hit.score)),
                }
                for hit in rows
            ]
        except Exception as exc:
            if not settings.vector_fallback_enabled:
                raise VectorStoreError("Milvus search failed") from exc
            logger.info("Milvus search skipped: %s", exc)
            return []

    def hybrid_search(
        self,
        query: str,
        embedding: list[float],
        project_id: int | None,
        limit: int,
    ) -> list[dict]:
        if not self.connect() or not self.supports_hybrid:
            return self.search(embedding, project_id, limit)
        try:
            from pymilvus import AnnSearchRequest, Collection, RRFRanker

            expression = f"project_id == {project_id}" if project_id is not None else "project_id == 0"
            dense_request = AnnSearchRequest(
                data=[embedding],
                anns_field="embedding",
                param={"metric_type": "COSINE", "params": {}},
                limit=limit,
                expr=expression,
            )
            sparse_request = AnnSearchRequest(
                data=[query],
                anns_field="sparse",
                param={"metric_type": "BM25", "params": {}},
                limit=limit,
                expr=expression,
            )
            rows = Collection(settings.milvus_collection).hybrid_search(
                reqs=[sparse_request, dense_request],
                rerank=RRFRanker(60),
                limit=limit,
                output_fields=["document_id", "project_id", "index_version", "content"],
            )[0]
            return [
                {
                    "vector_id": str(hit.id),
                    "document_id": int(hit.entity.get("document_id")),
                    "index_version": int(hit.entity.get("index_version")),
                    "content": hit.entity.get("content"),
                    "score": max(0.0, float(hit.score)),
                }
                for hit in rows
            ]
        except Exception as exc:
            if not settings.vector_fallback_enabled:
                raise VectorStoreError("Milvus hybrid search failed") from exc
            logger.warning("Milvus hybrid search failed; using dense search: %s", exc)
            return self.search(embedding, project_id, limit)

    def delete_document(self, document_id: int) -> None:
        if not self.connect():
            return
        try:
            from pymilvus import Collection

            Collection(settings.milvus_collection).delete(f"document_id == {document_id}")
        except Exception as exc:
            if not settings.vector_fallback_enabled:
                raise VectorStoreError(f"Milvus delete failed for document {document_id}") from exc
            logger.warning("Milvus delete skipped for document %s: %s", document_id, exc)

    def delete_ids(self, vector_ids: list[str]) -> None:
        if not vector_ids or not self.connect():
            return
        try:
            from pymilvus import Collection

            escaped = ", ".join(f'"{vector_id}"' for vector_id in vector_ids)
            Collection(settings.milvus_collection).delete(f"id in [{escaped}]")
        except Exception as exc:
            if not settings.vector_fallback_enabled:
                raise VectorStoreError("Milvus vector cleanup failed") from exc
            logger.warning("Milvus vector cleanup skipped: %s", exc)


vector_store = MilvusVectorStore()
