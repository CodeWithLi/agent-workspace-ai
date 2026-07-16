import logging

from app.core.config import get_settings


logger = logging.getLogger(__name__)
settings = get_settings()


class MilvusVectorStore:
    def __init__(self) -> None:
        self.connected = False

    def connect(self) -> bool:
        if self.connected:
            return True
        try:
            from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility

            connections.connect(alias="default", host=settings.milvus_host, port=settings.milvus_port)
            if not utility.has_collection(settings.milvus_collection):
                fields = [
                    FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=100),
                    FieldSchema(name="document_id", dtype=DataType.INT64),
                    FieldSchema(name="project_id", dtype=DataType.INT64),
                    FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=4096),
                    FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=settings.embedding_dimensions),
                ]
                schema = CollectionSchema(fields=fields, description="Agent Workspace knowledge chunks")
                collection = Collection(settings.milvus_collection, schema)
                collection.create_index(
                    field_name="embedding",
                    index_params={"metric_type": "COSINE", "index_type": "AUTOINDEX", "params": {}},
                )
            Collection(settings.milvus_collection).load()
            self.connected = True
            return True
        except Exception as exc:
            logger.info("Milvus unavailable, using local retrieval fallback: %s", exc)
            return False

    def upsert(self, vector_id: str, document_id: int, project_id: int | None, content: str, embedding: list[float]) -> None:
        if not self.connect():
            return
        try:
            from pymilvus import Collection

            collection = Collection(settings.milvus_collection)
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
            logger.info("Milvus upsert skipped: %s", exc)

    def search(self, embedding: list[float], project_id: int | None, limit: int) -> list[dict]:
        if not self.connect():
            return []
        try:
            from pymilvus import Collection

            expression = f"project_id == {project_id}" if project_id is not None else ""
            rows = Collection(settings.milvus_collection).search(
                data=[embedding],
                anns_field="embedding",
                param={"metric_type": "COSINE", "params": {}},
                limit=limit,
                expr=expression,
                output_fields=["document_id", "project_id", "content"],
            )[0]
            return [
                {
                    "vector_id": str(hit.id),
                    "document_id": int(hit.entity.get("document_id")),
                    "content": hit.entity.get("content"),
                    "score": max(0.0, float(hit.score)),
                }
                for hit in rows
            ]
        except Exception as exc:
            logger.info("Milvus search skipped: %s", exc)
            return []

    def delete_document(self, document_id: int) -> None:
        if not self.connect():
            return
        try:
            from pymilvus import Collection

            Collection(settings.milvus_collection).delete(f"document_id == {document_id}")
        except Exception as exc:
            logger.warning("Milvus delete skipped for document %s: %s", document_id, exc)


vector_store = MilvusVectorStore()
