import asyncio
import hashlib
import json
import logging
from collections.abc import Mapping
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.metrics import PROTOTYPE_GENERATION_DURATION, PROTOTYPE_GENERATION_EVENTS
from app.models import (
    ProductPrototype,
    ProductPrototypeVersion,
    Project,
    ProjectMember,
    ProjectMemberRole,
    PrototypeGenerationEvent,
    PrototypeGenerationJob,
    PrototypeGenerationOperation,
    PrototypeGenerationStatus,
    User,
)
from app.prototypes.service import (
    PrototypeGenerationArtifact,
    freeze_prototype_generation_context,
    generate_prototype_artifact,
)


logger = logging.getLogger(__name__)
settings = get_settings()

ACTIVE_JOB_STATUSES = {
    PrototypeGenerationStatus.queued,
    PrototypeGenerationStatus.running,
    PrototypeGenerationStatus.cancelling,
}
TERMINAL_JOB_STATUSES = {
    PrototypeGenerationStatus.succeeded,
    PrototypeGenerationStatus.failed,
    PrototypeGenerationStatus.cancelled,
}
PERMANENT_ERROR_CODES = {
    "AUTHORIZATION_REVOKED",
    "PROTOTYPE_NOT_FOUND",
    "PROTOTYPE_VERSION_CONFLICT",
    "VERSION_CONFLICT",
}

STAGE_AGENT_ROLES = {
    "product_definition": "product_manager",
    "architecture": "architect",
    "architecture_repair": "architect",
    "deterministic_repair": "quality_gate",
    "quality_review": "test_engineer",
    "quality_review_repair": "test_engineer",
}


class PrototypeGenerationRequestConflict(RuntimeError):
    pass


class PrototypeGenerationActiveConflict(RuntimeError):
    def __init__(self, job_id: int) -> None:
        self.job_id = job_id
        super().__init__(f"Prototype already has active generation job {job_id}")


class PrototypeGenerationLeaseLost(RuntimeError):
    pass


class PrototypeGenerationCancelled(RuntimeError):
    pass


class PrototypeGenerationPermanentError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _observe_terminal(job: PrototypeGenerationJob, now: datetime) -> None:
    started = job.started_at or job.created_at
    if started:
        duration = max(0.0, (now - _as_aware(started)).total_seconds())
        PROTOTYPE_GENERATION_DURATION.labels(
            operation=job.operation.value,
            status=job.status.value,
        ).observe(duration)


def prototype_generation_retryable(job: PrototypeGenerationJob) -> bool:
    return bool(
        job.status == PrototypeGenerationStatus.failed
        and job.error_code not in PERMANENT_ERROR_CODES
    )


def prototype_generation_job_snapshot(job: PrototypeGenerationJob) -> dict[str, Any]:
    return {
        "job_id": job.id,
        "request_id": job.request_id,
        "operation": job.operation.value,
        "status": job.status.value,
        "project_id": job.project_id,
        "prototype_id": job.prototype_id,
        "title": job.title,
        "result_prototype_id": job.result_prototype_id,
        "result_version": job.result_version,
        "stage": job.stage,
        "stage_history": _json_loads(job.stage_history_json, []),
        "progress_percent": job.progress_percent,
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "latest_event_id": job.latest_event_id,
        "retryable": prototype_generation_retryable(job),
        "error_code": job.error_code,
        "error_message": job.error_message,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }


