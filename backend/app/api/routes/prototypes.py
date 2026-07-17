import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import ensure_permission, get_current_user
from app.api.routes.projects import accessible_project_ids, get_project_for_user
from app.core.audit import record_audit
from app.core.database import get_db
from app.models import (
    ProductPrototype,
    ProductPrototypeMaterialization,
    ProductPrototypeVersion,
    PrototypeReviewComment,
    PrototypeTestCase,
    Requirement,
    Task,
    User,
)
from app.prototypes.delivery import (
    build_prototype_task_blueprints,
    build_prototype_test_case_blueprints,
)
from app.prototypes.schemas import (
    PrototypeCommentCreate,
    PrototypeCommentOut,
    PrototypeCommentUpdate,
    PrototypeDetailOut,
    PrototypeGenerateRequest,
    PrototypeMaterializationOut,
    PrototypeMaterializeRequest,
    PrototypeOut,
    PrototypeRegenerateRequest,
    PrototypeSpecification,
    PrototypeTestCaseOut,
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


def comment_out(db: Session, item: PrototypeReviewComment) -> PrototypeCommentOut:
    author = db.get(User, item.user_id)
    return PrototypeCommentOut(
        id=item.id,
        prototype_id=item.prototype_id,
        prototype_version=item.prototype_version,
        screen_id=item.screen_id,
        user_id=item.user_id,
        user_name=author.name if author else "Unknown",
        body=item.body,
        status=item.status,
        resolved_by_user_id=item.resolved_by_user_id,
        resolved_at=item.resolved_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def test_case_out(item: PrototypeTestCase) -> PrototypeTestCaseOut:
    return PrototypeTestCaseOut(
        id=item.id,
        prototype_id=item.prototype_id,
        prototype_version=item.prototype_version,
        screen_id=item.screen_id,
        case_key=item.case_key,
        title=item.title,
        preconditions=item.preconditions,
        steps=json.loads(item.steps_json or "[]"),
        expected_result=item.expected_result,
        priority=item.priority,
        created_at=item.created_at,
    )


def materialization_out(
    db: Session,
    item: ProductPrototypeMaterialization,
) -> PrototypeMaterializationOut:
    task_ids = list(
        db.scalars(
            select(Task.id)
            .where(
                Task.source_prototype_id == item.prototype_id,
                Task.source_prototype_version == item.prototype_version,
            )
            .order_by(Task.id)
        )
    )
    test_cases = list(
        db.scalars(
            select(PrototypeTestCase)
            .where(
                PrototypeTestCase.prototype_id == item.prototype_id,
                PrototypeTestCase.prototype_version == item.prototype_version,
            )
            .order_by(PrototypeTestCase.id)
        )
    )
    return PrototypeMaterializationOut(
        id=item.id,
        prototype_id=item.prototype_id,
        prototype_version=item.prototype_version,
        task_ids=task_ids,
        test_cases=[test_case_out(test_case) for test_case in test_cases],
        created_at=item.created_at,
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
    if values.get("status") == "APPROVED" and prototype.status != "APPROVED":
        active = current_version(db, prototype)
        quality = json.loads(active.quality_json or "{}")
        if not quality.get("passed"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="原型质量门禁通过后才能批准",
            )
        open_comment = db.scalar(
            select(PrototypeReviewComment.id).where(
                PrototypeReviewComment.prototype_id == prototype.id,
                PrototypeReviewComment.prototype_version == prototype.active_version,
                PrototypeReviewComment.status == "OPEN",
            )
        )
        if open_comment:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="请先解决当前版本的待处理评审意见",
            )
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="原型版本不存在")
    if prototype.active_version != version:
        prototype.status = "DRAFT"
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


@router.get("/{prototype_id}/comments", response_model=list[PrototypeCommentOut])
def list_prototype_comments(
    prototype_id: int,
    version: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PrototypeCommentOut]:
    prototype = get_prototype_for_user(prototype_id, current_user, db)
    stmt = select(PrototypeReviewComment).where(
        PrototypeReviewComment.prototype_id == prototype.id
    )
    if version is not None:
        stmt = stmt.where(PrototypeReviewComment.prototype_version == version)
    items = list(db.scalars(stmt.order_by(PrototypeReviewComment.created_at.desc())))
    return [comment_out(db, item) for item in items]


@router.post(
    "/{prototype_id}/comments",
    response_model=PrototypeCommentOut,
    status_code=status.HTTP_201_CREATED,
)
def add_prototype_comment(
    prototype_id: int,
    payload: PrototypeCommentCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PrototypeCommentOut:
    prototype = get_prototype_for_user(prototype_id, current_user, db)
    version = current_version(db, prototype)
    specification = PrototypeSpecification.model_validate_json(version.specification_json)
    if payload.screen_id and not any(
        screen.id == payload.screen_id for screen in specification.screens
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="评审意见关联的页面必须存在于当前原型版本",
        )
    item = PrototypeReviewComment(
        prototype_id=prototype.id,
        prototype_version=prototype.active_version,
        screen_id=payload.screen_id,
        user_id=current_user.id,
        body=payload.body.strip(),
        status="OPEN",
    )
    db.add(item)
    db.flush()
    record_audit(
        db,
        "prototype.comment_create",
        current_user.id,
        prototype.project_id,
        "prototype_review_comment",
        item.id,
        {
            "prototype_id": prototype.id,
            "version": prototype.active_version,
            "screen_id": item.screen_id,
        },
        request,
    )
    db.commit()
    db.refresh(item)
    return comment_out(db, item)


@router.patch(
    "/{prototype_id}/comments/{comment_id}",
    response_model=PrototypeCommentOut,
)
def update_prototype_comment(
    prototype_id: int,
    comment_id: int,
    payload: PrototypeCommentUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PrototypeCommentOut:
    ensure_permission(current_user, "projects:write")
    prototype = get_prototype_for_user(prototype_id, current_user, db, write=True)
    item = db.get(PrototypeReviewComment, comment_id)
    if not item or item.prototype_id != prototype.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="原型评审意见不存在",
        )
    item.status = payload.status
    if payload.status == "RESOLVED":
        item.resolved_by_user_id = current_user.id
        item.resolved_at = datetime.now(timezone.utc)
    else:
        item.resolved_by_user_id = None
        item.resolved_at = None
    record_audit(
        db,
        "prototype.comment_update",
        current_user.id,
        prototype.project_id,
        "prototype_review_comment",
        item.id,
        {"status": item.status},
        request,
    )
    db.commit()
    db.refresh(item)
    return comment_out(db, item)


@router.post(
    "/{prototype_id}/materialize",
    response_model=PrototypeMaterializationOut,
    status_code=status.HTTP_201_CREATED,
)
def materialize_prototype(
    prototype_id: int,
    payload: PrototypeMaterializeRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PrototypeMaterializationOut:
    ensure_permission(current_user, "projects:write")
    prototype = get_prototype_for_user(prototype_id, current_user, db, write=True)
    existing_request = db.scalar(
        select(ProductPrototypeMaterialization).where(
            ProductPrototypeMaterialization.request_id == payload.request_id
        )
    )
    if existing_request:
        if existing_request.prototype_id != prototype.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="该交付请求 ID 已被使用",
            )
        return materialization_out(db, existing_request)
    existing_version = db.scalar(
        select(ProductPrototypeMaterialization).where(
            ProductPrototypeMaterialization.prototype_id == prototype.id,
            ProductPrototypeMaterialization.prototype_version == prototype.active_version,
        )
    )
    if existing_version:
        return materialization_out(db, existing_version)
    if prototype.status != "APPROVED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="请先批准当前原型版本再生成交付清单",
        )
    version = current_version(db, prototype)
    specification = PrototypeSpecification.model_validate_json(version.specification_json)
    task_blueprints = build_prototype_task_blueprints(specification)
    test_case_blueprints = build_prototype_test_case_blueprints(specification)
    for blueprint in task_blueprints:
        db.add(
            Task(
                project_id=prototype.project_id,
                title=blueprint["title"],
                description=blueprint["description"],
                priority=blueprint["priority"],
                source_prototype_id=prototype.id,
                source_prototype_version=prototype.active_version,
                source_screen_id=blueprint["screen_id"],
            )
        )
    for blueprint in test_case_blueprints:
        db.add(
            PrototypeTestCase(
                prototype_id=prototype.id,
                prototype_version=prototype.active_version,
                screen_id=blueprint["screen_id"],
                case_key=blueprint["case_key"],
                title=blueprint["title"],
                preconditions=blueprint["preconditions"],
                steps_json=json.dumps(blueprint["steps"], ensure_ascii=False),
                expected_result=blueprint["expected_result"],
                priority=blueprint["priority"],
                created_by_user_id=current_user.id,
            )
        )
    materialization = ProductPrototypeMaterialization(
        prototype_id=prototype.id,
        prototype_version=prototype.active_version,
        request_id=payload.request_id,
        task_count=len(task_blueprints),
        test_case_count=len(test_case_blueprints),
        created_by_user_id=current_user.id,
    )
    db.add(materialization)
    try:
        db.flush()
        record_audit(
            db,
            "prototype.materialize",
            current_user.id,
            prototype.project_id,
            "product_prototype_materialization",
            materialization.id,
            {
                "prototype_id": prototype.id,
                "version": prototype.active_version,
                "task_count": len(task_blueprints),
                "test_case_count": len(test_case_blueprints),
            },
            request,
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(
            select(ProductPrototypeMaterialization).where(
                ProductPrototypeMaterialization.prototype_id == prototype.id,
                ProductPrototypeMaterialization.prototype_version == prototype.active_version,
            )
        )
        if existing:
            return materialization_out(db, existing)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="原型交付数据与已有转换结果冲突",
        ) from exc
    db.refresh(materialization)
    return materialization_out(db, materialization)


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
