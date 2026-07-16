from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.database import get_db
from app.models import AuditLog, User
from app.schemas import AuditLogOut


router = APIRouter()


@router.get("", response_model=list[AuditLogOut])
def list_audit_logs(
    action: str | None = None,
    project_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[AuditLog]:
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if project_id is not None:
        stmt = stmt.where(AuditLog.project_id == project_id)
    return list(db.scalars(stmt.order_by(AuditLog.created_at.desc()).limit(limit)))
