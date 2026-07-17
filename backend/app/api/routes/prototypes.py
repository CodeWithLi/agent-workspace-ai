import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import ensure_permission, get_current_user
from app.api.routes.projects import accessible_project_ids, get_project_for_user
from app.core.audit import record_audit
from app.core.database import get_db
from app.models import ProductPrototype, ProductPrototypeVersion, Requirement, User
from app.prototypes.schemas import (
    PrototypeDetailOut,
    PrototypeGenerateRequest,
    PrototypeOut,
    PrototypeRegenerateRequest,
    PrototypeUpdateRequest,
)
from app.prototypes.service import generate_prototype_version, version_out


router = APIRouter()


def get_prototype_for_user(
    prototype_id: int,
    current_user: User,
    db: Session,
    *,
    write: bool = False,
) -> ProductPrototype:
    prototype = db.get(ProductPrototype, prototype_id)
    if not prototype:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prototype not found")
    get_project_for_user(prototype.project_id, current_user, db, write=write)
    return prototype


def current_version(db: Session, prototype: ProductPrototype) -> ProductPrototypeVersion:
    item = db.scalar(
        select(ProductPrototypeVersion).where(
            ProductPrototypeVersion.prototype_id == prototype.id,
            ProductPrototypeVersion.version == prototype.active_version,
        )
    )
    if not item:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Prototype active version is unavailable",
        )
    return item


def prototype_out(db: Session, prototype: ProductPrototype) -> PrototypeOut:
    version = current_version(db, prototype)
    specification = json.loads(version.specification_json)
    quality = json.loads(version.quality_json or "{}")
    return PrototypeOut(
        id=prototype.id,
        project_id=prototype.project_id,
        requirement_id=prototype.requirement_id,
        created_by_user_id=prototype.created_by_user_id,
        title=prototype.title,
        summary=prototype.summary,
        status=prototype.status,
        active_version=prototype.active_version,
        screen_count=len(specification.get("screens", [])),
        quality_score=float(quality.get("score", 0)),
        created_at=prototype.created_at,
        updated_at=prototype.updated_at,
    )


def prototype_detail(db: Session, prototype: ProductPrototype) -> PrototypeDetailOut:
    versions = list(
        db.scalars(
            select(ProductPrototypeVersion)
            .where(ProductPrototypeVersion.prototype_id == prototype.id)
            .order_by(ProductPrototypeVersion.version.desc())
        )
    )
    active = next((item for item in versions if item.version == prototype.active_version), None)
    if not active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Prototype active version is unavailable",
        )
    summary = prototype_out(db, prototype)
    return PrototypeDetailOut(
        **summary.model_dump(),
        current=version_out(active),
        versions=[version_out(item) for item in versions],
    )


@router.get("", response_model=list[PrototypeOut])
def list_prototypes(
    project_id: int | None = None,
    requirement_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PrototypeOut]:
    project_ids = accessible_project_ids(current_user, db)
    if not project_ids:
        return []
    stmt = select(ProductPrototype).where(ProductPrototype.project_id.in_(project_ids))
    if project_id is not None:
        get_project_for_user(project_id, current_user, db)
        stmt = stmt.where(ProductPrototype.project_id == project_id)
    if requirement_id is not None:
        stmt = stmt.where(ProductPrototype.requirement_id == requirement_id)
    items = list(db.scalars(stmt.order_by(ProductPrototype.updated_at.desc()).limit(100)))
    return [prototype_out(db, item) for item in items]


@router.post("/generate", response_model=PrototypeDetailOut, status_code=status.HTTP_201_CREATED)
async def generate_prototype(
    payload: PrototypeGenerateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PrototypeDetailOut:
    ensure_permission(current_user, "projects:write")
    get_project_for_user(payload.project_id, current_user, db, write=True)
    if payload.requirement_id is not None:
        requirement = db.get(Requirement, payload.requirement_id)
        if not requirement or requirement.project_id != payload.project_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Requirement must belong to the selected project",
            )
    prototype = ProductPrototype(
        project_id=payload.project_id,
        requirement_id=payload.requirement_id,
        created_by_user_id=current_user.id,
        title=payload.title,
        status="DRAFT",
        active_version=1,
    )
    db.add(prototype)
    db.flush()
    version = await generate_prototype_version(
        db,
        current_user,
        prototype,
        payload.prompt,
        version=1,
    )
    specification = json.loads(version.specification_json)
    prototype.summary = specification["summary"]
    record_audit(
        db,
        "prototype.generate",
        current_user.id,
        prototype.project_id,
        "product_prototype",
        prototype.id,
        {
            "requirement_id": prototype.requirement_id,
            "version": 1,
            "generation_mode": version.generation_mode,
        },
        request,
    )
    db.commit()
    db.refresh(prototype)
    return prototype_detail(db, prototype)