def request_payload_hash(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _json_loads(value: str, default: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return deepcopy_json(default)


def deepcopy_json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _trace_metadata(
    stage: str, snapshot: Mapping[str, Any]
) -> tuple[int | None, str | None]:
    for item in reversed(list(snapshot.get("trace") or [])):
        if item.get("stage") == stage:
            round_value = item.get("round")
            return (
                int(round_value) if isinstance(round_value, int) else None,
                str(item.get("role") or STAGE_AGENT_ROLES.get(stage) or "") or None,
            )
    round_value = snapshot.get("repair_rounds")
    return (
        int(round_value) if isinstance(round_value, int) and round_value > 0 else None,
        STAGE_AGENT_ROLES.get(stage),
    )


def _stage_history_entry(
    stage: str,
    status: str,
    message: str,
    *,
    snapshot: Mapping[str, Any] | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> dict[str, Any]:
    now = utc_now()
    round_value, agent_role = _trace_metadata(stage, snapshot or {})
    return {
        "stage": stage,
        "status": status,
        "round": round_value,
        "agent_role": agent_role,
        "message": message,
        "started_at": (started_at or now).isoformat(),
        "finished_at": finished_at.isoformat() if finished_at else None,
    }


def _append_stage_history(
    job: PrototypeGenerationJob, entry: Mapping[str, Any]
) -> None:
    history = list(_json_loads(job.stage_history_json, []))
    history.append(dict(entry))
    job.stage_history_json = json.dumps(history[-200:], ensure_ascii=False)


def record_prototype_generation_event(
    db: Session,
    job: PrototypeGenerationJob,
    event_type: str,
    message: str,
    *,
    stage: str | None = None,
    payload: Mapping[str, Any] | None = None,
) -> PrototypeGenerationEvent:
    event = PrototypeGenerationEvent(
        job_id=job.id,
        stage=stage if stage is not None else job.stage,
        event_type=event_type,
        message=message[:500],
        payload_json=json.dumps(dict(payload or {}), ensure_ascii=False),
    )
    db.add(event)
    db.flush()
    job.latest_event_id = event.id
    PROTOTYPE_GENERATION_EVENTS.labels(event_type=event_type).inc()
    return event


def enqueue_prototype_generation_job(
    db: Session,
    *,
    request_id: str,
    operation: PrototypeGenerationOperation | str,
    user_id: int,
    project_id: int,
    title: str,
    source_prompt: str,
    requirement_id: int | None = None,
    prototype_id: int | None = None,
    base_version: int | None = None,
    target_version: int = 1,
    request_payload: Mapping[str, Any] | None = None,
) -> tuple[PrototypeGenerationJob, bool]:
    operation = PrototypeGenerationOperation(operation)
    payload = dict(
        request_payload
        or {
            "request_id": request_id,
            "operation": operation.value,
            "user_id": user_id,
            "project_id": project_id,
            "requirement_id": requirement_id,
            "prototype_id": prototype_id,
            "base_version": base_version,
            "target_version": target_version,
            "title": title,
            "source_prompt": source_prompt,
        }
    )
    payload_hash = request_payload_hash(payload)
    existing = db.scalar(
        select(PrototypeGenerationJob).where(
            PrototypeGenerationJob.request_id == request_id
        )
    )
    if existing:
        if (
            existing.user_id != user_id
            or existing.project_id != project_id
            or existing.request_payload_hash != payload_hash
        ):
            raise PrototypeGenerationRequestConflict(
                "Prototype generation request ID is already in use"
            )
        return existing, False

    if operation == PrototypeGenerationOperation.regenerate:
        if prototype_id is None or base_version is None:
            raise ValueError("REGENERATE requires prototype_id and base_version")
        active = db.scalar(
            select(PrototypeGenerationJob)
            .where(
                PrototypeGenerationJob.prototype_id == prototype_id,
                PrototypeGenerationJob.status.in_(ACTIVE_JOB_STATUSES),
            )
            .with_for_update()
        )
        if active:
            raise PrototypeGenerationActiveConflict(active.id)
    elif prototype_id is not None:
        raise ValueError("CREATE must not reference a prototype before finalization")

    context = freeze_prototype_generation_context(
        db,
        user_id=user_id,
        project_id=project_id,
        prototype_title=title,
        requirement_id=requirement_id,
    )
    now = utc_now()
    job = PrototypeGenerationJob(
        request_id=request_id,
        request_payload_hash=payload_hash,
        operation=operation,
        status=PrototypeGenerationStatus.queued,
        project_id=project_id,
        requirement_id=requirement_id,
        user_id=user_id,
        prototype_id=prototype_id,
        base_version=base_version,
        target_version=target_version,
        title=title,
        source_prompt=source_prompt,
        requirement_snapshot_json=json.dumps(
            context["requirement"], ensure_ascii=False
        ),
        agent_snapshot_json=json.dumps(context["agents"], ensure_ascii=False),
        stage="queued",
        progress_percent=0,
        next_attempt_at=now,
        max_attempts=settings.prototype_generation_max_attempts,
    )
    db.add(job)
    db.flush()
    history = _stage_history_entry(
        "queued",
        "COMPLETED",
        "Prototype generation queued",
        started_at=now,
        finished_at=now,
    )
    _append_stage_history(job, history)
    record_prototype_generation_event(
        db,
        job,
        "QUEUED",
        "Prototype generation queued",
        stage="queued",
        payload={"progress_percent": 0, "stage_history": history},
    )
    return job, True


def _lock_owned_job(
    db: Session,
    job_id: int,
    lease_token: str,
) -> PrototypeGenerationJob:
    job = db.scalar(
        select(PrototypeGenerationJob)
        .where(PrototypeGenerationJob.id == job_id)
        .with_for_update()
    )
    if not job:
        raise PrototypeGenerationLeaseLost("Prototype generation job no longer exists")
    if job.lease_token != lease_token:
        raise PrototypeGenerationLeaseLost(
            "Prototype generation lease ownership changed"
        )
    return job


def _mark_claim_exhausted(db: Session, job: PrototypeGenerationJob) -> None:
    now = utc_now()
    if job.status == PrototypeGenerationStatus.cancelling:
        job.status = PrototypeGenerationStatus.cancelled
        job.stage = "cancelled"
        job.error_code = "CANCELLED"
        job.error_message = "Prototype generation cancelled"
        status = "CANCELLED"
        event_type = "CANCELLED"
        message = "Prototype generation cancelled after lease recovery"
    else:
        job.status = PrototypeGenerationStatus.failed
        job.stage = "failed"
        job.error_code = "ATTEMPTS_EXHAUSTED"
        job.error_message = (
            "Prototype generation attempts exhausted during lease recovery"
        )
        status = "FAILED"
        event_type = "FAILED"
        message = job.error_message
    job.locked_at = None
    job.lease_token = None
    job.finished_at = now
    history = _stage_history_entry(
        job.stage,
        status,
        message,
        started_at=job.started_at,
        finished_at=now,
    )
    _append_stage_history(job, history)
    record_prototype_generation_event(
        db,
        job,
        event_type,
        message,
        payload={"progress_percent": job.progress_percent, "stage_history": history},
    )
    record_audit(
        db,
        "prototype.generation_cancelled" if job.status == PrototypeGenerationStatus.cancelled else "prototype.generation_failed",
        job.user_id,
        job.project_id,
        "prototype_generation_job",
        job.id,
        {"operation": job.operation.value, "error_code": job.error_code, "attempt_count": job.attempt_count},
    )
    _observe_terminal(job, now)


def claim_prototype_generation_job(db: Session) -> int | None:
    now = utc_now()
    cutoff = now - timedelta(seconds=settings.prototype_generation_lease_seconds)
    due = or_(
        PrototypeGenerationJob.next_attempt_at.is_(None),
        PrototypeGenerationJob.next_attempt_at <= now,
    )
    lease_available = or_(
        PrototypeGenerationJob.locked_at.is_(None),
        PrototypeGenerationJob.locked_at <= cutoff,
    )
    job = db.scalar(
        select(PrototypeGenerationJob)
        .where(
            or_(
                (PrototypeGenerationJob.status == PrototypeGenerationStatus.queued)
                & due,
                (
                    PrototypeGenerationJob.status.in_(
                        {
                            PrototypeGenerationStatus.running,
                            PrototypeGenerationStatus.cancelling,
                        }
                    )
                )
                & lease_available,
            )
        )
        .order_by(
            PrototypeGenerationJob.next_attempt_at,
            PrototypeGenerationJob.created_at,
            PrototypeGenerationJob.id,
        )
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if not job:
        return None
    recovered = job.status in {
        PrototypeGenerationStatus.running,
        PrototypeGenerationStatus.cancelling,
    }
    if job.attempt_count >= job.max_attempts:
        _mark_claim_exhausted(db, job)
        db.commit()
        return job.id

    if job.status != PrototypeGenerationStatus.cancelling:
        job.status = PrototypeGenerationStatus.running
    job.locked_at = now
    job.lease_token = str(uuid4())
    job.started_at = job.started_at or now
    job.attempt_count += 1
    job.next_attempt_at = None
    job.error_code = ""
    job.error_message = ""
    record_prototype_generation_event(
        db,
        job,
        "RECOVERED" if recovered else "STARTED",
        "Recovered stale prototype generation lease"
        if recovered
        else "Prototype generation worker started",
        payload={"attempt_count": job.attempt_count},
    )
    if recovered:
        record_audit(
            db,
            "prototype.generation_recovered",
            job.user_id,
            job.project_id,
            "prototype_generation_job",
            job.id,
            {"operation": job.operation.value, "attempt_count": job.attempt_count},
        )
    db.commit()
    return job.id


def _claim_specific_job(db: Session, job_id: int) -> bool:
    job = db.scalar(
        select(PrototypeGenerationJob)
        .where(PrototypeGenerationJob.id == job_id)
        .with_for_update()
    )
    if not job or job.status != PrototypeGenerationStatus.queued:
        return False
    if job.attempt_count >= job.max_attempts:
        _mark_claim_exhausted(db, job)
        db.commit()
        return False
    now = utc_now()
    job.status = PrototypeGenerationStatus.running
    job.locked_at = now
    job.lease_token = str(uuid4())
    job.started_at = job.started_at or now
    job.attempt_count += 1
    job.next_attempt_at = None
    job.error_code = ""
    job.error_message = ""
    record_prototype_generation_event(
        db,
        job,
        "STARTED",
        "Prototype generation worker started",
        payload={"attempt_count": job.attempt_count},
    )
    db.commit()
    return True


class PrototypeGenerationLeaseHeartbeat:
    def __init__(self, bind: Engine, job_id: int, lease_token: str) -> None:
        self.bind = bind
        self.job_id = job_id
        self.lease_token = lease_token
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        self.lost = False

    async def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(
            self._run(), name=f"prototype-generation-lease-{self.job_id}"
        )

    async def stop(self) -> None:
        if not self._task:
            return
        self._stop.set()
        await self._task
        self._task = None

    async def _run(self) -> None:
        interval = max(1.0, settings.prototype_generation_lease_seconds / 3)
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
                return
            except TimeoutError:
                pass
            try:
                with Session(self.bind) as heartbeat_db:
                    result = heartbeat_db.execute(
                        update(PrototypeGenerationJob)
                        .where(
                            PrototypeGenerationJob.id == self.job_id,
                            PrototypeGenerationJob.lease_token == self.lease_token,
                            PrototypeGenerationJob.status.in_(
                                {
                                    PrototypeGenerationStatus.running,
                                    PrototypeGenerationStatus.cancelling,
                                }
                            ),
                        )
                        .values(locked_at=utc_now())
                    )
                    heartbeat_db.commit()
                if result.rowcount != 1:
                    self.lost = True
                    return
            except Exception:
                logger.exception(
                    "Prototype generation lease heartbeat failed: job_id=%s",
                    self.job_id,
                )


def checkpoint_prototype_generation_job(
    job_id: int,
    lease_token: str,
    stage: str,
    progress_percent: int,
    snapshot: Mapping[str, Any],
    *,
    message: str | None = None,
) -> PrototypeGenerationJob:
    with SessionLocal() as db:
        job = _lock_owned_job(db, job_id, lease_token)
        if job.status == PrototypeGenerationStatus.cancelling:
            raise PrototypeGenerationCancelled(
                "Prototype generation cancellation requested"
            )
        if job.status != PrototypeGenerationStatus.running:
            raise PrototypeGenerationLeaseLost(
                "Prototype generation job is no longer running"
            )
        now = utc_now()
        job.stage = stage
        job.progress_percent = max(job.progress_percent, min(100, progress_percent))
        job.state_json = json.dumps(dict(snapshot), ensure_ascii=False)
        job.locked_at = now
        event_message = message or f"Completed prototype generation stage {stage}"
        history = _stage_history_entry(
            stage,
            "COMPLETED",
            event_message,
            snapshot=snapshot,
            finished_at=now,
        )
        _append_stage_history(job, history)
        record_prototype_generation_event(
            db,
            job,
            "STAGE_COMPLETED",
            event_message,
            stage=stage,
            payload={
                "progress_percent": job.progress_percent,
                "stage_history": history,
            },
        )
        db.commit()
        db.refresh(job)
        return job


def _cancel_owned_job(job_id: int, lease_token: str, message: str) -> None:
    with SessionLocal() as db:
        job = _lock_owned_job(db, job_id, lease_token)
        if job.status in TERMINAL_JOB_STATUSES:
            return
        now = utc_now()
        job.status = PrototypeGenerationStatus.cancelled
        job.stage = "cancelled"
        job.locked_at = None
        job.lease_token = None
        job.finished_at = now
        job.error_code = "CANCELLED"
        job.error_message = message[:2000]
        history = _stage_history_entry(
            "cancelled",
            "CANCELLED",
            message,
            started_at=job.started_at,
            finished_at=now,
        )
        _append_stage_history(job, history)
        record_prototype_generation_event(
            db,
            job,
            "CANCELLED",
            message,
            stage="cancelled",
            payload={
                "progress_percent": job.progress_percent,
                "stage_history": history,
            },
        )
        record_audit(
            db,
            "prototype.generation_cancelled",
            job.user_id,
            job.project_id,
            "prototype_generation_job",
            job.id,
            {"operation": job.operation.value, "attempt_count": job.attempt_count},
        )
        _observe_terminal(job, now)
        db.commit()


def _fail_or_retry_owned_job(
    job_id: int,
    lease_token: str,
    *,
    error_code: str,
    error_message: str,
    retryable: bool,
) -> None:
    with SessionLocal() as db:
        job = _lock_owned_job(db, job_id, lease_token)
        if job.status == PrototypeGenerationStatus.cancelling:
            db.rollback()
            _cancel_owned_job(job_id, lease_token, "Prototype generation cancelled")
            return
        if job.status in TERMINAL_JOB_STATUSES:
            return
        now = utc_now()
        failed_stage = job.stage
        failed_history = _stage_history_entry(
            failed_stage,
            "FAILED",
            error_message,
            started_at=job.started_at,
            finished_at=now,
        )
        _append_stage_history(job, failed_history)
        job.error_code = error_code[:100]
        job.error_message = error_message[:2000]
        job.locked_at = None
        job.lease_token = None
        if retryable and job.attempt_count < job.max_attempts:
            delay = min(
                settings.prototype_generation_retry_max_seconds,
                settings.prototype_generation_retry_base_seconds
                * (2 ** max(0, job.attempt_count - 1)),
            )
            job.status = PrototypeGenerationStatus.queued
            job.next_attempt_at = now + timedelta(seconds=delay)
            record_prototype_generation_event(
                db,
                job,
                "RETRY_SCHEDULED",
                "Prototype generation retry scheduled",
                stage=failed_stage,
                payload={
                    "delay_seconds": delay,
                    "error_code": job.error_code,
                    "progress_percent": job.progress_percent,
                    "stage_history": failed_history,
                },
            )
            record_audit(
                db,
                "prototype.generation_retry_scheduled",
                job.user_id,
                job.project_id,
                "prototype_generation_job",
                job.id,
                {"operation": job.operation.value, "error_code": job.error_code, "attempt_count": job.attempt_count},
            )
        else:
            job.status = PrototypeGenerationStatus.failed
            job.stage = "failed"
            job.finished_at = now
            terminal_history = _stage_history_entry(
                "failed",
                "FAILED",
                error_message,
                started_at=job.started_at,
                finished_at=now,
            )
            _append_stage_history(job, terminal_history)
            record_prototype_generation_event(
                db,
                job,
                "FAILED",
                "Prototype generation failed",
                stage="failed",
                payload={
                    "error_code": job.error_code,
                    "progress_percent": job.progress_percent,
                    "stage_history": terminal_history,
                },
            )
            record_audit(
                db,
                "prototype.generation_failed",
                job.user_id,
                job.project_id,
                "prototype_generation_job",
                job.id,
                {"operation": job.operation.value, "error_code": job.error_code, "attempt_count": job.attempt_count},
            )
            _observe_terminal(job, now)
        db.commit()


def _validate_publish_authorization(
    db: Session,
    job: PrototypeGenerationJob,
) -> None:
    user = db.scalar(select(User).where(User.id == job.user_id).with_for_update())
    project = db.scalar(select(Project).where(Project.id == job.project_id).with_for_update())
    if not user or not user.is_active or not project:
        raise PrototypeGenerationPermanentError(
            "AUTHORIZATION_REVOKED",
            "Prototype generation owner or project is no longer available",
        )
    if project.owner_id == user.id:
        return
    membership = db.scalar(
        select(ProjectMember)
        .where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == user.id,
        )
        .with_for_update()
    )
    if not membership or membership.role == ProjectMemberRole.viewer:
        raise PrototypeGenerationPermanentError(
            "AUTHORIZATION_REVOKED",
            "Project write access was revoked while prototype generation was running",
        )


def finalize_prototype_generation_job(
    job_id: int,
    lease_token: str,
    artifact: PrototypeGenerationArtifact,
) -> PrototypeGenerationJob:
    with SessionLocal() as db:
        job = _lock_owned_job(db, job_id, lease_token)
        if job.status == PrototypeGenerationStatus.cancelling:
            raise PrototypeGenerationCancelled(
                "Prototype generation cancellation requested"
            )
        if job.status != PrototypeGenerationStatus.running:
            raise PrototypeGenerationLeaseLost(
                "Prototype generation job is no longer running"
            )
        _validate_publish_authorization(db, job)

        if job.operation == PrototypeGenerationOperation.create:
            prototype = ProductPrototype(
                project_id=job.project_id,
                requirement_id=job.requirement_id,
                created_by_user_id=job.user_id,
                title=job.title,
                status="DRAFT",
                active_version=job.target_version,
            )
            db.add(prototype)
            db.flush()
            job.prototype_id = prototype.id
        else:
            prototype = db.scalar(
                select(ProductPrototype)
                .where(ProductPrototype.id == job.prototype_id)
                .with_for_update()
            )
            if not prototype or prototype.project_id != job.project_id:
                raise PrototypeGenerationPermanentError(
                    "PROTOTYPE_NOT_FOUND",
                    "Prototype was removed before generation completed",
                )
            if prototype.active_version != job.base_version:
                raise PrototypeGenerationPermanentError(
                    "PROTOTYPE_VERSION_CONFLICT",
                    "Prototype active version changed while generation was running",
                )

        version = ProductPrototypeVersion(
            prototype_id=prototype.id,
            version=job.target_version,
            source_prompt=job.source_prompt,
            specification_json=artifact.specification.model_dump_json(),
            agent_trace_json=json.dumps(artifact.agent_trace, ensure_ascii=False),
            quality_json=json.dumps(artifact.quality, ensure_ascii=False),
            generation_mode=artifact.generation_mode,
            created_by_user_id=job.user_id,
        )
        db.add(version)
        db.flush()
        prototype.active_version = job.target_version
        prototype.summary = artifact.specification.summary
        prototype.status = "DRAFT"

        now = utc_now()
        job.status = PrototypeGenerationStatus.succeeded
        job.stage = "completed"
        job.progress_percent = 100
        job.state_json = json.dumps(artifact.checkpoint(), ensure_ascii=False)
        job.result_prototype_id = prototype.id
        job.result_version = version.version
        job.result_version_id = version.id
        job.locked_at = None
        job.lease_token = None
        job.next_attempt_at = None
        job.error_code = ""
        job.error_message = ""
        job.finished_at = now
        history = _stage_history_entry(
            "completed",
            "COMPLETED",
            "Prototype generation completed",
            started_at=job.started_at,
            finished_at=now,
        )
        _append_stage_history(job, history)
        record_prototype_generation_event(
            db,
            job,
            "SUCCEEDED",
            "Prototype generation completed",
            stage="completed",
            payload={
                "progress_percent": 100,
                "result_prototype_id": prototype.id,
                "result_version": version.version,
                "stage_history": history,
            },
        )
        record_audit(
            db,
            "prototype.generation_succeeded",
            job.user_id,
            job.project_id,
            "prototype_generation_job",
            job.id,
            {
                "operation": job.operation.value,
                "result_prototype_id": prototype.id,
                "result_version": version.version,
                "attempt_count": job.attempt_count,
            },
        )
        _observe_terminal(job, now)
        db.commit()
        db.refresh(job)
        return job


def cancel_prototype_generation_job(
    db: Session,
    job_id: int,
) -> PrototypeGenerationJob:
    job = db.scalar(
        select(PrototypeGenerationJob)
        .where(PrototypeGenerationJob.id == job_id)
        .with_for_update()
    )
    if not job:
        raise LookupError("Prototype generation job not found")
    if job.status in TERMINAL_JOB_STATUSES:
        return job
    now = utc_now()
    job.cancel_requested_at = job.cancel_requested_at or now
    if job.status == PrototypeGenerationStatus.queued:
        job.status = PrototypeGenerationStatus.cancelled
        job.stage = "cancelled"
        job.finished_at = now
        job.next_attempt_at = None
        job.error_code = "CANCELLED"
        job.error_message = "Prototype generation cancelled before execution"
        history = _stage_history_entry(
            "cancelled",
            "CANCELLED",
            job.error_message,
            started_at=now,
            finished_at=now,
        )
        _append_stage_history(job, history)
        record_prototype_generation_event(
            db,
            job,
            "CANCELLED",
            job.error_message,
            stage="cancelled",
            payload={
                "progress_percent": job.progress_percent,
                "stage_history": history,
            },
        )
        record_audit(
            db,
            "prototype.generation_cancelled",
            job.user_id,
            job.project_id,
            "prototype_generation_job",
            job.id,
            {"operation": job.operation.value, "attempt_count": job.attempt_count},
        )
        _observe_terminal(job, now)
    else:
        job.status = PrototypeGenerationStatus.cancelling
        record_prototype_generation_event(
            db,
            job,
            "CANCELLING",
            "Prototype generation cancellation requested",
            payload={"progress_percent": job.progress_percent},
        )
        record_audit(
            db,
            "prototype.generation_cancelling",
            job.user_id,
            job.project_id,
            "prototype_generation_job",
            job.id,
            {"operation": job.operation.value, "attempt_count": job.attempt_count},
        )
    return job


def retry_prototype_generation_job(
    db: Session,
    job_id: int,
) -> PrototypeGenerationJob:
    job = db.scalar(
        select(PrototypeGenerationJob)
        .where(PrototypeGenerationJob.id == job_id)
        .with_for_update()
    )
    if not job:
        raise LookupError("Prototype generation job not found")
    if job.status != PrototypeGenerationStatus.failed:
        raise ValueError("Only failed prototype generation jobs can be retried")
    now = utc_now()
    job.status = PrototypeGenerationStatus.queued
    job.stage = "queued"
    job.attempt_count = 0
    job.max_attempts = settings.prototype_generation_max_attempts
    job.next_attempt_at = now
    job.locked_at = None
    job.lease_token = None
    job.error_code = ""
    job.error_message = ""
    job.cancel_requested_at = None
    job.finished_at = None
    history = _stage_history_entry(
        "queued",
        "COMPLETED",
        "Prototype generation manually queued for retry",
        started_at=now,
        finished_at=now,
    )
    _append_stage_history(job, history)
    record_prototype_generation_event(
        db,
        job,
        "QUEUED",
        "Prototype generation manually queued for retry",
        stage="queued",
        payload={"progress_percent": job.progress_percent, "stage_history": history},
    )
    return job


def _get_job(job_id: int) -> PrototypeGenerationJob:
    with SessionLocal() as db:
        job = db.get(PrototypeGenerationJob, job_id)
        if not job:
            raise LookupError("Prototype generation job not found")
        db.expunge(job)
        return job


def _get_job_after_worker_stop(job_id: int) -> PrototypeGenerationJob:
    try:
        return _get_job(job_id)
    except LookupError as exc:
        raise PrototypeGenerationLeaseLost(
            "Prototype generation job was removed while the worker was running"
        ) from exc


async def process_prototype_generation_job(
    job_id: int,
    *,
    claimed: bool = False,
) -> PrototypeGenerationJob:
    if not claimed:
        with SessionLocal() as claim_db:
            if not _claim_specific_job(claim_db, job_id):
                return _get_job(job_id)

    job = _get_job(job_id)
    if job.status in TERMINAL_JOB_STATUSES:
        return job
    if not job.lease_token:
        raise PrototypeGenerationLeaseLost("Claimed job does not have a lease token")
    lease_token = job.lease_token
    if job.status == PrototypeGenerationStatus.cancelling:
        _cancel_owned_job(job_id, lease_token, "Prototype generation cancelled")
        return _get_job(job_id)

    context = {
        "user_id": job.user_id,
        "project_id": job.project_id,
        "prototype_title": job.title,
        "requirement": _json_loads(job.requirement_snapshot_json, None),
        "agents": _json_loads(job.agent_snapshot_json, {}),
    }
    resume_state = _json_loads(job.state_json, {})
    heartbeat = PrototypeGenerationLeaseHeartbeat(
        SessionLocal.kw["bind"], job_id, lease_token
    )
    await heartbeat.start()

    async def progress(
        stage: str,
        progress_percent: int,
        snapshot: dict[str, Any],
    ) -> None:
        if heartbeat.lost:
            raise PrototypeGenerationLeaseLost(
                "Prototype generation lease ownership changed during execution"
            )
        checkpoint_prototype_generation_job(
            job_id,
            lease_token,
            stage,
            progress_percent,
            snapshot,
        )

    try:
        artifact = await generate_prototype_artifact(
            context,
            job.source_prompt,
            progress_callback=progress,
            resume_state=resume_state,
        )
        if heartbeat.lost:
            raise PrototypeGenerationLeaseLost(
                "Prototype generation lease ownership changed before finalization"
            )
        checkpoint_prototype_generation_job(
            job_id,
            lease_token,
            "persisting",
            95,
            artifact.checkpoint(),
            message="Persisting generated prototype",
        )
        return finalize_prototype_generation_job(job_id, lease_token, artifact)
    except PrototypeGenerationLeaseLost:
        logger.warning("Stopped stale prototype generation worker: job_id=%s", job_id)
        return _get_job_after_worker_stop(job_id)
    except PrototypeGenerationCancelled:
        with suppress(PrototypeGenerationLeaseLost):
            _cancel_owned_job(job_id, lease_token, "Prototype generation cancelled")
        return _get_job_after_worker_stop(job_id)
    except PrototypeGenerationPermanentError as exc:
        with suppress(PrototypeGenerationLeaseLost):
            _fail_or_retry_owned_job(
                job_id,
                lease_token,
                error_code=exc.code,
                error_message=str(exc),
                retryable=False,
            )
        return _get_job_after_worker_stop(job_id)
    except Exception as exc:
        with suppress(PrototypeGenerationLeaseLost):
            _fail_or_retry_owned_job(
                job_id,
                lease_token,
                error_code=type(exc).__name__.upper()[:100],
                error_message=str(exc) or "Prototype generation failed",
                retryable=True,
            )
        logger.exception("Prototype generation job %s failed", job_id)
        return _get_job_after_worker_stop(job_id)
    finally:
        with suppress(Exception):
            await heartbeat.stop()


class PrototypeGenerationDispatcher:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if not settings.prototype_generation_worker_enabled or self._task:
            return
        self._stop.clear()
        self._task = asyncio.create_task(
            self._run(), name="prototype-generation-dispatcher"
        )
        logger.info("Prototype generation dispatcher started")

    async def stop(self) -> None:
        if not self._task:
            return
        self._stop.set()
        try:
            await asyncio.wait_for(
                asyncio.shield(self._task),
                timeout=settings.prototype_generation_shutdown_grace_seconds,
            )
        except TimeoutError:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                processed = await self.dispatch_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                processed = False
                logger.exception("Prototype generation dispatcher iteration failed")
            if processed:
                continue
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=settings.prototype_generation_poll_seconds,
                )
            except TimeoutError:
                pass

    async def dispatch_once(self) -> bool:
        with SessionLocal() as db:
            job_id = claim_prototype_generation_job(db)
        if job_id is None:
            return False
        await process_prototype_generation_job(job_id, claimed=True)
        return True


prototype_generation_dispatcher = PrototypeGenerationDispatcher()
