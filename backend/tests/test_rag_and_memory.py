import json

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.llm import get_llm
from app.core.memory import save_project_memory
from app.models import Embedding, KnowledgeDocument, Memory, Project, User, UserRole
from app.rag.service import cosine_similarity, search_knowledge
from app.rag.vector_store import vector_store


def create_user_and_project(db: Session, email: str = "owner@example.com") -> tuple[User, Project]:
    user = User(email=email, name="Owner", password_hash="hash", role=UserRole.member)
    db.add(user)
    db.flush()
    project = Project(name="Knowledge Project", description="", owner_id=user.id)
    db.add(project)
    db.flush()
    return user, project


@pytest.mark.asyncio
async def test_local_dense_embedding_preserves_relevance() -> None:
    gateway = get_llm()
    query, relevant, irrelevant = await gateway.embed_many(
        ["PostgreSQL 数据库备份方案", "PostgreSQL 数据库如何备份和恢复", "前端按钮颜色设计"]
    )
    assert cosine_similarity(query, relevant) > cosine_similarity(query, irrelevant)


@pytest.mark.asyncio
async def test_hybrid_search_ranks_relevant_owned_document(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    owner, project = create_user_and_project(db)
    intruder, other_project = create_user_and_project(db, "other@example.com")
    documents = [
        (owner, project, "backup.md", "PostgreSQL 数据库应执行每日增量备份，并定期演练恢复流程。"),
        (owner, project, "ui.md", "按钮使用绿色，页面采用响应式布局。"),
        (intruder, other_project, "private.md", "PostgreSQL 最高机密备份口令。"),
    ]
    texts = [item[3] for item in documents]
    vectors = await get_llm().embed_many(texts)
    for index, ((user, item_project, filename, content), vector) in enumerate(zip(documents, vectors)):
        document = KnowledgeDocument(
            project_id=item_project.id,
            owner_id=user.id,
            filename=filename,
            storage_path=filename,
            status="INDEXED",
        )
        db.add(document)
        db.flush()
        db.add(
            Embedding(
                document_id=document.id,
                project_id=item_project.id,
                content=content,
                chunk_index=0,
                vector_id=f"test-{index}",
                vector_json=json.dumps(vector),
            )
        )
    db.commit()

    monkeypatch.setattr(vector_store, "search", lambda *_args, **_kwargs: [])

    async def fake_chat(*_args, **_kwargs):
        return "应执行每日增量备份并演练恢复。[backup.md#chunk-0]"

    monkeypatch.setattr(get_llm(), "chat", fake_chat)
    answer, results = await search_knowledge(db, owner, "PostgreSQL 数据库怎么备份恢复", project.id, top_k=2)
    assert results[0]["filename"] == "backup.md"
    assert all(item["filename"] != "private.md" for item in results)
    assert "backup.md#chunk-0" in answer
    assert results[0]["sparse_score"] > 0
    assert results[0]["dense_score"] > 0


def test_project_memory_is_bounded_and_compressed(db: Session) -> None:
    user, project = create_user_and_project(db)
    for index in range(20):
        save_project_memory(db, user.id, project.id, None, f"fact-{index}", f"value-{index}")
    count = db.scalar(select(func.count(Memory.id)).where(Memory.project_id == project.id))
    summaries = db.scalar(
        select(func.count(Memory.id)).where(Memory.project_id == project.id, Memory.memory_type == "summary")
    )
    assert count <= 13
    assert summaries == 1
