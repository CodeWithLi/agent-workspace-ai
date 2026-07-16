from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import ensure_permission, get_current_user
from app.api.routes.projects import get_project_for_user
from app.core.audit import record_audit
from app.core.database import get_db
from app.models import Notification, User
from app.schemas import NotificationCreate, NotificationOut
from app.tools.project_tools import notification_create


router = APIRouter()


def owned_notification(notification_id: int, user: User, db: Session) -> Notification:
    notification = db.get(Notification, notification_id)
    if not notification or notification.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    return notification


@router.get("", response_model=list[NotificationOut])
def list_notifications(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Notification]:
    return list(
        db.scalars(
            select(Notification)
            .where(or_(Notification.user_id == current_user.id, Notification.recipient_user_id == current_user.id))
            .order_by(Notification.created_at.desc())
        )
    )


@router.post("", response_model=NotificationOut)
def create_notification(
    payload: NotificationCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Notification:
    ensure_permission(current_user, "projects:write")
    if payload.project_id:
        get_project_for_user(payload.project_id, current_user, db, write=True)
    recipient = current_user
    if payload.recipient_email:
        recipient = db.scalar(select(User).where(User.email == payload.recipient_email))
        if payload.channel == "in_app" and recipient is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="In-app recipient must be a registered user")
    if payload.channel == "email" and not payload.recipient_email:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Email recipient is required")
    draft = notification_create(payload.title, payload.content, payload.channel)
    scheduled_for = payload.schedule_at
    if scheduled_for and scheduled_for.tzinfo is None:
        scheduled_for = scheduled_for.replace(tzinfo=timezone.utc)
    recipient_email = str(payload.recipient_email) if payload.recipient_email else (recipient.email if recipient else "")
    notification = Notification(
        project_id=payload.project_id,
        user_id=current_user.id,
        recipient_user_id=recipient.id if recipient else None,
        recipient_email=recipient_email,
        title=draft["title"],
        content=draft["content"],
        channel=payload.channel,
        schedule_at=scheduled_for.isoformat() if scheduled_for else "",
        scheduled_for=scheduled_for,
        status="SCHEDULED" if scheduled_for else "DRAFT",
    )
    db.add(notification)
    db.flush()
    record_audit(
        db,
        "notification.create",
        current_user.id,
        payload.project_id,
        "notification",
        notification.id,
        {"channel": notification.channel, "status": notification.status, "recipient_user_id": notification.recipient_user_id},
        request,
    )
    db.commit()
    db.refresh(notification)
    return notification


@router.post("/{notification_id}/send", response_model=NotificationOut)
def send_notification_now(
    notification_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Notification:
    ensure_permission(current_user, "projects:write")
    notification = owned_notification(notification_id, current_user, db)
    if notification.status not in {"DRAFT", "FAILED", "CANCELLED"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Notification cannot be scheduled from its current status")
    notification.status = "SCHEDULED"
    notification.scheduled_for = datetime.now(timezone.utc)
    notification.schedule_at = notification.scheduled_for.isoformat()
    notification.last_error = ""
    notification.attempts = 0
    record_audit(db, "notification.schedule_now", current_user.id, notification.project_id, "notification", notification.id, request=request)
    db.commit()
    db.refresh(notification)
    return notification


@router.post("/{notification_id}/cancel", response_model=NotificationOut)
def cancel_notification(
    notification_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Notification:
    ensure_permission(current_user, "projects:write")
    notification = owned_notification(notification_id, current_user, db)
    if notification.status not in {"DRAFT", "SCHEDULED"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only draft or scheduled notifications can be cancelled")
    notification.status = "CANCELLED"
    record_audit(db, "notification.cancel", current_user.id, notification.project_id, "notification", notification.id, request=request)
    db.commit()
    db.refresh(notification)
    return notification
