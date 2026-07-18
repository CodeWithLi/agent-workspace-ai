import asyncio
import json
from collections.abc import Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.routes.projects import accessible_project_ids, get_project_for_user
from app.api.routes.prototypes import current_version, get_prototype_for_user
from app.core.audit import record_audit
from app.core.database import SessionLocal, get_db
from app.models import (
    Project,
    ProductPrototypeVersion,
    PrototypeGenerationEvent,
    PrototypeGenerationJob,
    PrototypeGenerationOperation,
    PrototypeGenerationStatus,
    Requirement,
    User,
)
from app.prototypes.schemas import (
    PrototypeGenerationCreateRequest,
    PrototypeGenerationJobOut,
    PrototypeGenerationRegenerateRequest,
    PrototypeGenerationStageOut,
)
from app.services.prototype_generations import (
    ACTIVE_JOB_STATUSES,
    TERMINAL_JOB_STATUSES,
    PrototypeGenerationActiveConflict,
    PrototypeGenerationRequestConflict,
    cancel_prototype_generation_job,
    enqueue_prototype_generation_job,
    prototype_generation_retryable,
    retry_prototype_generation_job,
)


router = APIRouter()


def _enum_value(value: object) -> str:
    return str(getattr(value, "value", value))


def prototype_generation_job_out(job: PrototypeGenerationJob) -> PrototypeGenerationJobOut:
    try:
        raw_history = json.loads(job.stage_history_json or "[]")
    except json.JSONDecodeError:
        raw_history = []
    history: list[PrototypeGenerationStageOut] = []
    for raw in raw_history if isinstance(raw_history, list) else []:
        if not isinstance(raw, dict):
            continue
        history.append(
            PrototypeGenerationStageOut(
                stage=str(raw.get("stage") or "queued"),
                status=str(raw.get("status") or "PENDING"),
                round=max(0, int(raw.get("round") or 0)),
                agent_role=str(raw["agent_role"]) if raw.get("agent_role") else None,
                message=str(raw.get("message") or ""),
                started_at=raw.get("started_at"),
                finished_at=raw.get("finished_at"),
            )
        )
    operation = _enum_value(job.operation)
    job_status = _enum_value(job.status)
    return PrototypeGenerationJobOut(
        job_id=job.id,
        operation=operation,
        project_id=job.project_id,
        title=job.title,
        prototype_id=job.prototype_id,
        base_version=job.base_version,
        target_version=job.target_version,
        status=job_status,
        stage=job.stage,
        stage_history=history,
        progress_percent=job.progress_percent,
        attempt_count=job.attempt_count,
        max_attempts=job.max_attempts,
        latest_event_id=job.latest_event_id or 0,
        retryable=prototype_generation_retryable(job),
        error_code=job.error_code or None,
        error_message=job.error_message or None,
        result_prototype_id=job.result_prototype_id,
        result_version=job.result_version,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        updated_at=job.updated_at,
    )


def get_generation_job_for_user(
    job_id: int,
    current_user: User,
    db: Session,
    *,
    write: bool = False,
) -> PrototypeGenerationJob:
    job = db.get(PrototypeGenerationJob, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation job not found")
    get_project_for_user(job.project_id, current_user, db, write=write)
    return job


def _enqueue_with_conflict_recovery(
    db: Session,
    enqueue: Callable[[], tuple[PrototypeGenerationJob, bool]],
) -> tuple[PrototypeGenerationJob, bool]:
    try:
        try:
            return enqueue()
        except IntegrityError:
            db.rollback()
            return enqueue()
    except PrototypeGenerationRequestConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except PrototypeGenerationActiveConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Prototype already has active generation job {exc.job_id}",
        ) from exc


