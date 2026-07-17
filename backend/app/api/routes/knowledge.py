import json
from time import perf_counter

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ensure_permission, get_current_user
from app.api.routes.projects import get_project_for_user
from app.core.audit import record_audit
from app.core.config import get_settings
from app.core.database import get_db
from app.core.storage import ObjectStorageError, object_storage
from app.core.llm_usage import bind_llm_usage
from app.core.metrics import RAG_SEARCH_DURATION, RAG_SEARCH_RESULTS
from app.models import Embedding, KnowledgeDocument, KnowledgeIndexVersion, User
from app.rag.service import (
    DuplicateDocumentError,
    DocumentValidationError,
    queue_document,
    rollback_index_version,
    search_knowledge,
)
from app.rag.vector_store import vector_store
from app.schemas import (
    KnowledgeChunkOut,
    KnowledgeDocumentActionRequest,
    KnowledgeDocumentOut,
    KnowledgeDocumentUpdate,
    KnowledgeIndexVersionOut,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
)


router = APIRouter()
settings = get_settings()


def get_document_for_user(
    document_id: int,
    current_user: User,
    db: Session,
    *,
    write: bool = False,
) -> KnowledgeDocument:
    document = db.get(KnowledgeDocument, document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    if document.project_id is not None:
        get_project_for_user(document.project_id, current_user, db, write=write)
    elif document.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return document


@router.get("/documents", response_model=list[KnowledgeDocumentOut])
def list_documents(
    project_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[KnowledgeDocument]:
    if project_id is not None:
        get_project_for_user(project_id, current_user, db)
        stmt = select(KnowledgeDocument).where(KnowledgeDocument.project_id == project_id)
    else:
        stmt = select(KnowledgeDocument).where(
            KnowledgeDocument.project_id.is_(None),
            KnowledgeDocument.owner_id == current_user.id,
        )
    return list(db.scalars(stmt.order_by(KnowledgeDocument.created_at.desc()).limit(200)))


@router.post("/upload", response_model=KnowledgeDocumentOut, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    project_id: int | None = Form(default=None),
    tags: str = Form(default=""),
    source_label: str = Form(default="upload"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KnowledgeDocument:
    ensure_permission(current_user, "knowledge:write")
    if project_id is not None:
        get_project_for_user(project_id, current_user, db, write=True)
    try:
        document = await queue_document(
            db,
            current_user,
            file,
            project_id,
            tags=[item.strip() for item in tags.split(",") if item.strip()],
            source_label=source_label,
        )
        record_audit(
            db,
            "knowledge.queued",
            current_user.id,
            project_id,
            "document",
            document.id,
            {"filename": document.filename, "version": document.version},
            request,
        )
        db.commit()
        db.refresh(document)
        return document
    except DuplicateDocumentError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(exc), "existing_document_id": exc.document_id},
        ) from exc
    except DocumentValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/documents/{document_id}", response_model=KnowledgeDocumentOut)
def update_document(
    document_id: int,
    payload: KnowledgeDocumentUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KnowledgeDocument:
    ensure_permission(current_user, "knowledge:write")
    document = get_document_for_user(document_id, current_user, db, write=True)
    document.source_label = payload.source_label.strip()
    document.metadata_json = json.dumps({"tags": sorted(set(payload.tags))}, ensure_ascii=False)
    record_audit(
        db,
        "knowledge.metadata_updated",
        current_user.id,
        document.project_id,
        "document",
        document.id,
        request=request,
    )
    db.commit()
    db.refresh(document)
    return document


@router.post("/search", response_model=KnowledgeSearchResponse)
async def search(
    payload: KnowledgeSearchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KnowledgeSearchResponse:
    if payload.project_id is not None:
        get_project_for_user(payload.project_id, current_user, db)
    started = perf_counter()
    try:
        with bind_llm_usage(db=db, user_id=current_user.id, project_id=payload.project_id):
            answer, results = await search_knowledge(
                db,
                current_user,
                payload.query,
                payload.project_id,
                payload.top_k if payload.top_k is not None else settings.rag_top_k,
                payload.min_score if payload.min_score is not None else settings.rag_min_score,
                document_ids=payload.document_ids,
                tags=payload.tags,
                source_labels=payload.source_labels,
            )
        RAG_SEARCH_DURATION.labels("success").observe(perf_counter() - started)
        RAG_SEARCH_RESULTS.observe(len(results))
    except Exception:
        RAG_SEARCH_DURATION.labels("failed").observe(perf_counter() - started)
        raise
    db.commit()
    return KnowledgeSearchResponse(answer=answer, results=results)


@router.get("/documents/{document_id}/chunks/{chunk_index}", response_model=KnowledgeChunkOut)
def get_document_chunk(
    document_id: int,
    chunk_index: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KnowledgeChunkOut:
    document = get_document_for_user(document_id, current_user, db)
    chunk = db.scalar(
        select(Embedding).where(
            Embedding.document_id == document.id,
            Embedding.index_version == document.active_index_version,
            Embedding.chunk_index == chunk_index,
        )
    )
    if not chunk:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document chunk not found")
    return KnowledgeChunkOut(
        document_id=document.id,
        filename=document.filename,
        chunk_index=chunk.chunk_index,
        content=chunk.content,
        citation=f"{document.filename}#chunk-{chunk.chunk_index}",
        stable_id=chunk.stable_id,
        index_version=chunk.index_version,
        parent_stable_id=chunk.parent_stable_id,
        parent_content=chunk.parent_content,
        heading_path=json.loads(chunk.heading_path_json or "[]"),
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        token_count=chunk.token_count,
    )


@router.get("/documents/{document_id}/index-versions", response_model=list[KnowledgeIndexVersionOut])
def list_index_versions(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[KnowledgeIndexVersion]:
    document = get_document_for_user(document_id, current_user, db)
    return list(
        db.scalars(
            select(KnowledgeIndexVersion)
            .where(KnowledgeIndexVersion.document_id == document.id)
            .order_by(KnowledgeIndexVersion.version.desc())
        )
    )


@router.post(
    "/documents/{document_id}/index-versions/{index_version}/activate",
    response_model=KnowledgeDocumentOut,
)
def activate_index_version(
    document_id: int,
    index_version: int,
    payload: KnowledgeDocumentActionRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KnowledgeDocument:
    ensure_permission(current_user, "knowledge:write")
    document = get_document_for_user(document_id, current_user, db, write=True)
    if document.status == "INDEXING":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Document is currently indexing")
    try:
        rollback_index_version(db, document, index_version)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    record_audit(
        db,
        "knowledge.index_version_activated",
        current_user.id,
        document.project_id,
        "document",
        document.id,
        {"request_id": payload.request_id, "index_version": index_version},
        request,
    )
    db.commit()
    db.refresh(document)
    return document


@router.post("/documents/{document_id}/retry", response_model=KnowledgeDocumentOut, status_code=status.HTTP_202_ACCEPTED)
def retry_document(
    document_id: int,
    payload: KnowledgeDocumentActionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KnowledgeDocument:
    ensure_permission(current_user, "knowledge:write")
    document = get_document_for_user(document_id, current_user, db, write=True)
    if document.status != "FAILED":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only failed documents can be retried")
    document.status = "QUEUED"
    document.attempts = 0
    document.max_attempts = settings.knowledge_max_attempts
    document.error = ""
    document.locked_at = None
    record_audit(
        db,
        "knowledge.retry",
        current_user.id,
        document.project_id,
        "document",
        document.id,
        {"request_id": payload.request_id},
    )
    db.commit()
    db.refresh(document)
    return document


@router.post("/documents/{document_id}/reindex", response_model=KnowledgeDocumentOut, status_code=status.HTTP_202_ACCEPTED)
def reindex_document(
    document_id: int,
    payload: KnowledgeDocumentActionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KnowledgeDocument:
    ensure_permission(current_user, "knowledge:write")
    document = get_document_for_user(document_id, current_user, db, write=True)
    if document.status in {"QUEUED", "INDEXING"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Document is already being indexed")
    document.status = "QUEUED"
    document.attempts = 0
    document.max_attempts = settings.knowledge_max_attempts
    document.error = ""
    document.locked_at = None
    document.indexed_at = None
    record_audit(
        db,
        "knowledge.reindex",
        current_user.id,
        document.project_id,
        "document",
        document.id,
        {"request_id": payload.request_id},
    )
    db.commit()
    db.refresh(document)
    return document


@router.delete("/documents/{document_id}")
def delete_document(
    document_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    ensure_permission(current_user, "knowledge:write")
    document = get_document_for_user(document_id, current_user, db, write=True)
    try:
        object_storage.delete(document.storage_path)
    except ObjectStorageError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    vector_store.delete_document(document.id)
    record_audit(
        db,
        "knowledge.delete",
        current_user.id,
        document.project_id,
        "document",
        document.id,
        {"filename": document.filename},
        request,
    )
    db.delete(document)
    db.commit()
    return {"ok": True}
