import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import Response
from sqlalchemy import delete, func, select
from starlette.requests import Request

from app.api.routes import evaluations as evaluation_routes
from app.api.routes.evaluations import create_evaluation_run
from app.core.database import SessionLocal
from app.evaluation import EvaluationLeaseLost, _owned_run, claim_next_evaluation_run, enqueue_evaluation_run, settings, utc_now
from app.models import Agent, AgentRole, EvaluationCase, EvaluationRun, EvaluationSuiteRevision, User, UserRole
from app.schemas import EvaluationRunCreate


pytestmark = pytest.mark.skipif(
    os.getenv("EVALUATION_PG_INTEGRATION") != "1",
    reason="requires the PostgreSQL concurrency CI job",
)


def http_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/evaluations/runs",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "scheme": "http",
            "server": ("testserver", 80),
            "router": evaluation_routes.router,
        }
    )


@pytest.fixture(scope="module")
def postgres_evaluation_context() -> dict[str, int | str]:
    suffix = uuid4().hex[:12]
    with SessionLocal() as db:
        if db.get_bind().dialect.name != "postgresql":
            pytest.skip("requires PostgreSQL")
        user = User(
            email=f"evaluation-pg-{suffix}@example.com",
            name="Evaluation PG Admin",
            password_hash="hash",
            role=UserRole.admin,
        )
        db.add(user)
        db.flush()
        agent = db.scalar(select(Agent).where(Agent.role == AgentRole.architect))
        created_agent = agent is None
        if agent is None:
            agent = Agent(
                name=f"Evaluation PG Architect {suffix}",
                role=AgentRole.architect,
                description="PostgreSQL evaluation concurrency Agent",
                system_prompt="Return secure architecture evidence",
                model="test-model",
                tools="",
            )
            db.add(agent)
            db.flush()
        case = EvaluationCase(
            name=f"Evaluation PG Case {suffix}",
            agent_role=AgentRole.architect.value,
            input_text="Return secure architecture evidence",
            expected_keywords_json='["secure", "architecture"]',
            enabled=True,
            created_by_user_id=user.id,
        )
        db.add(case)
        db.commit()
        context = {
            "user_id": user.id,
            "agent_id": agent.id,
            "case_id": case.id,
            "created_agent": int(created_agent),
            "suffix": suffix,
        }
    yield context
    with SessionLocal() as db:
        revision_ids = list(
            db.scalars(
                select(EvaluationRun.suite_revision_id).where(
                    EvaluationRun.created_by_user_id == context["user_id"],
                    EvaluationRun.suite_revision_id.is_not(None),
                )
            )
        )
        db.execute(delete(EvaluationRun).where(EvaluationRun.created_by_user_id == context["user_id"]))
        case = db.get(EvaluationCase, context["case_id"])
        if case:
            db.delete(case)
        user = db.get(User, context["user_id"])
        if user:
            db.delete(user)
        if context["created_agent"]:
            agent = db.get(Agent, context["agent_id"])
            if agent:
                db.delete(agent)
        db.flush()
        if revision_ids:
            db.execute(
                delete(EvaluationSuiteRevision).where(
                    EvaluationSuiteRevision.id.in_(revision_ids),
                    ~EvaluationSuiteRevision.id.in_(select(EvaluationRun.suite_revision_id)),
                )
            )
        db.commit()


def test_postgres_concurrent_evaluation_enqueue_is_idempotent(
    postgres_evaluation_context: dict[str, int | str],
) -> None:
    request_id = f"evaluation-pg-idempotent-{postgres_evaluation_context['suffix']}"
    barrier = Barrier(2)

    def enqueue() -> int:
        with SessionLocal() as db:
            user = db.get(User, postgres_evaluation_context["user_id"])
            barrier.wait(timeout=10)
            result = create_evaluation_run(
                EvaluationRunCreate(request_id=request_id),
                http_request(),
                Response(),
                user,
                db,
            )
            return result.id

    with ThreadPoolExecutor(max_workers=2) as executor:
        run_ids = list(executor.map(lambda _index: enqueue(), range(2)))

    assert len(set(run_ids)) == 1
    with SessionLocal() as db:
        assert db.scalar(
            select(func.count(EvaluationRun.id)).where(EvaluationRun.request_id == request_id)
        ) == 1
        run = db.get(EvaluationRun, run_ids[0])
        run.status = "CANCELLED"
        db.commit()


def test_postgres_evaluation_skip_locked_and_stale_token_fencing(
    postgres_evaluation_context: dict[str, int | str],
) -> None:
    run_ids: list[int] = []
    with SessionLocal() as db:
        for index in range(2):
            run, _ = enqueue_evaluation_run(
                db,
                request_id=f"evaluation-pg-claim-{postgres_evaluation_context['suffix']}-{index}",
                user_id=int(postgres_evaluation_context["user_id"]),
            )
            run_ids.append(run.id)
        db.commit()

    barrier = Barrier(2)

    def claim() -> tuple[int, str] | None:
        with SessionLocal() as db:
            barrier.wait(timeout=10)
            return claim_next_evaluation_run(db)

    with ThreadPoolExecutor(max_workers=2) as executor:
        claimed = list(executor.map(lambda _index: claim(), range(2)))
    assert {item[0] for item in claimed if item} == set(run_ids)

    stale_run_id, old_token = claimed[0]
    with SessionLocal() as db:
        stale = db.get(EvaluationRun, stale_run_id)
        stale.locked_at = utc_now() - timedelta(seconds=settings.evaluation_lease_seconds + 1)
        other = db.get(EvaluationRun, run_ids[1] if stale_run_id == run_ids[0] else run_ids[0])
        other.status = "CANCELLED"
        other.locked_at = None
        other.lease_token = None
        db.commit()
    with SessionLocal() as db:
        replacement = claim_next_evaluation_run(db)
        assert replacement is not None and replacement[0] == stale_run_id
        assert replacement[1] != old_token
    with SessionLocal() as db, pytest.raises(EvaluationLeaseLost):
        _owned_run(db, stale_run_id, old_token)
    with SessionLocal() as db:
        stale = db.get(EvaluationRun, stale_run_id)
        stale.status = "CANCELLED"
        stale.locked_at = None
        stale.lease_token = None
        db.commit()
