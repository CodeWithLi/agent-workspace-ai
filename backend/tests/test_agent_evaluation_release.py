import json

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.api.routes.evaluations import publish_evaluation_run, rollback_evaluation_release
from app.evaluation import enqueue_evaluation_run
from app.models import (
    Agent,
    AgentEvaluationRelease,
    AgentPromptVersion,
    AgentRole,
    AuditLog,
    EvaluationCase,
    EvaluationRun,
    Notification,
    User,
    UserRole,
)
from app.schemas import EvaluationReleaseRequest
from app.services.agent_versions import VERSION_FIELDS, create_version, ensure_initial_agent_version


def request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/evaluations/runs/1/publish",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 1234),
        }
    )


def seed_candidate_release(
    db: Session,
) -> tuple[User, Agent, AgentPromptVersion, EvaluationRun, EvaluationRun]:
    admin = User(
        email="release-admin@example.com",
        name="Release Admin",
        password_hash="hash",
        role=UserRole.admin,
    )
    agent = Agent(
        name="Release Architect",
        role=AgentRole.architect,
        description="Production architect",
        system_prompt="production-prompt-v1",
        model="test-model",
        tools="",
        current_version=1,
    )
    case = EvaluationCase(
        name="Release safety",
        agent_role=AgentRole.architect.value,
        input_text="Design a release-safe architecture",
        expected_keywords_json=json.dumps(["release", "rollback"]),
        forbidden_keywords_json="[]",
        rubric="Preserve release evidence.",
        minimum_score=0.8,
        weight=1,
        enabled=True,
    )
    db.add_all([admin, agent, case])
    db.flush()
    ensure_initial_agent_version(db, agent)
    values = {field: getattr(agent, field) for field in VERSION_FIELDS}
    values["system_prompt"] = "challenger-prompt-v2"
    candidate = create_version(
        db,
        agent,
        values,
        admin.id,
        release_note="Evaluated challenger",
    )
    baseline, _ = enqueue_evaluation_run(
        db,
        request_id="release-baseline-run",
        user_id=admin.id,
    )
    baseline.status = "COMPLETED"
    baseline.gate_passed = True
    candidate_run, _ = enqueue_evaluation_run(
        db,
        request_id="release-candidate-run",
        user_id=admin.id,
        baseline_run_id=baseline.id,
        candidate_version_id=candidate.id,
    )
    candidate_run.status = "COMPLETED"
    candidate_run.gate_passed = True
    db.commit()
    return admin, agent, candidate, baseline, candidate_run


def test_candidate_run_requires_matching_baseline_and_freezes_draft(db: Session) -> None:
    admin, agent, candidate, baseline, run = seed_candidate_release(db)

    snapshot = json.loads(run.agent_snapshot_json)[AgentRole.architect.value]
    assert snapshot["version"] == candidate.version == 2
    assert snapshot["system_prompt"] == "challenger-prompt-v2"
    assert run.candidate_agent_id == agent.id
    assert run.candidate_version_id == candidate.id
    assert run.candidate_version == candidate.version
    assert run.expected_current_version == 1
    assert baseline.suite_revision_id == run.suite_revision_id

    with pytest.raises(ValueError, match="baseline"):
        enqueue_evaluation_run(
            db,
            request_id="candidate-without-baseline",
            user_id=admin.id,
            candidate_version_id=candidate.id,
        )


def test_gate_and_optimistic_version_conflicts_block_release(db: Session) -> None:
    admin, agent, _, _, run = seed_candidate_release(db)
    run.gate_passed = False
    db.commit()

    with pytest.raises(HTTPException) as gate_error:
        publish_evaluation_run(
            run.id,
            EvaluationReleaseRequest(request_id="release-blocked-gate"),
            request(),
            admin,
            db,
        )
    assert gate_error.value.status_code == 409

    run.gate_passed = True
    agent.current_version = 7
    db.commit()
    with pytest.raises(HTTPException) as version_error:
        publish_evaluation_run(
            run.id,
            EvaluationReleaseRequest(request_id="release-version-drift"),
            request(),
            admin,
            db,
        )
    assert version_error.value.status_code == 409
    assert "changed" in str(version_error.value.detail).lower()


def test_release_rechecks_current_core_agent_coverage(db: Session) -> None:
    admin, _, _, _, run = seed_candidate_release(db)
    db.add(
        Agent(
            name="Release Product Manager",
            role=AgentRole.product_manager,
            description="Added after the historical green run",
            system_prompt="product-v1",
            model="test-model",
            tools="",
            current_version=1,
        )
    )
    db.commit()

    with pytest.raises(HTTPException) as coverage_error:
        publish_evaluation_run(
            run.id,
            EvaluationReleaseRequest(request_id="release-missing-role-coverage"),
            request(),
            admin,
            db,
        )

    assert coverage_error.value.status_code == 409
    assert "product_manager" in str(coverage_error.value.detail)


def test_passed_candidate_release_is_idempotent_audited_and_redacted(db: Session) -> None:
    admin, agent, candidate, _, run = seed_candidate_release(db)
    observer = User(
        email="release-observer@example.com",
        name="Release Observer",
        password_hash="hash",
        role=UserRole.admin,
    )
    db.add(observer)
    db.commit()
    payload = EvaluationReleaseRequest(request_id="publish-candidate-request")

    first = publish_evaluation_run(run.id, payload, request(), admin, db)
    second = publish_evaluation_run(run.id, payload, request(), admin, db)

    assert first.id == second.id
    assert first.status == "PUBLISHED"
    assert first.candidate_version == candidate.version
    assert first.previous_version == 1
    assert db.get(Agent, agent.id).current_version == candidate.version
    assert db.get(AgentPromptVersion, candidate.id).status == "PUBLISHED"
    assert db.scalar(select(func.count(AgentEvaluationRelease.id))) == 1

    audit = db.scalar(
        select(AuditLog).where(AuditLog.action == "evaluation.release_publish")
    )
    assert audit is not None
    assert "challenger-prompt-v2" not in audit.details
    notifications = list(
        db.scalars(select(Notification).where(Notification.title == "Agent 候选版本已发布"))
    )
    assert {notification.user_id for notification in notifications} == {admin.id, observer.id}
    assert all("challenger-prompt-v2" not in notification.content for notification in notifications)


def test_release_rollback_is_idempotent_and_preserves_version_history(db: Session) -> None:
    admin, agent, candidate, _, run = seed_candidate_release(db)
    released = publish_evaluation_run(
        run.id,
        EvaluationReleaseRequest(request_id="publish-before-rollback"),
        request(),
        admin,
        db,
    )
    rollback_payload = EvaluationReleaseRequest(request_id="rollback-release-request")

    first = rollback_evaluation_release(
        released.id,
        rollback_payload,
        request(),
        admin,
        db,
    )
    version_count = db.scalar(select(func.count(AgentPromptVersion.id)))
    second = rollback_evaluation_release(
        released.id,
        rollback_payload,
        request(),
        admin,
        db,
    )

    assert first.id == second.id == released.id
    assert first.status == "ROLLED_BACK"
    assert first.rollback_version is not None and first.rollback_version > candidate.version
    assert db.get(Agent, agent.id).system_prompt == "production-prompt-v1"
    assert db.scalar(select(func.count(AgentPromptVersion.id))) == version_count
    assert db.scalar(
        select(func.count(AuditLog.id)).where(AuditLog.action == "evaluation.release_rollback")
    ) == 1
    assert db.scalar(
        select(func.count(Notification.id)).where(Notification.title == "Agent 发布已回滚")
    ) == 1
