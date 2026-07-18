import asyncio
from datetime import timedelta

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request

from app.agent.service import ensure_default_agents
from app.api.routes import prototype_jobs as prototype_job_routes
from app.api.routes.prototype_jobs import (
    cancel_generation_job,
    create_prototype_generation_job,
    get_prototype_generation_job,
    retry_generation_job,
    stream_prototype_generation_events,
)
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
    Requirement,
    User,
)
from app.prototypes.schemas import PrototypeGenerationCreateRequest
from app.prototypes.service import PrototypeGenerationArtifact, build_fallback_spec
from app.services import prototype_generations as generation_service
from app.services.prototype_generations import (
    PrototypeGenerationLeaseHeartbeat,
    PrototypeGenerationLeaseLost,
    PrototypeGenerationPermanentError,
    PrototypeGenerationRequestConflict,
    cancel_prototype_generation_job,
    checkpoint_prototype_generation_job,
    claim_prototype_generation_job,
    enqueue_prototype_generation_job,
    finalize_prototype_generation_job,
    process_prototype_generation_job,
    retry_prototype_generation_job,
    utc_now,
)


def generation_context(
    db: Session,
    suffix: str = "owner",
    *,
    member_role: ProjectMemberRole = ProjectMemberRole.owner,
) -> tuple[User, Project, Requirement]:
    ensure_default_agents(db)
    user = User(
        email=f"prototype-job-{suffix}@example.com",
        name=f"Prototype Job {suffix}",
        password_hash="hash",
        permissions="agents:read,projects:write",
    )
    db.add(user)
    db.flush()
    project = Project(name=f"Prototype Job {suffix}", owner_id=user.id)
    db.add(project)
    db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role=member_role))
    requirement = Requirement(
        project_id=project.id,
        user_id=user.id,
        title="Durable generation",
        content="Generate a recoverable interactive product prototype.",
        analysis="The result must preserve version history and tenant isolation.",
        status="ANALYZED",
    )
    db.add(requirement)
    db.commit()
    return user, project, requirement


def http_request(path: str, method: str = "POST") -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "scheme": "http",
            "server": ("testserver", 80),
            "router": prototype_job_routes.router,
        }
    )


