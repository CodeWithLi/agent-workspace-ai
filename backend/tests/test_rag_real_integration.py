import json
import math
import os
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter
from uuid import uuid4

import pytest
from sqlalchemy import inspect, select

from app.core.database import SessionLocal, engine
from app.core.llm import get_llm
from app.models import Embedding, KnowledgeDocument, KnowledgeIndexVersion, User
from app.rag.service import search_knowledge
from app.rag.vector_store import MilvusVectorStore, settings as vector_settings


pytestmark = pytest.mark.skipif(
    os.getenv("RAG_REAL_INTEGRATION") != "1",
    reason="requires real PostgreSQL and Milvus services",
)


@pytest.mark.asyncio
async def test_real_postgres_milvus_hybrid_search_preserves_personal_isolation() -> None:
    assert engine.dialect.name == "postgresql"
    assert {"documents", "document_index_versions", "embeddings"}.issubset(inspect(engine).get_table_names())
    assert vector_settings.vector_fallback_enabled is False
    assert vector_settings.rag_multi_vector_enabled is True

    suffix = uuid4().hex[:12]
    store = MilvusVectorStore()
    users: list[User] = []
    documents: list[KnowledgeDocument] = []
    contents = [
        "alpha private backup procedure uses PostgreSQL point-in-time recovery",
        "alpha private payroll procedure requires finance approval",
    ]
    vectors = await get_llm().embed_many(contents)

    try:
        with SessionLocal() as db:
            for index, content in enumerate(contents, start=1):
                user = User(
                    email=f"rag-integration-{suffix}-{index}@example.com",
                    name=f"RAG integration user {index}",
                    password_hash="not-used",
                    permissions="knowledge:write",
                )
                db.add(user)
                db.flush()
                document = KnowledgeDocument(
                    owner_id=user.id,
                    filename=f"private-{suffix}-{index}.md",
                    content_type="text/markdown",
                    storage_path=f"integration/{suffix}/{index}.md",
                    status="INDEXED",
                    content_hash=(str(index) * 64)[:64],
                    dedup_key=f"rag-integration-{suffix}-{index}",
                    active_index_version=1,
                    parser_name="markdown-it-py",
                    parser_version="3.0.0",
                    chunker_name="structural-parent-child",
                    chunker_version="1",
                    element_count=1,
                    chunk_count=1,
                )
                db.add(document)
                db.flush()
                db.add(
                    KnowledgeIndexVersion(
                        document_id=document.id,
                        version=1,
                        status="ACTIVE",
                        parser_name="markdown-it-py",
                        parser_version="3.0.0",
                        chunker_name="structural-parent-child",
                        chunker_version="1",
                        embedding_model="local-feature-hashing",
                        embedding_dimensions=vector_settings.embedding_dimensions,
                        element_count=1,
                        chunk_count=1,
                    )
                )
                vector_id = f"integration-{suffix}-{index}"
                db.add(
                    Embedding(
                        document_id=document.id,
                        content=content,
                        chunk_index=0,
                        vector_id=vector_id,
                        vector_json=json.dumps(vectors[index - 1]),
                        parent_vector_json=json.dumps(vectors[index - 1]),
                        stable_id=(f"{index}" * 64)[:64],
                        index_version=1,
                        parent_stable_id=f"parent-{suffix}-{index}",
                        parent_content=content,
                        token_count=12,
                        heading_path_json='["Private", "Procedure"]',
                        metadata_json="{}",
                        content_hash=(f"{index + 2}" * 64)[:64],
                    )
                )
                users.append(user)
                documents.append(document)
            db.commit()

            for index, (document, content, vector) in enumerate(zip(documents, contents, vectors), start=1):
                store.upsert(
                    f"integration-{suffix}-{index}",
                    document.id,
                    None,
                    content,
                    vector,
                    index_version=1,
                    parent_embedding=vector,
                    owner_id=document.owner_id,
                )

            assert store.connect() is True
            assert store.supports_hybrid is True
            assert store.supports_multi_vector is True
            hybrid = store.hybrid_search(contents[0], vectors[0], None, 10, owner_id=users[0].id)
            assert documents[0].id in {row["document_id"] for row in hybrid}
            assert {row["document_id"] for row in hybrid}.issubset({document.id for document in documents})
            assert all(row["index_version"] == 1 for row in hybrid)

            def timed_hybrid_search() -> tuple[float, list[dict]]:
                search_started = perf_counter()
                found = store.hybrid_search(contents[0], vectors[0], None, 10, owner_id=users[0].id)
                return (perf_counter() - search_started) * 1000, found

            with ThreadPoolExecutor(max_workers=4) as executor:
                measurements = list(executor.map(lambda _index: timed_hybrid_search(), range(24)))
            latencies = sorted(latency for latency, _rows in measurements)
            p95 = latencies[max(0, math.ceil(len(latencies) * 0.95) - 1)]
            assert all(rows for _latency, rows in measurements)
            assert p95 <= float(os.getenv("RAG_INTEGRATION_MAX_P95_MS", "3000"))

            first_answer, first_results = await search_knowledge(
                db,
                users[0],
                "alpha private backup PostgreSQL recovery",
                min_score=0.01,
            )
            second_answer, second_results = await search_knowledge(
                db,
                users[1],
                "alpha private payroll finance approval",
                min_score=0.01,
            )

            assert {row["document_id"] for row in first_results} == {documents[0].id}
            assert {row["document_id"] for row in second_results} == {documents[1].id}
            assert f"[{documents[0].filename}#chunk-0]" in first_answer
            assert f"[{documents[1].filename}#chunk-0]" in second_answer
            assert db.scalar(select(Embedding).where(Embedding.document_id == documents[0].id)) is not None
    finally:
        try:
            from pymilvus import connections, utility

            connections.connect(alias="default", host=vector_settings.milvus_host, port=vector_settings.milvus_port)
            if utility.has_collection(vector_settings.milvus_collection):
                utility.drop_collection(vector_settings.milvus_collection)
        finally:
            with SessionLocal() as db:
                for user in db.scalars(
                    select(User).where(User.email.like(f"rag-integration-{suffix}-%"))
                ):
                    db.delete(user)
                db.commit()
