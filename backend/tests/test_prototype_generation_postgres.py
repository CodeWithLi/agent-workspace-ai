import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import func, select
from starlette.requests import Request

from app.api.routes import prototype_jobs as prototype_job_routes
from app.api.routes.prototype_jobs import (
    create_prototype_generation_job,
    create_prototype_regeneration_job,
)
from app.core.database import SessionLocal
from app.models import (
    ProductPrototype,
    ProductPrototypeVersion,
    Project,
    ProjectMember,
    ProjectMemberRole,
    PrototypeGenerationJob,
    PrototypeGenerationOperation,
    User,
)
from app.prototypes.schemas import (
    PrototypeGenerationCreateRequest,
    PrototypeGenerationRegenerateRequest,
)
from app.prototypes.service import build_fallback_spec
from app.services.prototype_generations import (
    PrototypeGenerationLeaseLost,
    cancel_prototype_generation_job,
    checkpoint_prototype_generation_job,
    claim_prototype_generation_job,
    enqueue_prototype_generation_job,
    settings,
    utc_now,
)


pytestmark = pytest.mark.skipif(
    os.getenv("PROTOTYPE_GENERATION_PG_INTEGRATION") != "1",
    reason="requires the PostgreSQL concurrency CI job",
)


def http_request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "scheme": "http",
            "server": ("testserver", 80),
            "router": prototype_job_routes.router,
        }
    )


@pytest.fixture(scope="module")
def postgres_context() -> dict[str, int | str]:
    suffix = uuid4().hex[:12]
    with SessionLocal() as db:
        if db.get_bind().dialect.name != "postgresql":
            pytest.skip("requires PostgreSQL")
        user = User(
            email=f"prototype-pg-{suffix}@example.com",
            name="Prototype PG Owner",
            password_hash="hash",
            permissions="projects:write",
        )
        db.add(user)
        db.flush()
        project = Project(name=f"Prototype PG {suffix}", owner_id=user.id)
        db.add(project)
        db.flush()
        db.add(
            ProjectMember(
                project_id=project.id,
                user_id=user.id,
                role=ProjectMemberRole.owner,
            )
        )
        db.commit()
        context = {"user_id": user.id, "project_id": project.id, "suffix": suffix}
    yield context
    with SessionLocal() as db:
        project = db.get(Project, context["project_id"])
        if project:
            db.delete(project)
            db.commit()
        user = db.get(User, context["user_id"])
        if user:
            db.delete(user)
            db.commit()


def test_postgres_concurrent_idempotent_enqueue_creates_one_job(
    postgres_context: dict[str, int | str],
) -> None:
    barrier = Barrier(2)
    request_id = f"pg-idempotent-{postgres_context['suffix']}"

    def enqueue() -> int:
        with SessionLocal() as db:
            user = db.get(User, postgres_context["user_id"])
            barrier.wait(timeout=10)
            result = create_prototype_generation_job(
                PrototypeGenerationCreateRequest(
                    request_id=request_id,
                    project_id=int(postgres_context["project_id"]),
                    title="PostgreSQL idempotent prototype",
                    prompt="Generate a complete interactive PostgreSQL concurrency prototype.",
                ),
                http_request("/api/v1/prototypes/generation-jobs"),
                Response(),
                user,
                db,
            )
            return result.job_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        job_ids = list(executor.map(lambda _index: enqueue(), range(2)))

    assert len(set(job_ids)) == 1
    with SessionLocal() as db:
        assert db.scalar(
            select(func.count(PrototypeGenerationJob.id)).where(
                PrototypeGenerationJob.request_id == request_id
            )
        ) == 1
        cancel_prototype_generation_job(db, job_ids[0])
        db.commit()


def test_postgres_skip_locked_and_stale_token_fencing(
    postgres_context: dict[str, int | str],
) -> None:
    job_ids: list[int] = []
    with SessionLocal() as db:
        for index in range(2):
            job, _ = enqueue_prototype_generation_job(
                db,
                request_id=f"pg-claim-{postgres_context['suffix']}-{index}",
                operation=PrototypeGenerationOperation.create,
                user_id=int(postgres_context["user_id"]),
                project_id=int(postgres_context["project_id"]),
                title=f"PostgreSQL claim {index}",
                source_prompt="Generate a complete interactive prototype for queue claim testing.",
            )
            job_ids.append(job.id)
        db.commit()

    barrier = Barrier(2)

    def claim() -> int | None:
        with SessionLocal() as db:
            barrier.wait(timeout=10)
            return claim_prototype_generation_job(db)

    with ThreadPoolExecutor(max_workers=2) as executor:
        claimed = list(executor.map(lambda _index: claim(), range(2)))
    assert set(claimed) == set(job_ids)

    stale_job_id = job_ids[0]
    with SessionLocal() as db:
        stale_job = db.get(PrototypeGenerationJob, stale_job_id)
        old_token = stale_job.lease_token
        stale_job.locked_at = utc_now() - timedelta(
            seconds=settings.prototype_generation_lease_seconds + 1
        )
        db.commit()
    with SessionLocal() as db:
        assert claim_prototype_generation_job(db) == stale_job_id
        replacement = db.get(PrototypeGenerationJob, stale_job_id)
        assert replacement.lease_token != old_token

    with pytest.raises(PrototypeGenerationLeaseLost):
        checkpoint_prototype_generation_job(
            stale_job_id,
            str(old_token),
            "architecture",
            45,
            {"architect_output": "stale worker output"},
        )


def test_postgres_concurrent_regeneration_reserves_one_version(
    postgres_context: dict[str, int | str],
) -> None:
    specification = build_fallback_spec("Concurrent version", "registration login invitation")
    with SessionLocal() as db:
        prototype = ProductPrototype(
            project_id=int(postgres_context["project_id"]),
            created_by_user_id=int(postgres_context["user_id"]),
            title="Concurrent regeneration",
            summary=specification.summary,
            active_version=1,
        )
        db.add(prototype)
        db.flush()
        db.add(
            ProductPrototypeVersion(
                prototype_id=prototype.id,
                version=1,
                source_prompt="Generate the original prototype.",
                specification_json=specification.model_dump_json(),
                agent_trace_json="[]",
                quality_json='{"score": 100, "passed": true}',
                generation_mode="MULTI_AGENT",
                created_by_user_id=int(postgres_context["user_id"]),
            )
        )
        db.commit()
        prototype_id = prototype.id

    barrier = Barrier(2)

    def regenerate(index: int) -> tuple[str, int]:
        with SessionLocal() as db:
            user = db.get(User, postgres_context["user_id"])
            barrier.wait(timeout=10)
            try:
                result = create_prototype_regeneration_job(
                    prototype_id,
                    PrototypeGenerationRegenerateRequest(
                        request_id=f"pg-regenerate-{postgres_context['suffix']}-{index}",
                        feedback=f"Concurrent feedback {index}",
                    ),
                    http_request(
                        f"/api/v1/prototypes/{prototype_id}/generation-jobs"
                    ),
                    Response(),
                    user,
                    db,
                )
                return "created", result.target_version
            except HTTPException as exc:
                return "conflict", exc.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(regenerate, range(2)))

    assert sorted(results) == [("conflict", 409), ("created", 2)]
    with SessionLocal() as db:
        jobs = list(
            db.scalars(
                select(PrototypeGenerationJob).where(
                    PrototypeGenerationJob.prototype_id == prototype_id
                )
            )
        )
        assert len(jobs) == 1
        assert jobs[0].target_version == 2
