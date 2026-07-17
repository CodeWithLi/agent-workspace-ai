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
        self.supports_multi_vector = False
        self.supports_owner_filter = False

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
                    FieldSchema(name="owner_id", dtype=DataType.INT64),
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
                    FieldSchema(name="parent_embedding", dtype=DataType.FLOAT_VECTOR, dim=settings.embedding_dimensions),
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
                collection.create_index(
                    field_name="parent_embedding",
                    index_params={"metric_type": "COSINE", "index_type": "AUTOINDEX", "params": {}},
                )
            collection = Collection(settings.milvus_collection)
            field_names = {field.name for field in collection.schema.fields}
            self.supports_hybrid = {"sparse", "content", "index_version"}.issubset(field_names)
            self.supports_multi_vector = "parent_embedding" in field_names
            self.supports_owner_filter = "owner_id" in field_names
            collection.load()
            self.connected = True
            return True
        except Exception as exc:
            self.connected = False
            self.supports_hybrid = False
            self.supports_multi_vector = False
            self.supports_owner_filter = False
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
        parent_embedding: list[float] | None = None,
        owner_id: int | None = None,
    ) -> None:
        if not self.connect():
            return
        try:
            from pymilvus import Collection

            collection = Collection(settings.milvus_collection)
            if self.supports_hybrid:
                item = {
                    "id": vector_id,
                    "document_id": document_id,
                    "project_id": project_id or 0,
                    "owner_id": owner_id or 0,
                    "index_version": index_version,
                    "content": content[:8192],
                    "embedding": embedding,
                }
                if self.supports_multi_vector:
                    item["parent_embedding"] = parent_embedding or embedding
                collection.upsert([item])
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

    def _scope_expression(
        self,
        project_id: int | None,
        owner_id: int | None,
        document_ids: list[int] | None = None,
    ) -> str | None:
        if project_id is not None:
            expression = f"project_id == {project_id}"
        elif owner_id is not None and self.supports_owner_filter:
            expression = f"project_id == 0 and owner_id == {owner_id}"
        elif owner_id is not None:
            if not settings.vector_fallback_enabled:
                raise VectorStoreError("Milvus collection does not support personal owner isolation")
            logger.warning("Milvus owner filter unavailable; using PostgreSQL retrieval fallback")
            return None
        else:
            expression = "project_id == 0"
        if document_ids:
            ids = ", ".join(str(document_id) for document_id in sorted(set(document_ids)))
            expression += f" and document_id in [{ids}]"
        return expression

    def search(
        self,
        embedding: list[float],
        project_id: int | None,
        limit: int,
        owner_id: int | None = None,
        document_ids: list[int] | None = None,
    ) -> list[dict]:
        if not self.connect():
            return []
        try:
            from pymilvus import Collection

            expression = self._scope_expression(project_id, owner_id, document_ids)
            if expression is None:
                return []
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
        owner_id: int | None = None,
        document_ids: list[int] | None = None,
    ) -> list[dict]:
        if not self.connect() or not self.supports_hybrid:
            return self.search(
                embedding,
                project_id,
                limit,
                owner_id=owner_id,
                document_ids=document_ids,
            )
        try:
            from pymilvus import AnnSearchRequest, Collection, RRFRanker

            expression = self._scope_expression(project_id, owner_id, document_ids)
            if expression is None:
                return []
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
            requests = [sparse_request, dense_request]
            if settings.rag_multi_vector_enabled and self.supports_multi_vector:
                requests.append(
                    AnnSearchRequest(
                        data=[embedding],
                        anns_field="parent_embedding",
                        param={"metric_type": "COSINE", "params": {}},
                        limit=limit,
                        expr=expression,
                    )
                )
            rows = Collection(settings.milvus_collection).hybrid_search(
                reqs=requests,
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
            return self.search(
                embedding,
                project_id,
                limit,
                owner_id=owner_id,
                document_ids=document_ids,
            )

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
