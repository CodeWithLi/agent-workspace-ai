import json
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditLog


def request_ip(request: Request | None) -> str:
    if request is None:
        return ""
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "")


def record_audit(
    db: Session,
    action: str,
    user_id: int | None = None,
    project_id: int | None = None,
    resource_type: str = "",
    resource_id: str | int = "",
    details: dict[str, Any] | None = None,
    request: Request | None = None,
) -> AuditLog:
    entry = AuditLog(
        user_id=user_id,
        project_id=project_id,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        details=json.dumps(details or {}, ensure_ascii=False, default=str),
        ip_address=request_ip(request),
    )
    db.add(entry)
    db.flush()
    return entry