@pytest.fixture
def generation_session_local(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    factory = sessionmaker(bind=db.get_bind())
    monkeypatch.setattr(generation_service, "SessionLocal", factory)
    return factory


def artifact(title: str = "Generated prototype") -> PrototypeGenerationArtifact:
    specification = build_fallback_spec(
        title,
        "Create an interactive workflow with complete navigation and accessible forms.",
    )
    return PrototypeGenerationArtifact(
        specification=specification,
        agent_trace=[{"stage": "quality_review", "role": "test_engineer"}],
        quality={"score": 100, "passed": True, "issues": []},
        generation_mode="MULTI_AGENT",
    )


def enqueue_create(
    db: Session,
    user: User,
    project: Project,
    requirement: Requirement,
    *,
    request_id: str,
    title: str = "Durable prototype",
) -> PrototypeGenerationJob:
    payload = {
        "request_id": request_id,
        "operation": "CREATE",
        "project_id": project.id,
        "requirement_id": requirement.id,
        "title": title,
        "prompt": "Create a durable and interactive prototype for this project.",
    }
    job, _created = enqueue_prototype_generation_job(
        db,
        request_id=request_id,
        operation=PrototypeGenerationOperation.create,
        user_id=user.id,
        project_id=project.id,
        requirement_id=requirement.id,
        title=title,
        source_prompt=payload["prompt"],
        request_payload=payload,
    )
    db.commit()
    db.refresh(job)
    return job


def create_versioned_prototype(
    db: Session,
    user: User,
    project: Project,
    requirement: Requirement,
) -> ProductPrototype:
    first = artifact("Existing prototype")
    prototype = ProductPrototype(
        project_id=project.id,
        requirement_id=requirement.id,
        created_by_user_id=user.id,
        title="Existing prototype",
        summary=first.specification.summary,
        status="DRAFT",
        active_version=1,
    )
    db.add(prototype)
    db.flush()
    db.add(
        ProductPrototypeVersion(
            prototype_id=prototype.id,
            version=1,
            source_prompt="Initial prototype",
            specification_json=first.specification.model_dump_json(),
            agent_trace_json="[]",
            quality_json='{"score": 100, "passed": true}',
            generation_mode="MULTI_AGENT",
            created_by_user_id=user.id,
        )
    )
    db.commit()
    db.refresh(prototype)
    return prototype


def test_request_id_is_idempotent_for_same_payload_and_conflicts_for_different_payload(
    db: Session,
) -> None:
    user, project, requirement = generation_context(db, "idempotency")
    payload = {
        "request_id": "prototype-create-idempotent",
        "operation": "CREATE",
        "project_id": project.id,
        "requirement_id": requirement.id,
        "title": "Idempotent prototype",
        "prompt": "Generate the same interactive prototype exactly once.",
    }

    first, created = enqueue_prototype_generation_job(
        db,
        request_id=payload["request_id"],
        operation=PrototypeGenerationOperation.create,
        user_id=user.id,
        project_id=project.id,
        requirement_id=requirement.id,
        title=payload["title"],
        source_prompt=payload["prompt"],
        request_payload=payload,
    )
    db.commit()
    second, created_again = enqueue_prototype_generation_job(
        db,
        request_id=payload["request_id"],
        operation=PrototypeGenerationOperation.create,
        user_id=user.id,
        project_id=project.id,
        requirement_id=requirement.id,
        title=payload["title"],
        source_prompt=payload["prompt"],
        request_payload=payload,
    )

    assert created is True
    assert created_again is False
    assert second.id == first.id
    assert db.scalar(select(func.count(PrototypeGenerationJob.id))) == 1

    conflicting = {
        **payload,
        "prompt": "A different request body must not reuse the key.",
    }
    with pytest.raises(PrototypeGenerationRequestConflict):
        enqueue_prototype_generation_job(
            db,
            request_id=payload["request_id"],
            operation=PrototypeGenerationOperation.create,
            user_id=user.id,
            project_id=project.id,
            requirement_id=requirement.id,
            title=payload["title"],
            source_prompt=conflicting["prompt"],
            request_payload=conflicting,
        )


def test_create_route_returns_same_job_for_same_request_and_conflicts_on_payload_change(
    db: Session,
) -> None:
    user, project, requirement = generation_context(db, "route-idempotency")
    request_id = "prototype-route-idempotent"
    payload = PrototypeGenerationCreateRequest(
        request_id=request_id,
        project_id=project.id,
        requirement_id=requirement.id,
        title="Route idempotency",
        prompt="Create a route-level idempotent interactive prototype.",
    )

    first = create_prototype_generation_job(
        payload,
        http_request("/api/v1/prototypes/generation-jobs"),
        Response(),
        user,
        db,
    )
    repeated = create_prototype_generation_job(
        payload,
        http_request("/api/v1/prototypes/generation-jobs"),
        Response(),
        user,
        db,
    )
    assert repeated.job_id == first.job_id
    assert db.scalar(select(func.count(PrototypeGenerationJob.id))) == 1

    conflicting = payload.model_copy(
        update={"prompt": "This changed request body must be rejected."}
    )
    with pytest.raises(HTTPException) as conflict:
        create_prototype_generation_job(
            conflicting,
            http_request("/api/v1/prototypes/generation-jobs"),
            Response(),
            user,
            db,
        )
    assert conflict.value.status_code == 409


def test_job_routes_hide_cross_tenant_resources_and_reject_viewer_writes(
    db: Session,
) -> None:
    owner, project, requirement = generation_context(db, "tenant-owner")
    outsider, _other_project, _other_requirement = generation_context(
        db, "tenant-outsider"
    )
    job = enqueue_create(
        db,
        owner,
        project,
        requirement,
        request_id="prototype-tenant-isolation",
    )

    with pytest.raises(HTTPException) as hidden:
        get_prototype_generation_job(job.id, outsider, db)
    assert hidden.value.status_code == 404

    viewer = User(
        email="prototype-job-viewer@example.com",
        name="Prototype Job Viewer",
        password_hash="hash",
        permissions="projects:write",
    )
    db.add(viewer)
    db.flush()
    db.add(
        ProjectMember(
            project_id=project.id,
            user_id=viewer.id,
            role=ProjectMemberRole.viewer,
        )
    )
    db.commit()
    assert get_prototype_generation_job(job.id, viewer, db).job_id == job.id

    with pytest.raises(HTTPException) as cancel_forbidden:
        cancel_generation_job(
            job.id,
            http_request(f"/api/v1/prototypes/generation-jobs/{job.id}/cancel"),
            viewer,
            db,
        )
    assert cancel_forbidden.value.status_code == 403

    job.status = PrototypeGenerationStatus.failed
    job.error_code = "PROVIDER_ERROR"
    db.commit()
    with pytest.raises(HTTPException) as retry_forbidden:
        retry_generation_job(
            job.id,
            http_request(f"/api/v1/prototypes/generation-jobs/{job.id}/retry"),
            viewer,
            db,
        )
    assert retry_forbidden.value.status_code == 403


@pytest.mark.asyncio
async def test_sse_last_event_id_resumes_after_cursor_and_hides_cross_tenant_job(
    db: Session,
    generation_session_local,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, project, requirement = generation_context(db, "sse-owner")
    outsider, _other_project, _other_requirement = generation_context(
        db, "sse-outsider"
    )
    job = enqueue_create(
        db,
        owner,
        project,
        requirement,
        request_id="prototype-sse-resume",
    )
    first_event_id = job.latest_event_id
    assert first_event_id
    cancel_prototype_generation_job(db, job.id)
    db.commit()
    db.refresh(job)
    terminal_event_id = job.latest_event_id
    assert terminal_event_id and terminal_event_id > first_event_id

    with pytest.raises(HTTPException) as hidden:
        await stream_prototype_generation_events(
            job.id,
            last_event_id=0,
            header_event_id=str(first_event_id),
            current_user=outsider,
            db=db,
        )
    assert hidden.value.status_code == 404

    monkeypatch.setattr(prototype_job_routes, "SessionLocal", generation_session_local)

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(prototype_job_routes.asyncio, "sleep", no_sleep)
    response = await stream_prototype_generation_events(
        job.id,
        last_event_id=0,
        header_event_id=str(first_event_id),
        current_user=owner,
        db=db,
    )
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
    stream = "".join(chunks)

    assert response.media_type == "text/event-stream"
    assert "retry: 1500" in stream
    assert f"id: {terminal_event_id}" in stream
    assert "event: job_cancelled" in stream
    assert f"id: {first_event_id}\n" not in stream


def test_stale_lease_is_reclaimed_and_old_token_is_fenced(
    db: Session,
    generation_session_local,
) -> None:
    user, project, requirement = generation_context(db, "fencing")
    job = enqueue_create(
        db,
        user,
        project,
        requirement,
        request_id="prototype-stale-fencing",
    )
    assert claim_prototype_generation_job(db) == job.id
    db.expire_all()
    claimed = db.get(PrototypeGenerationJob, job.id)
    old_token = claimed.lease_token
    assert old_token

    claimed.locked_at = utc_now() - timedelta(
        seconds=generation_service.settings.prototype_generation_lease_seconds + 1
    )
    db.commit()
    assert claim_prototype_generation_job(db) == job.id
    db.expire_all()
    reclaimed = db.get(PrototypeGenerationJob, job.id)
    assert reclaimed.lease_token
    assert reclaimed.lease_token != old_token
    assert reclaimed.attempt_count == 2

    with pytest.raises(PrototypeGenerationLeaseLost):
        checkpoint_prototype_generation_job(
            job.id,
            old_token,
            "architecture",
            50,
            {"architect_output": "stale output"},
        )

    updated = checkpoint_prototype_generation_job(
        job.id,
        reclaimed.lease_token,
        "architecture",
        50,
        {"architect_output": "current output"},
    )
    assert updated.progress_percent == 50
    assert updated.stage == "architecture"


@pytest.mark.asyncio
async def test_heartbeat_refreshes_owned_lease_and_detects_token_loss(
    db: Session,
    generation_session_local,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, project, requirement = generation_context(db, "heartbeat")
    job = enqueue_create(
        db,
        user,
        project,
        requirement,
        request_id="prototype-heartbeat",
    )
    claim_prototype_generation_job(db)
    db.expire_all()
    claimed = db.get(PrototypeGenerationJob, job.id)
    token = claimed.lease_token
    original_locked_at = claimed.locked_at
    assert token and original_locked_at

    monkeypatch.setattr(
        generation_service.settings,
        "prototype_generation_lease_seconds",
        0.03,
    )
    heartbeat = PrototypeGenerationLeaseHeartbeat(db.get_bind(), job.id, token)
    await heartbeat.start()
    await asyncio.sleep(1.1)
    await heartbeat.stop()
    db.expire_all()
    assert db.get(PrototypeGenerationJob, job.id).locked_at > original_locked_at
    assert heartbeat.lost is False

    lost = PrototypeGenerationLeaseHeartbeat(db.get_bind(), job.id, "stale-token")
    await lost.start()
    await asyncio.sleep(1.1)
    await lost.stop()
    assert lost.lost is True


@pytest.mark.asyncio
async def test_retryable_failures_exhaust_automatic_attempts(
    db: Session,
    generation_session_local,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, project, requirement = generation_context(db, "attempts")
    job = enqueue_create(
        db,
        user,
        project,
        requirement,
        request_id="prototype-attempt-exhaustion",
    )
    job.max_attempts = 2
    db.commit()

    async def unavailable(*_args, **_kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(generation_service, "generate_prototype_artifact", unavailable)
    first = await process_prototype_generation_job(job.id)
    assert first.status == PrototypeGenerationStatus.queued
    assert first.attempt_count == 1
    assert first.next_attempt_at is not None

    db.expire_all()
    stored = db.get(PrototypeGenerationJob, job.id)
    stored.next_attempt_at = utc_now() - timedelta(seconds=1)
    db.commit()
    second = await process_prototype_generation_job(job.id)
    assert second.status == PrototypeGenerationStatus.failed
    assert second.attempt_count == 2
    assert second.finished_at is not None
    assert second.error_code == "RUNTIMEERROR"


@pytest.mark.asyncio
async def test_queued_and_running_jobs_cancel_idempotently(
    db: Session,
    generation_session_local,
) -> None:
    user, project, requirement = generation_context(db, "cancel")
    queued = enqueue_create(
        db,
        user,
        project,
        requirement,
        request_id="prototype-cancel-queued",
    )
    first_cancel = cancel_prototype_generation_job(db, queued.id)
    db.commit()
    repeated_cancel = cancel_prototype_generation_job(db, queued.id)
    db.commit()
    assert first_cancel.status == PrototypeGenerationStatus.cancelled
    assert repeated_cancel.status == PrototypeGenerationStatus.cancelled
    assert (
        db.scalar(
            select(func.count(PrototypeGenerationEvent.id)).where(
                PrototypeGenerationEvent.job_id == queued.id,
                PrototypeGenerationEvent.event_type == "CANCELLED",
            )
        )
        == 1
    )

    running = enqueue_create(
        db,
        user,
        project,
        requirement,
        request_id="prototype-cancel-running",
    )
    claim_prototype_generation_job(db)
    requested = cancel_prototype_generation_job(db, running.id)
    db.commit()
    assert requested.status == PrototypeGenerationStatus.cancelling

    cancelled = await process_prototype_generation_job(running.id, claimed=True)
    assert cancelled.status == PrototypeGenerationStatus.cancelled
    assert cancelled.lease_token is None
    assert cancelled.finished_at is not None
    assert (
        db.scalar(
            select(func.count(ProductPrototype.id)).where(
                ProductPrototype.project_id == project.id
            )
        )
        == 0
    )


def test_cancelled_regeneration_releases_target_version_reservation(
    db: Session,
) -> None:
    user, project, requirement = generation_context(db, "cancelled-reservation")
    prototype = create_versioned_prototype(db, user, project, requirement)
    first, _created = enqueue_prototype_generation_job(
        db,
        request_id="prototype-regeneration-cancelled-first",
        operation=PrototypeGenerationOperation.regenerate,
        user_id=user.id,
        project_id=project.id,
        requirement_id=requirement.id,
        prototype_id=prototype.id,
        base_version=1,
        target_version=2,
        title=prototype.title,
        source_prompt="First regeneration request",
    )
    db.commit()
    cancel_prototype_generation_job(db, first.id)
    db.commit()

    replacement, created = enqueue_prototype_generation_job(
        db,
        request_id="prototype-regeneration-cancelled-replacement",
        operation=PrototypeGenerationOperation.regenerate,
        user_id=user.id,
        project_id=project.id,
        requirement_id=requirement.id,
        prototype_id=prototype.id,
        base_version=1,
        target_version=2,
        title=prototype.title,
        source_prompt="Replacement regeneration request",
    )
    db.commit()

    assert created is True
    assert replacement.id != first.id
    assert replacement.target_version == 2


def test_manual_retry_only_requeues_failed_job(
    db: Session,
) -> None:
    user, project, requirement = generation_context(db, "manual-retry")
    job = enqueue_create(
        db,
        user,
        project,
        requirement,
        request_id="prototype-manual-retry",
    )
    with pytest.raises(ValueError):
        retry_prototype_generation_job(db, job.id)

    job.status = PrototypeGenerationStatus.failed
    job.stage = "failed"
    job.attempt_count = job.max_attempts
    job.error_code = "PROVIDER_ERROR"
    job.error_message = "Provider unavailable"
    job.finished_at = utc_now()
    db.commit()

    retried = retry_prototype_generation_job(db, job.id)
    db.commit()
    assert retried.status == PrototypeGenerationStatus.queued
    assert retried.attempt_count == 0
    assert retried.error_code == ""
    assert retried.error_message == ""
    assert retried.finished_at is None
    assert retried.next_attempt_at is not None


def test_create_finalization_persists_exactly_one_prototype_and_version(
    db: Session,
    generation_session_local,
) -> None:
    user, project, requirement = generation_context(db, "exactly-once")
    job = enqueue_create(
        db,
        user,
        project,
        requirement,
        request_id="prototype-create-exactly-once",
    )
    claim_prototype_generation_job(db)
    db.expire_all()
    token = db.get(PrototypeGenerationJob, job.id).lease_token
    assert token

    completed = finalize_prototype_generation_job(job.id, token, artifact())
    assert completed.status == PrototypeGenerationStatus.succeeded
    assert completed.result_prototype_id is not None
    assert completed.result_version == 1
    with pytest.raises(PrototypeGenerationLeaseLost):
        finalize_prototype_generation_job(job.id, token, artifact())

    db.expire_all()
    assert (
        db.scalar(
            select(func.count(ProductPrototype.id)).where(
                ProductPrototype.project_id == project.id
            )
        )
        == 1
    )
    assert (
        db.scalar(
            select(func.count(ProductPrototypeVersion.id))
            .join(ProductPrototype)
            .where(ProductPrototype.project_id == project.id)
        )
        == 1
    )


@pytest.mark.asyncio
async def test_regeneration_baseline_conflict_never_overwrites_new_active_version(
    db: Session,
    generation_session_local,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, project, requirement = generation_context(db, "baseline")
    prototype = create_versioned_prototype(db, user, project, requirement)
    job, _created = enqueue_prototype_generation_job(
        db,
        request_id="prototype-regenerate-stale-base",
        operation=PrototypeGenerationOperation.regenerate,
        user_id=user.id,
        project_id=project.id,
        requirement_id=requirement.id,
        prototype_id=prototype.id,
        base_version=1,
        target_version=2,
        title=prototype.title,
        source_prompt="Regenerate from version one.",
    )
    db.commit()

    async def generation_with_competing_activation(*_args, **_kwargs):
        with generation_session_local() as competing_db:
            current = competing_db.get(ProductPrototype, prototype.id)
            newer = artifact("Competing version")
            competing_db.add(
                ProductPrototypeVersion(
                    prototype_id=prototype.id,
                    version=3,
                    source_prompt="Concurrent update",
                    specification_json=newer.specification.model_dump_json(),
                    agent_trace_json="[]",
                    quality_json='{"score": 100, "passed": true}',
                    generation_mode="MULTI_AGENT",
                    created_by_user_id=user.id,
                )
            )
            current.active_version = 3
            current.summary = "Competing version remains active"
            competing_db.commit()
        return artifact("Stale regeneration")

    monkeypatch.setattr(
        generation_service,
        "generate_prototype_artifact",
        generation_with_competing_activation,
    )
    result = await process_prototype_generation_job(job.id)

    assert result.status == PrototypeGenerationStatus.failed
    assert result.error_code == "PROTOTYPE_VERSION_CONFLICT"
    db.expire_all()
    stored = db.get(ProductPrototype, prototype.id)
    assert stored.active_version == 3
    assert stored.summary == "Competing version remains active"
    assert (
        db.scalar(
            select(func.count(ProductPrototypeVersion.id)).where(
                ProductPrototypeVersion.prototype_id == prototype.id,
                ProductPrototypeVersion.version == 2,
            )
        )
        == 0
    )


def test_finalize_rejects_baseline_conflict_before_any_version_write(
    db: Session,
    generation_session_local,
) -> None:
    user, project, requirement = generation_context(db, "direct-baseline")
    prototype = create_versioned_prototype(db, user, project, requirement)
    job, _created = enqueue_prototype_generation_job(
        db,
        request_id="prototype-direct-stale-base",
        operation=PrototypeGenerationOperation.regenerate,
        user_id=user.id,
        project_id=project.id,
        requirement_id=requirement.id,
        prototype_id=prototype.id,
        base_version=1,
        target_version=2,
        title=prototype.title,
        source_prompt="Regenerate from version one.",
    )
    db.commit()
    claim_prototype_generation_job(db)
    db.expire_all()
    token = db.get(PrototypeGenerationJob, job.id).lease_token
    prototype = db.get(ProductPrototype, prototype.id)
    prototype.active_version = 3
    db.commit()
    assert token

    with pytest.raises(PrototypeGenerationPermanentError) as exc_info:
        finalize_prototype_generation_job(job.id, token, artifact("Stale result"))
    assert exc_info.value.code == "PROTOTYPE_VERSION_CONFLICT"
    assert (
        db.scalar(
            select(func.count(ProductPrototypeVersion.id)).where(
                ProductPrototypeVersion.prototype_id == prototype.id,
                ProductPrototypeVersion.version == 2,
            )
        )
        == 0
    )
