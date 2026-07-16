from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ensure_permission, get_current_user
from app.api.routes.projects import get_project_for_user
from app.core.database import get_db
from app.core.llm import get_llm
from app.models import Requirement, User
from app.schemas import RequirementCreate, RequirementOut
from app.tools.project_tools import requirement_create

router = APIRouter()


@router.get("", response_model=list[RequirementOut])
def list_requirements(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Requirement]:
    return list(
        db.scalars(select(Requirement).where(Requirement.user_id == current_user.id).order_by(Requirement.created_at.desc()))
    )


@router.post("", response_model=RequirementOut)
async def create_requirement(
    payload: RequirementCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Requirement:
    ensure_permission(current_user, "projects:write")
    if payload.project_id:
        get_project_for_user(payload.project_id, current_user, db, write=True)
    structured = requirement_create(payload.content)
    analysis = await get_llm().chat(
        "你是AI产品经理。把模糊想法澄清成需求卡片和验收标准。",
        f"标题：{payload.title}\n内容：{payload.content}\n结构化草案：{structured}",
    )
    requirement = Requirement(
        project_id=payload.project_id,
        user_id=current_user.id,
        title=payload.title,
        content=payload.content,
        analysis=analysis,
        status="ANALYZED",
    )
    db.add(requirement)
    db.commit()
    db.refresh(requirement)
    return requirement
