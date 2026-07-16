from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ensure_permission, get_current_user
from app.api.routes.projects import get_project_for_user
from app.core.database import get_db
from app.core.audit import record_audit
from app.models import KnowledgeDocument, User
from app.core.storage import ObjectStorageError, object_storage
from app.rag.service import DocumentValidationError, index_document, search_knowledge
from app.rag.vector_store import vector_store
from app.schemas import KnowledgeDocumentOut, KnowledgeSearchRequest, KnowledgeSearchResponse

router = APIRouter()


@router.get("/documents", response_model=list[KnowledgeDocumentOut])
def list_documents(
    project_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[KnowledgeDocument]:
    stmt = select(KnowledgeDocument).where(KnowledgeDocument.owner_id == current_user.id)
    if project_id:
        get_project_for_user(project_id, current_user, db)
        stmt = select(KnowledgeDocument).where(KnowledgeDocument.project_id == project_id)
    return list(db.scalars(stmt.order_by(KnowledgeDocument.created_at.desc())))


@router.post("/upload", response_model=KnowledgeDocumentOut)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    project_id: int | None = Form(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KnowledgeDocument:
    ensure_permission(current_user, "knowledge:write")
    if project_id:
        get_project_for_user(project_id, current_user, db, write=True)
    try:
        document = await index_document(db, current_user, file, project_id)
        record_audit(db, "knowledge.upload", current_user.id, project_id, "document", document.id, {"filename": document.filename}, request)
        db.commit()
        return document
    except DocumentValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/search", response_model=KnowledgeSearchResponse)
async def search(
    payload: KnowledgeSearchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KnowledgeSearchResponse:
    if payload.project_id:
        get_project_for_user(payload.project_id, current_user, db)
    answer, results = await search_knowledge(
        db,
        current_user,
        payload.query,
        payload.project_id,
        payload.top_k,
        payload.min_score,
    )
    return KnowledgeSearchResponse(answer=answer, results=results)


@router.delete("/documents/{document_id}")
def delete_document(
    document_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    ensure_permission(current_user, "knowledge:write")
    document = db.get(KnowledgeDocument, document_id)
    if not document or document.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    try:
        object_storage.delete(document.storage_path)
    except ObjectStorageError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    vector_store.delete_document(document.id)
    record_audit(db, "knowledge.delete", current_user.id, document.project_id, "document", document.id, {"filename": document.filename}, request)
    db.delete(document)
    db.commit()
    return {"ok": True}
