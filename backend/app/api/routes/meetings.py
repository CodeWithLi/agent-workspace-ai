import json

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ensure_permission, get_current_user
from app.api.routes.projects import get_project_for_user
from app.core.database import get_db
from app.core.llm import get_llm
from app.models import Meeting, User
from app.schemas import MeetingCreate, MeetingOut
from app.tools.project_tools import meeting_summary

router = APIRouter()


@router.get("", response_model=list[MeetingOut])
def list_meetings(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Meeting]:
    return list(db.scalars(select(Meeting).where(Meeting.user_id == current_user.id).order_by(Meeting.created_at.desc())))


@router.post("", response_model=MeetingOut)
async def create_meeting(
    payload: MeetingCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Meeting:
    ensure_permission(current_user, "projects:write")
    if payload.project_id:
        get_project_for_user(payload.project_id, current_user, db, write=True)
    structured = meeting_summary(payload.transcript)
    llm_summary = await get_llm().chat("你是AI会议纪要员。生成会议纪要和TODO。", payload.transcript)
    meeting = Meeting(
        project_id=payload.project_id,
        user_id=current_user.id,
        title=payload.title,
        transcript=payload.transcript,
        summary=llm_summary,
        action_items=json.dumps(structured["todos"], ensure_ascii=False),
    )
    db.add(meeting)
    db.commit()
    db.refresh(meeting)
    return meeting
