from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.routes.knowledge import get_document_chunk, list_documents, reindex_document, retry_document
from app.models import Embedding, KnowledgeDocument, KnowledgeIndexVersion, Project, ProjectMember, ProjectMemberRole, User
from app.rag.service import DuplicateDocumentError, queue_document, rollback_index_version
from app.schemas import KnowledgeDocumentActionRequest
from app.services.knowledge import process_document


def project_user(db: Session) -> tuple[User, Project]:
    user = User(
        email="knowledge-job@example.com",
        name="Knowledge Job",
        password_hash="hash",
        permissions="knowledge:write,projects:write",
    )
    db.add(user)
    db.flush()
    project = Project(name="Knowledge Jobs", owner_id=user.id)
    db.add(project)
    db.commit()
    return user, project


@pytest.mark.asyncio
async def test_document_upload_is_deduplicated_queued_and_indexed(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, project = project_user(db)
    content = b"# Recovery\nPostgreSQL backups must be restored in a rehearsal."
    monkeypatch.setattr("app.rag.service.object_storage.save", lambda *_args: "minio://bucket/recovery.md")
    monkeypatch.setattr("app.rag.service.object_storage.read", lambda *_args: content)
    monkeypatch.setattr("app.rag.service.vector_store.upsert", lambda *_args, **_kwargs: None)

    document = await queue_document(
        db,
        user,
        UploadFile(filename="recovery.md", file=BytesIO(content)),
        project.id,
        tags=["database", "operations"],
        source_label="runbook",
    )
    db.commit()
    assert document.status == "QUEUED"
    assert document.content_hash
    assert document.version == 1

    with pytest.raises(DuplicateDocumentError) as duplicate:
        await queue_document(
            db,
            user,
            UploadFile(filename="copy.md", file=BytesIO(content)),
            project.id,
        )
    assert duplicate.value.document_id == document.id

    await process_document(db, document.id)
    db.expire_all()
    indexed = db.get(KnowledgeDocument, document.id)
    assert indexed.status == "INDEXED"
    assert indexed.indexed_at is not None
    assert indexed.active_index_version == 1
    assert indexed.parser_name == "markdown-it-py"
    assert indexed.chunker_name == "structural-parent-child"
    assert indexed.element_count == 2
    assert indexed.chunk_count == 1
    assert db.scalar(select(func.count(Embedding.id)).where(Embedding.document_id == document.id)) == 1

    chunk = get_document_chunk(document.id, 0, user, db)
    assert chunk.citation == "recovery.md#chunk-0"
    assert "PostgreSQL backups" in chunk.content


@pytest.mark.asyncio
async def test_failed_document_can_retry_and_indexed_document_can_rebuild(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, project = project_user(db)
    document = KnowledgeDocument(
        project_id=project.id,
        owner_id=user.id,
        filename="failed.md",
        storage_path="minio://bucket/failed.md",
        status="QUEUED",
        content_hash="a" * 64,
        dedup_key=f"project:{project.id}:{'a' * 64}",
        max_attempts=1,
    )
    db.add(document)
    db.commit()

    async def fail_index(*_args, **_kwargs):
        raise RuntimeError("embedding unavailable")

    monkeypatch.setattr("app.services.knowledge.index_stored_document", fail_index)
    await process_document(db, document.id)
    db.expire_all()
    assert db.get(KnowledgeDocument, document.id).status == "FAILED"

    retried = retry_document(
        document.id,
        KnowledgeDocumentActionRequest(request_id="knowledge-retry-request"),
        user,
        db,
    )
    assert retried.status == "QUEUED"
    retried.status = "INDEXED"
    db.add(Embedding(document_id=document.id, project_id=project.id, content="old", chunk_index=0))
    db.commit()
    rebuilt = reindex_document(
        document.id,
        KnowledgeDocumentActionRequest(request_id="knowledge-reindex-request"),
        user,
        db,
    )
    assert rebuilt.status == "QUEUED"
    assert rebuilt.active_index_version == 0
    assert db.scalar(select(func.count(Embedding.id)).where(Embedding.document_id == document.id)) == 1


@pytest.mark.asyncio
async def test_reindex_activates_new_version_without_removing_previous_version(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, project = project_user(db)
    content = b"# Recovery\n\nKeep the active index available while rebuilding it."
    monkeypatch.setattr("app.rag.service.object_storage.save", lambda *_args: "minio://bucket/versioned.md")
    monkeypatch.setattr("app.rag.service.object_storage.read", lambda *_args: content)
    monkeypatch.setattr("app.rag.service.vector_store.upsert", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("app.rag.service.settings.rag_multi_vector_enabled", True)
    embedding_calls: list[list[str]] = []

    async def embed_many(texts: list[str]) -> list[list[float]]:
        embedding_calls.append(texts)
        return [[1.0] + [0.0] * 255 for _text in texts]

    monkeypatch.setattr(
        "app.rag.service.get_llm",
        lambda: SimpleNamespace(embed_many=embed_many, api_key=None, base_url="https://embedding.invalid/v1"),
    )

    document = await queue_document(
        db,
        user,
        UploadFile(filename="versioned.md", file=BytesIO(content)),
        project.id,
    )
    db.commit()
    await process_document(db, document.id)
    db.expire_all()
    indexed = db.get(KnowledgeDocument, document.id)
    assert indexed.active_index_version == 1
    assert len(embedding_calls) == 2

    reindex_document(
        document.id,
        KnowledgeDocumentActionRequest(request_id="versioned-reindex-request"),
        user,
        db,
    )
    assert get_document_chunk(document.id, 0, user, db).index_version == 1

    await process_document(db, document.id)
    db.expire_all()
    rebuilt = db.get(KnowledgeDocument, document.id)
    versions = set(
        db.scalars(select(Embedding.index_version).where(Embedding.document_id == document.id))
    )
    assert rebuilt.active_index_version == 2
    assert len(embedding_calls) == 2
    assert versions == {1, 2}
    assert get_document_chunk(document.id, 0, user, db).index_version == 2
    index_records = list(
        db.scalars(
            select(KnowledgeIndexVersion)
            .where(KnowledgeIndexVersion.document_id == document.id)
            .order_by(KnowledgeIndexVersion.version)
        )
    )
    assert [(record.version, record.status) for record in index_records] == [
        (1, "SUPERSEDED"),
        (2, "ACTIVE"),
    ]

    rollback_index_version(db, rebuilt, 1)
    db.commit()
    db.refresh(rebuilt)
    assert rebuilt.active_index_version == 1
    assert get_document_chunk(document.id, 0, user, db).index_version == 1

    monkeypatch.setattr("app.rag.service.settings.embedding_model", "replacement-embedding")
    reindex_document(
        document.id,
        KnowledgeDocumentActionRequest(request_id="versioned-reindex-after-rollback"),
        user,
        db,
    )
    await process_document(db, document.id)
    db.expire_all()
    rebuilt_after_rollback = db.get(KnowledgeDocument, document.id)
    assert rebuilt_after_rollback.active_index_version == 3
    assert len(embedding_calls) == 4
    assert set(db.scalars(select(Embedding.index_version).where(Embedding.document_id == document.id))) == {1, 2, 3}
    assert [
        (record.version, record.status)
        for record in db.scalars(
            select(KnowledgeIndexVersion)
            .where(KnowledgeIndexVersion.document_id == document.id)
            .order_by(KnowledgeIndexVersion.version)
        )
    ] == [(1, "SUPERSEDED"), (2, "SUPERSEDED"), (3, "ACTIVE")]


@pytest.mark.asyncio
async def test_failed_vector_write_cleans_attempted_ids_without_activating_index(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, project = project_user(db)
    content = b"# Recovery\n\nA failed Milvus flush must not activate this index."
    monkeypatch.setattr("app.rag.service.object_storage.save", lambda *_args: "minio://bucket/atomic.md")
    monkeypatch.setattr("app.rag.service.object_storage.read", lambda *_args: content)
    attempted: list[str] = []
    cleaned: list[str] = []

    def fail_upsert(vector_id: str, *_args, **_kwargs) -> None:
        attempted.append(vector_id)
        raise RuntimeError("Milvus flush failed")

    monkeypatch.setattr("app.rag.service.vector_store.upsert", fail_upsert)
    monkeypatch.setattr("app.rag.service.vector_store.delete_ids", lambda vector_ids: cleaned.extend(vector_ids))

    document = await queue_document(
        db,
        user,
        UploadFile(filename="atomic.md", file=BytesIO(content)),
        project.id,
    )
    db.commit()

    await process_document(db, document.id)
    db.expire_all()
    failed = db.get(KnowledgeDocument, document.id)

    assert attempted and cleaned == attempted
    assert failed.active_index_version == 0
    assert failed.status == "QUEUED"
    assert db.scalar(select(func.count(Embedding.id)).where(Embedding.document_id == document.id)) == 0
    assert db.scalar(
        select(func.count(KnowledgeIndexVersion.id)).where(KnowledgeIndexVersion.document_id == document.id)
    ) == 0


def test_project_members_share_project_documents(db: Session) -> None:
    owner, project = project_user(db)
    viewer = User(email="knowledge-viewer@example.com", name="Viewer", password_hash="hash")
    db.add(viewer)
    db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=viewer.id, role=ProjectMemberRole.viewer))
    document = KnowledgeDocument(
        project_id=project.id,
        owner_id=owner.id,
        filename="shared.md",
        storage_path="shared.md",
        status="INDEXED",
        content_hash="b" * 64,
        dedup_key=f"project:{project.id}:{'b' * 64}",
    )
    db.add(document)
    db.commit()
    assert [item.id for item in list_documents(project.id, viewer, db)] == [document.id]
    with pytest.raises(HTTPException) as missing_scope:
        get_document_chunk(document.id, 0, viewer, db)
    assert missing_scope.value.status_code == 404
