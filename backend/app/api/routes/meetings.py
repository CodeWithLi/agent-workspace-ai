import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import ensure_permission, get_current_user
from app.api.routes.projects import accessible_project_ids, get_project_for_user
from app.core.audit import record_audit
from app.core.database import get_db
from app.core.llm import get_llm
from app.core.llm_usage import bind_llm_usage
from app.models import Meeting, ProjectMember, Task, User
from app.schemas import MeetingCreate, MeetingOut, MeetingUpdate, TaskOut
from app.tools.project_tools import meeting_summary


router = APIRouter()


def get_meeting_for_user(meeting_id: int, user: User, db: Session, *, write: bool = False) -> Meeting:
    meeting = db.get(Meeting, meeting_id)
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    if meeting.project_id is not None:
        get_project_for_user(meeting.project_id, user, db, write=write)
    elif meeting.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    return meeting


@router.get("", response_model=list[MeetingOut])
def list_meetings(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Meeting]:
    project_ids = accessible_project_ids(current_user, db)
    return list(
        db.scalars(
            select(Meeting)
            .where(
                or_(
                    (Meeting.project_id.is_(None)) & (Meeting.user_id == current_user.id),
                    Meeting.project_id.in_(project_ids),
                )
            )
            .order_by(Meeting.created_at.desc())
        )
    )


@router.post("", response_model=MeetingOut)
async def create_meeting(
    payload: MeetingCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Meeting:
    ensure_permission(current_user, "projects:write")
    if payload.project_id:
        get_project_for_user(payload.project_id, current_user, db, write=True)
    structured = meeting_summary(payload.transcript)
    with bind_llm_usage(db=db, user_id=current_user.id, project_id=payload.project_id):
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
    db.flush()
    record_audit(db, "meeting.create", current_user.id, payload.project_id, "meeting", meeting.id, request=request)
    db.commit()
    db.refresh(meeting)
    return meeting


@router.patch("/{meeting_id}", response_model=MeetingOut)
def update_meeting(
    meeting_id: int,
    payload: MeetingUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Meeting:
    ensure_permission(current_user, "projects:write")
    meeting = get_meeting_for_user(meeting_id, current_user, db, write=True)
    values = payload.model_dump(exclude_unset=True)
    if "action_items" in values:
        values["action_items"] = json.dumps(values["action_items"], ensure_ascii=False)
    for field, value in values.items():
        setattr(meeting, field, value)
    record_audit(db, "meeting.update", current_user.id, meeting.project_id, "meeting", meeting.id, {"fields": sorted(values)}, request)
    db.commit()
    db.refresh(meeting)
    return meeting


@router.post("/{meeting_id}/tasks", response_model=list[TaskOut])
def create_tasks_from_meeting(
    meeting_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Task]:
    ensure_permission(current_user, "projects:write")
    meeting = get_meeting_for_user(meeting_id, current_user, db, write=True)
    if meeting.project_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Meeting must belong to a project")
    try:
        action_items = json.loads(meeting.action_items or "[]")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Meeting action items are invalid") from exc
    existing = set(db.scalars(select(Task.title).where(Task.project_id == meeting.project_id)))
    members = list(
        db.scalars(
            select(User)
            .join(ProjectMember, ProjectMember.user_id == User.id)
            .where(ProjectMember.project_id == meeting.project_id)
        )
    )
    created: list[Task] = []
    for item in action_items:
        title = str(item.get("task") or "").strip()
        if not title or title in existing:
            continue
        owner = str(item.get("owner") or "").strip().lower()
        assignee = next((member for member in members if owner in {member.name.lower(), member.email.lower()}), None)
        due_date = str(item.get("due_date") or "").strip()
        try:
            due_at = datetime.fromisoformat(due_date) if due_date else None
        except ValueError:
            due_at = None
        task = Task(
            project_id=meeting.project_id,
            title=title,
            description=f"由会议《{meeting.title}》行动项创建",
            assignee_user_id=assignee.id if assignee else None,
            due_date=due_date,
            due_at=due_at,
        )
        db.add(task)
        created.append(task)
        existing.add(title)
    db.flush()
    record_audit(
        db,
        "meeting.tasks_create",
        current_user.id,
        meeting.project_id,
        "meeting",
        meeting.id,
        {"task_ids": [item.id for item in created]},
        request,
    )
    db.commit()
    for item in created:
        db.refresh(item)
    return created


@router.delete("/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_meeting(
    meeting_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    ensure_permission(current_user, "projects:write")
    meeting = get_meeting_for_user(meeting_id, current_user, db, write=True)
    record_audit(db, "meeting.delete", current_user.id, meeting.project_id, "meeting", meeting.id, request=request)
    db.delete(meeting)
    db.commit()