@router.post(
    "/generation-jobs",
    response_model=PrototypeGenerationJobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_prototype_generation_job(
    payload: PrototypeGenerationCreateRequest,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PrototypeGenerationJobOut:
    get_project_for_user(payload.project_id, current_user, db, write=True)
    if payload.requirement_id is not None:
        requirement = db.get(Requirement, payload.requirement_id)
        if not requirement or requirement.project_id != payload.project_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Requirement must belong to the selected project",
            )
    stable_payload = {
        "operation": PrototypeGenerationOperation.create.value,
        "project_id": payload.project_id,
        "requirement_id": payload.requirement_id,
        "title": payload.title.strip(),
        "prompt": payload.prompt.strip(),
    }

    def enqueue() -> tuple[PrototypeGenerationJob, bool]:
        return enqueue_prototype_generation_job(
            db,
            request_id=payload.request_id,
            operation=PrototypeGenerationOperation.create,
            user_id=current_user.id,
            project_id=payload.project_id,
            requirement_id=payload.requirement_id,
            title=payload.title.strip(),
            source_prompt=payload.prompt.strip(),
            request_payload=stable_payload,
        )

    job, created = _enqueue_with_conflict_recovery(db, enqueue)
    if created:
        record_audit(
            db,
            "prototype.generation_queued",
            current_user.id,
            job.project_id,
            "prototype_generation_job",
            job.id,
            {"operation": job.operation.value, "request_id": job.request_id},
            request,
        )
    db.commit()
    db.refresh(job)
    response.headers["Location"] = str(
        request.url_for("get_prototype_generation_job", job_id=job.id)
    )
    return prototype_generation_job_out(job)


@router.post(
    "/{prototype_id}/generation-jobs",
    response_model=PrototypeGenerationJobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_prototype_regeneration_job(
    prototype_id: int,
    payload: PrototypeGenerationRegenerateRequest,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PrototypeGenerationJobOut:
    prototype = get_prototype_for_user(prototype_id, current_user, db, write=True)
    if prototype.status == "ARCHIVED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Archived prototypes cannot be regenerated",
        )
    previous = current_version(db, prototype)
    target_version = int(
        db.scalar(
            select(func.coalesce(func.max(ProductPrototypeVersion.version), 0)).where(
                ProductPrototypeVersion.prototype_id == prototype.id
            )
        )
    ) + 1
    feedback = payload.feedback.strip()
    source_prompt = previous.source_prompt
    if feedback:
        source_prompt = f"{source_prompt}\n\n本轮修改意见：{feedback}"
    stable_payload = {
        "operation": PrototypeGenerationOperation.regenerate.value,
        "project_id": prototype.project_id,
        "prototype_id": prototype.id,
        "feedback": feedback,
    }

    def enqueue() -> tuple[PrototypeGenerationJob, bool]:
        return enqueue_prototype_generation_job(
            db,
            request_id=payload.request_id,
            operation=PrototypeGenerationOperation.regenerate,
            user_id=current_user.id,
            project_id=prototype.project_id,
            requirement_id=prototype.requirement_id,
            prototype_id=prototype.id,
            base_version=prototype.active_version,
            target_version=target_version,
            title=prototype.title,
            source_prompt=source_prompt,
            request_payload=stable_payload,
        )

    job, created = _enqueue_with_conflict_recovery(db, enqueue)
    if created:
        record_audit(
            db,
            "prototype.regeneration_queued",
            current_user.id,
            job.project_id,
            "prototype_generation_job",
            job.id,
            {
                "operation": job.operation.value,
                "prototype_id": prototype.id,
                "base_version": job.base_version,
                "target_version": job.target_version,
                "request_id": job.request_id,
            },
            request,
        )
    db.commit()
    db.refresh(job)
    response.headers["Location"] = str(
        request.url_for("get_prototype_generation_job", job_id=job.id)
    )
    return prototype_generation_job_out(job)


@router.get("/generation-jobs", response_model=list[PrototypeGenerationJobOut])
def list_prototype_generation_jobs(
    active: bool = False,
    project_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PrototypeGenerationJobOut]:
    project_ids = accessible_project_ids(current_user, db)
    if not project_ids:
        return []
    stmt = select(PrototypeGenerationJob).where(
        PrototypeGenerationJob.project_id.in_(project_ids),
        PrototypeGenerationJob.user_id == current_user.id,
    )
    if project_id is not None:
        get_project_for_user(project_id, current_user, db)
        stmt = stmt.where(PrototypeGenerationJob.project_id == project_id)
    if active:
        stmt = stmt.where(PrototypeGenerationJob.status.in_(ACTIVE_JOB_STATUSES))
    jobs = list(
        db.scalars(stmt.order_by(PrototypeGenerationJob.created_at.desc()).limit(100))
    )
    return [prototype_generation_job_out(job) for job in jobs]


@router.get("/generation-jobs/{job_id}", response_model=PrototypeGenerationJobOut)
def get_prototype_generation_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PrototypeGenerationJobOut:
    return prototype_generation_job_out(get_generation_job_for_user(job_id, current_user, db))


@router.get("/generation-jobs/{job_id}/events")
async def stream_prototype_generation_events(
    job_id: int,
    last_event_id: int = 0,
    header_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    get_generation_job_for_user(job_id, current_user, db)
    try:
        cursor = max(last_event_id, int(header_event_id or 0))
    except ValueError:
        cursor = last_event_id
    user_id = current_user.id

    async def event_stream():
        nonlocal cursor
        idle_polls = 0
        yield "retry: 1500\n\n"
        while True:
            with SessionLocal() as event_db:
                job = event_db.get(PrototypeGenerationJob, job_id)
                event_user = event_db.get(User, user_id)
                project = event_db.get(Project, job.project_id) if job else None
                if not job or not event_user or not event_user.is_active or not project:
                    return
                try:
                    get_project_for_user(project.id, event_user, event_db)
                except HTTPException:
                    return
                events = list(
                    event_db.scalars(
                        select(PrototypeGenerationEvent)
                        .where(
                            PrototypeGenerationEvent.job_id == job_id,
                            PrototypeGenerationEvent.id > cursor,
                        )
                        .order_by(PrototypeGenerationEvent.id)
                        .limit(100)
                    )
                )
                terminal = job.status in TERMINAL_JOB_STATUSES
                if events:
                    snapshot = prototype_generation_job_out(job).model_dump(mode="json")
                    for event in events:
                        cursor = event.id
                        event_name = f"job_{event.event_type.lower()}"
                        yield (
                            f"id: {event.id}\n"
                            f"event: {event_name}\n"
                            f"data: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
                        )
                    idle_polls = 0
                elif terminal:
                    return
                else:
                    idle_polls += 1
                    if idle_polls >= 15:
                        yield ": heartbeat\n\n"
                        idle_polls = 0
            await asyncio.sleep(1)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/generation-jobs/{job_id}/cancel",
    response_model=PrototypeGenerationJobOut,
)
def cancel_generation_job(
    job_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PrototypeGenerationJobOut:
    job = get_generation_job_for_user(job_id, current_user, db, write=True)
    previous_status = job.status
    job = cancel_prototype_generation_job(db, job.id)
    if job.status != previous_status:
        record_audit(
            db,
            "prototype.generation_cancel",
            current_user.id,
            job.project_id,
            "prototype_generation_job",
            job.id,
            {"previous_status": _enum_value(previous_status)},
            request,
        )
    db.commit()
    db.refresh(job)
    return prototype_generation_job_out(job)


@router.post(
    "/generation-jobs/{job_id}/retry",
    response_model=PrototypeGenerationJobOut,
)
def retry_generation_job(
    job_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PrototypeGenerationJobOut:
    job = get_generation_job_for_user(job_id, current_user, db, write=True)
    if job.status == PrototypeGenerationStatus.failed and not prototype_generation_retryable(job):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This generation failure cannot be retried without creating a new request",
        )
    try:
        job = retry_prototype_generation_job(db, job.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    record_audit(
        db,
        "prototype.generation_retry",
        current_user.id,
        job.project_id,
        "prototype_generation_job",
        job.id,
        {"request_id": job.request_id},
        request,
    )
    db.commit()
    db.refresh(job)
    return prototype_generation_job_out(job)
