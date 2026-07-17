from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import ensure_permission, get_current_user
from app.api.routes.projects import accessible_project_ids, get_project_for_user
from app.core.audit import record_audit
from app.core.database import get_db
from app.core.llm import get_llm
from app.core.llm_usage import bind_llm_usage
from app.models import Requirement, User
from app.schemas import RequirementCreate, RequirementOut, RequirementUpdate
from app.tools.project_tools import requirement_create


router = APIRouter()


def get_requirement_for_user(
    requirement_id: int,
    current_user: User,
    db: Session,
    *,
    write: bool = False,
) -> Requirement:
    item = db.get(Requirement, requirement_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requirement not found")
    if item.project_id is not None:
        get_project_for_user(item.project_id, current_user, db, write=write)
    elif item.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requirement not found")
    return item


@router.get("", response_model=list[RequirementOut])
def list_requirements(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Requirement]:
    project_ids = accessible_project_ids(current_user, db)
    return list(
        db.scalars(
            select(Requirement)
            .where(
                or_(
                    (Requirement.project_id.is_(None)) & (Requirement.user_id == current_user.id),
                    Requirement.project_id.in_(project_ids),
                )
            )
            .order_by(Requirement.created_at.desc())
        )
    )


@router.post("", response_model=RequirementOut)
async def create_requirement(
    payload: RequirementCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Requirement:
    ensure_permission(current_user, "projects:write")
    if payload.project_id:
        get_project_for_user(payload.project_id, current_user, db, write=True)
    structured = requirement_create(payload.content)
    with bind_llm_usage(db=db, user_id=current_user.id, project_id=payload.project_id):
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
    db.flush()
    record_audit(db, "requirement.create", current_user.id, payload.project_id, "requirement", requirement.id, request=request)
    db.commit()
    db.refresh(requirement)
    return requirement


@router.patch("/{requirement_id}", response_model=RequirementOut)
def update_requirement(
    requirement_id: int,
    payload: RequirementUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Requirement:
    ensure_permission(current_user, "projects:write")
    item = get_requirement_for_user(requirement_id, current_user, db, write=True)
    values = payload.model_dump(exclude_unset=True)
    for field, value in values.items():
        setattr(item, field, value)
    record_audit(db, "requirement.update", current_user.id, item.project_id, "requirement", item.id, {"fields": sorted(values)}, request)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{requirement_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_requirement(
    requirement_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    ensure_permission(current_user, "projects:write")
    item = get_requirement_for_user(requirement_id, current_user, db, write=True)
    record_audit(db, "requirement.delete", current_user.id, item.project_id, "requirement", item.id, request=request)
    db.delete(item)
    db.commit()
