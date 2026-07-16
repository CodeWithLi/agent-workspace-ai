from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.routes.projects import get_project_for_user
from app.core.database import get_db
from app.models import Notification, User
from app.schemas import NotificationCreate, NotificationOut
from app.tools.project_tools import notification_create

router = APIRouter()


@router.get("", response_model=list[NotificationOut])
def list_notifications(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Notification]:
    return list(
        db.scalars(select(Notification).where(Notification.user_id == current_user.id).order_by(Notification.created_at.desc()))
    )


@router.post("", response_model=NotificationOut)
def create_notification(
    payload: NotificationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Notification:
    if payload.project_id:
        get_project_for_user(payload.project_id, current_user, db, write=True)
    draft = notification_create(payload.title, payload.content, payload.channel)
    notification = Notification(
        project_id=payload.project_id,
        user_id=current_user.id,
        title=draft["title"],
        content=draft["content"],
        channel=payload.channel,
        schedule_at=payload.schedule_at,
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)
    return notification
