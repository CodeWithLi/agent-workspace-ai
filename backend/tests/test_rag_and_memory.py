import json

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.llm import get_llm
from app.core.memory import save_project_memory
from app.models import Embedding, KnowledgeDocument, Memory, Project, User, UserRole
from app.rag.service import build_context, cosine_similarity, ensure_valid_citations, rewrite_query, search_knowledge
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
            metadata_json=json.dumps({"tags": ["database"] if filename == "backup.md" else ["other"]}),
            source_label="runbook" if filename == "backup.md" else "upload",
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

    monkeypatch.setattr(vector_store, "hybrid_search", lambda *_args, **_kwargs: [])

    async def fake_chat(*_args, **_kwargs):
        return "应执行每日增量备份并演练恢复。[backup.md#chunk-0]"

    monkeypatch.setattr(get_llm(), "chat", fake_chat)
    answer, results = await search_knowledge(
        db,
        owner,
        "PostgreSQL 数据库怎么备份恢复",
        project.id,
        top_k=2,
        tags=["database"],
        source_labels=["runbook"],
    )
    assert results[0]["filename"] == "backup.md"
    assert all(item["filename"] != "private.md" for item in results)
    assert "backup.md#chunk-0" in answer
    assert results[0]["sparse_score"] > 0
    assert results[0]["dense_score"] > 0
    assert results[0]["tags"] == ["database"]
    assert results[0]["source_label"] == "runbook"


@pytest.mark.asyncio
async def test_personal_search_excludes_documents_from_owned_projects(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, project = create_user_and_project(db)
    personal = KnowledgeDocument(
        project_id=None,
        owner_id=owner.id,
        filename="personal.md",
        storage_path="personal.md",
        status="INDEXED",
    )
    project_document = KnowledgeDocument(
        project_id=project.id,
        owner_id=owner.id,
        filename="project-secret.md",
        storage_path="project-secret.md",
        status="INDEXED",
    )
    db.add_all([personal, project_document])
    db.flush()
    vectors = await get_llm().embed_many(["个人备忘录", "项目机密信息"])
    db.add_all(
        [
            Embedding(
                document_id=personal.id,
                project_id=None,
                content="个人备忘录",
                chunk_index=0,
                vector_id="personal-vector",
                vector_json=json.dumps(vectors[0]),
            ),
            Embedding(
                document_id=project_document.id,
                project_id=project.id,
                content="项目机密信息",
                chunk_index=0,
                vector_id="project-vector",
                vector_json=json.dumps(vectors[1]),
            ),
        ]
    )
    db.commit()
    monkeypatch.setattr(vector_store, "hybrid_search", lambda *_args, **_kwargs: [])

    async def fake_chat(*_args, **_kwargs):
        return "个人信息。[personal.md#chunk-0]"

    monkeypatch.setattr(get_llm(), "chat", fake_chat)
    _, results = await search_knowledge(db, owner, "个人备忘录", project_id=None, top_k=5, min_score=0)

    assert [result["filename"] for result in results] == ["personal.md"]


def test_parent_context_is_deduplicated_bounded_and_citations_are_validated() -> None:
    rows = [
        {
            "document_id": 1,
            "stable_id": "child-a",
            "parent_stable_id": "parent-a",
            "parent_content": "父块完整内容。" * 100,
            "content": "子块 A",
            "citation": "runbook.md#chunk-0",
            "score": 0.9,
        }
    ]

    context = build_context(rows, max_tokens=80)
    answer = ensure_valid_citations("结论。[fake.md#chunk-9]", rows)

    assert "父块完整内容" in context
    assert "fake.md" not in answer
    assert "[runbook.md#chunk-0]" in answer


@pytest.mark.asyncio
async def test_query_rewrite_accepts_only_bounded_structured_variants(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_chat(*_args, **_kwargs):
        return '```json\n{"queries":["restore drill", "backup recovery exercise", "extra"]}\n```'

    monkeypatch.setattr(get_llm(), "chat", fake_chat)
    monkeypatch.setattr("app.rag.service.settings.rag_query_rewrite_enabled", True)
    monkeypatch.setattr("app.rag.service.settings.rag_query_rewrite_max_variants", 3)

    assert await rewrite_query("恢复演练") == ["恢复演练", "restore drill", "backup recovery exercise"]


@pytest.mark.asyncio
async def test_query_rewrite_falls_back_on_unstructured_output(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_chat(*_args, **_kwargs):
        return "直接回答而不是 JSON"

    monkeypatch.setattr(get_llm(), "chat", fake_chat)
    monkeypatch.setattr("app.rag.service.settings.rag_query_rewrite_enabled", True)

    assert await rewrite_query("原始查询") == ["原始查询"]


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