@router.get("/{prototype_id}", response_model=PrototypeDetailOut)
def get_prototype(
    prototype_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PrototypeDetailOut:
    return prototype_detail(db, get_prototype_for_user(prototype_id, current_user, db))


@router.patch("/{prototype_id}", response_model=PrototypeDetailOut)
def update_prototype(
    prototype_id: int,
    payload: PrototypeUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PrototypeDetailOut:
    ensure_permission(current_user, "projects:write")
    prototype = get_prototype_for_user(prototype_id, current_user, db, write=True)
    values = payload.model_dump(exclude_unset=True)
    for field, value in values.items():
        setattr(prototype, field, value)
    record_audit(
        db,
        "prototype.update",
        current_user.id,
        prototype.project_id,
        "product_prototype",
        prototype.id,
        {"fields": sorted(values)},
        request,
    )
    db.commit()
    db.refresh(prototype)
    return prototype_detail(db, prototype)


@router.post("/{prototype_id}/regenerate", response_model=PrototypeDetailOut)
async def regenerate_prototype(
    prototype_id: int,
    payload: PrototypeRegenerateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PrototypeDetailOut:
    ensure_permission(current_user, "projects:write")
    prototype = get_prototype_for_user(prototype_id, current_user, db, write=True)
    previous = current_version(db, prototype)
    next_version = int(
        db.scalar(
            select(func.coalesce(func.max(ProductPrototypeVersion.version), 0)).where(
                ProductPrototypeVersion.prototype_id == prototype.id
            )
        )
    ) + 1
    source_prompt = previous.source_prompt
    if payload.feedback.strip():
        source_prompt = f"{source_prompt}\n\n本轮修改意见：{payload.feedback.strip()}"
    version = await generate_prototype_version(
        db,
        current_user,
        prototype,
        source_prompt,
        version=next_version,
    )
    specification = json.loads(version.specification_json)
    prototype.active_version = next_version
    prototype.summary = specification["summary"]
    prototype.status = "DRAFT"
    record_audit(
        db,
        "prototype.regenerate",
        current_user.id,
        prototype.project_id,
        "product_prototype",
        prototype.id,
        {"version": next_version, "generation_mode": version.generation_mode},
        request,
    )
    db.commit()
    db.refresh(prototype)
    return prototype_detail(db, prototype)


@router.post("/{prototype_id}/versions/{version}/activate", response_model=PrototypeDetailOut)
def activate_prototype_version(
    prototype_id: int,
    version: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PrototypeDetailOut:
    ensure_permission(current_user, "projects:write")
    prototype = get_prototype_for_user(prototype_id, current_user, db, write=True)
    selected = db.scalar(
        select(ProductPrototypeVersion).where(
            ProductPrototypeVersion.prototype_id == prototype.id,
            ProductPrototypeVersion.version == version,
        )
    )
    if not selected:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prototype version not found")
    prototype.active_version = version
    prototype.summary = json.loads(selected.specification_json)["summary"]
    record_audit(
        db,
        "prototype.version_activate",
        current_user.id,
        prototype.project_id,
        "product_prototype",
        prototype.id,
        {"version": version},
        request,
    )
    db.commit()
    db.refresh(prototype)
    return prototype_detail(db, prototype)


@router.delete("/{prototype_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_prototype(
    prototype_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    ensure_permission(current_user, "projects:write")
    prototype = get_prototype_for_user(prototype_id, current_user, db, write=True)
    record_audit(
        db,
        "prototype.delete",
        current_user.id,
        prototype.project_id,
        "product_prototype",
        prototype.id,
        request=request,
    )
    db.delete(prototype)
    db.commit()
