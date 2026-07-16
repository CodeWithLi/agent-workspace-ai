from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.audit import record_audit
from app.core.database import get_db
from app.models import User, UserRole, UserSession
from app.schemas import UserAdminUpdate, UserOut


router = APIRouter()
ALLOWED_PERMISSIONS = {"agents:read", "projects:write", "knowledge:write"}


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.get("", response_model=list[UserOut])
def list_users(
    q: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[User]:
    stmt = select(User)
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(or_(User.email.ilike(pattern), User.name.ilike(pattern)))
    return list(db.scalars(stmt.order_by(User.created_at.desc()).limit(limit)))


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserAdminUpdate,
    request: Request,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.id == current_admin.id and (payload.is_active is False or payload.role == UserRole.member):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Administrators cannot disable or demote themselves")
    changed: list[str] = []
    if payload.role is not None and payload.role != user.role:
        user.role = payload.role
        changed.append("role")
    if payload.is_active is not None and payload.is_active != user.is_active:
        user.is_active = payload.is_active
        changed.append("is_active")
        if not user.is_active:
            now = datetime.now(timezone.utc)
            for session in db.scalars(select(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))):
                session.revoked_at = now
    if payload.permissions is not None:
        permissions = set(payload.permissions)
        invalid = permissions - ALLOWED_PERMISSIONS
        if invalid:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Unknown permissions: {sorted(invalid)}")
        user.permissions = ",".join(sorted(permissions))
        changed.append("permissions")
    record_audit(
        db,
        "user.update",
        current_admin.id,
        resource_type="user",
        resource_id=user.id,
        details={"changed_fields": changed},
        request=request,
    )
    db.commit()
    db.refresh(user)
    return user


@router.post("/{user_id}/revoke-sessions", status_code=status.HTTP_204_NO_CONTENT)
def revoke_user_sessions(
    user_id: int,
    request: Request,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> None:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    now = datetime.now(timezone.utc)
    sessions = list(db.scalars(select(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))))
    for session in sessions:
        session.revoked_at = now
    record_audit(
        db,
        "user.sessions_revoke",
        current_admin.id,
        resource_type="user",
        resource_id=user.id,
        details={"revoked_count": len(sessions)},
        request=request,
    )
    db.commit()
