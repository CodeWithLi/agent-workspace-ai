import json
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.evaluation import (
    EvaluationRequestConflict,
    cancel_evaluation_run,
    claim_next_evaluation_run,
    enqueue_evaluation_run,
    parse_evaluation_judge_response,
    process_evaluation_run,
    run_evaluation,
    settings,
    retry_evaluation_run,
    utc_now,
)
from app.models import Agent, AgentRole, EvaluationCase, EvaluationResult, EvaluationRun, User, UserRole


class FakeGateway:
    api_key = None

    async def chat(self, system_prompt: str, _user_prompt: str, *_args, **_kwargs) -> str:
        return f"{system_prompt} architecture secure"


def seed_evaluation(db: Session) -> tuple[User, Agent, EvaluationCase]:
    user = User(
        email="evaluation@example.com",
        name="Evaluation Admin",
        password_hash="hash",
        role=UserRole.admin,
    )
    agent = Agent(
        name="Evaluation Architect",
        role=AgentRole.architect,
        description="Evaluated architect",
        system_prompt="candidate-v1",
        model="test-model",
        tools="",
        current_version=1,
    )
    case = EvaluationCase(
        name="Architecture safety",
        agent_role=AgentRole.architect.value,
        input_text="Design a secure architecture",
        expected_keywords_json=json.dumps(["architecture", "secure"]),
        forbidden_keywords_json=json.dumps(["disable security"]),
        rubric="Explain a secure architecture.",
        minimum_score=0.8,
        weight=2,
        enabled=True,
    )
    db.add_all([user, agent, case])
    db.commit()
    return user, agent, case


def worker_factory(db: Session):
    return sessionmaker(bind=db.get_bind(), expire_on_commit=False)


async def execute_next(db: Session) -> EvaluationRun:
    factory = worker_factory(db)
    with factory() as worker_db:
        claimed = claim_next_evaluation_run(worker_db)
    assert claimed is not None
    await process_evaluation_run(*claimed, session_factory=factory)
    db.expire_all()
    run = db.get(EvaluationRun, claimed[0])
    assert run is not None
    return run


def test_judge_parser_is_strict() -> None:
    parsed = parse_evaluation_judge_response(
        '```json\n{"correctness":0.9,"relevance":0.8,"completeness":0.7,'
        '"safety":1,"reason":"Requirements are grounded."}\n```'
    )
    assert parsed["correctness"] == 0.9
    assert parsed["reason"] == "Requirements are grounded."
    with pytest.raises(ValueError, match="valid JSON"):
        parse_evaluation_judge_response("not-json")
    with pytest.raises(ValueError, match=r"within \[0, 1\]"):
        parse_evaluation_judge_response(
            '{"correctness":2,"relevance":1,"completeness":1,"safety":1,"reason":"invalid"}'
        )


def test_enqueue_is_idempotent_and_freezes_suite_and_agent(db: Session) -> None:
    user, agent, _ = seed_evaluation(db)
    first, created = enqueue_evaluation_run(db, request_id="evaluation-request-1", user_id=user.id)
    second, created_again = enqueue_evaluation_run(db, request_id="evaluation-request-1", user_id=user.id)

    assert created is True
    assert created_again is False
    assert second.id == first.id
    assert json.loads(first.agent_snapshot_json)[AgentRole.architect.value]["system_prompt"] == "candidate-v1"

    agent.current_version = 2
    db.flush()
    duplicate, created_after_change = enqueue_evaluation_run(
        db, request_id="evaluation-request-1", user_id=user.id
    )
    assert duplicate.id == first.id
    assert created_after_change is False

    with pytest.raises(EvaluationRequestConflict):
        enqueue_evaluation_run(db, request_id="evaluation-request-1", user_id=user.id + 99)


def test_team_run_requires_cases_for_every_configured_core_agent(db: Session) -> None:
    user, _, _ = seed_evaluation(db)
    product_agent = Agent(
        name="Evaluation Product Manager",
        role=AgentRole.product_manager,
        description="Evaluated product manager",
        system_prompt="product-v1",
        model="test-model",
        tools="",
        current_version=1,
    )
    db.add(product_agent)
    db.commit()

    with pytest.raises(ValueError, match="product_manager"):
        enqueue_evaluation_run(
            db,
            request_id="evaluation-missing-role-coverage",
            user_id=user.id,
        )

    db.add(
        EvaluationCase(
            name="Product acceptance",
            agent_role=AgentRole.product_manager.value,
            input_text="Define an acceptance-ready requirement",
            expected_keywords_json=json.dumps(["acceptance"]),
            forbidden_keywords_json="[]",
            rubric="Define testable acceptance criteria.",
            minimum_score=0.8,
            weight=1,
            enabled=True,
        )
    )
    db.flush()
    run, created = enqueue_evaluation_run(
        db,
        request_id="evaluation-complete-role-coverage",
        user_id=user.id,
    )

    assert created is True
    assert set(json.loads(run.agent_snapshot_json)) == {
        AgentRole.architect.value,
        AgentRole.product_manager.value,
    }


@pytest.mark.asyncio
async def test_worker_uses_frozen_snapshot_and_completes_gate(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, agent, case = seed_evaluation(db)
    run, _ = enqueue_evaluation_run(db, request_id="evaluation-request-2", user_id=user.id)
    db.commit()
    agent.system_prompt = "mutated-after-enqueue"
    agent.current_version = 2
    db.commit()
    monkeypatch.setattr("app.evaluation.get_llm", lambda: FakeGateway())

    completed = await execute_next(db)
    result = db.scalar(select(EvaluationResult).where(EvaluationResult.run_id == run.id))

    assert completed.status == "COMPLETED"
    assert completed.completed_cases == completed.total_cases == 1
    assert completed.gate_passed is True
    assert completed.average_score == 1.0
    assert result is not None
    assert result.case_id == case.id
    assert result.answer.startswith("candidate-v1")
    assert json.loads(result.agent_snapshot_json)["version"] == 1
    assert result.score_source == "deterministic_fallback"


@pytest.mark.asyncio
async def test_worker_rechecks_team_coverage_before_passing_gate(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, _, _ = seed_evaluation(db)
    run, _ = enqueue_evaluation_run(
        db,
        request_id="evaluation-coverage-changed-during-run",
        user_id=user.id,
    )
    db.commit()
    db.add(
        Agent(
            name="Late Product Manager",
            role=AgentRole.product_manager,
            description="Added after evaluation enqueue",
            system_prompt="product-v1",
            model="test-model",
            tools="",
            current_version=1,
        )
    )
    db.commit()
    monkeypatch.setattr("app.evaluation.get_llm", lambda: FakeGateway())

    completed = await execute_next(db)

    assert completed.id == run.id
    assert completed.status == "COMPLETED"
    assert completed.gate_passed is False
    assert "product_manager" in " ".join(json.loads(completed.gate_failures_json))


@pytest.mark.asyncio
async def test_baseline_comparison_blocks_case_regression(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, agent, _ = seed_evaluation(db)
    monkeypatch.setattr("app.evaluation.get_llm", lambda: FakeGateway())
    baseline, _ = enqueue_evaluation_run(db, request_id="evaluation-baseline", user_id=user.id)
    db.commit()
    baseline = await execute_next(db)
    assert baseline.gate_passed is True

    agent.system_prompt = "candidate-without-required-terms"
    agent.current_version = 2
    db.commit()

    class RegressedGateway(FakeGateway):
        async def chat(self, system_prompt: str, _user_prompt: str, *_args, **_kwargs) -> str:
            return system_prompt

    monkeypatch.setattr("app.evaluation.get_llm", lambda: RegressedGateway())
    candidate, _ = enqueue_evaluation_run(
        db,
        request_id="evaluation-candidate",
        user_id=user.id,
        baseline_run_id=baseline.id,
    )
    db.commit()
    candidate = await execute_next(db)
    result = db.scalar(select(EvaluationResult).where(EvaluationResult.run_id == candidate.id))

    assert candidate.status == "COMPLETED"
    assert candidate.baseline_average_score == 1.0
    assert candidate.average_score == 0.15
    assert candidate.score_delta == -0.85
    assert candidate.gate_passed is False
    assert result is not None and result.regressed is True and result.passed is False
    assert "regression tolerance" in " ".join(json.loads(candidate.gate_failures_json))


@pytest.mark.asyncio
async def test_configured_judge_failure_blocks_release(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, _, _ = seed_evaluation(db)

    class BrokenJudgeGateway(FakeGateway):
        api_key = "configured"

        async def chat(self, system_prompt: str, _user_prompt: str, *_args, **kwargs) -> str:
            return "not-json" if kwargs.get("response_format") else f"{system_prompt} architecture secure"

    monkeypatch.setattr("app.evaluation.get_llm", lambda: BrokenJudgeGateway())
    run, _ = enqueue_evaluation_run(db, request_id="evaluation-broken-judge", user_id=user.id)
    db.commit()
    completed = await execute_next(db)
    result = db.scalar(select(EvaluationResult).where(EvaluationResult.run_id == run.id))

    assert completed.status == "COMPLETED"
    assert completed.gate_passed is False
    assert result is not None and result.score_source == "judge_fallback"
    assert "configured LLM Judge" in " ".join(json.loads(completed.gate_failures_json))


@pytest.mark.asyncio
async def test_worker_revalidates_admin_authorization(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, _, _ = seed_evaluation(db)
    monkeypatch.setattr("app.evaluation.get_llm", lambda: FakeGateway())
    run, _ = enqueue_evaluation_run(db, request_id="evaluation-revoked-admin", user_id=user.id)
    db.commit()
    user.is_active = False
    db.commit()

    failed = await execute_next(db)

    assert failed.id == run.id
    assert failed.status == "FAILED"
    assert "authorization was revoked" in failed.error
    assert db.scalar(select(EvaluationResult).where(EvaluationResult.run_id == run.id)) is None


@pytest.mark.asyncio
async def test_cli_run_claims_its_own_job(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, _, _ = seed_evaluation(db)
    older, _ = enqueue_evaluation_run(db, request_id="evaluation-older-queued", user_id=user.id)
    db.commit()
    monkeypatch.setattr("app.evaluation.get_llm", lambda: FakeGateway())

    completed = await run_evaluation(db, user.id)

    db.refresh(older)
    assert completed.status == "COMPLETED"
    assert older.status == "QUEUED"


def test_cancel_and_retry_preserve_durable_progress(db: Session) -> None:
    user, _, _ = seed_evaluation(db)
    run, _ = enqueue_evaluation_run(db, request_id="evaluation-cancel", user_id=user.id)
    cancel_evaluation_run(db, run)
    db.commit()
    assert run.status == "CANCELLED"

    retry_evaluation_run(db, run)
    db.commit()
    assert run.status == "QUEUED"
    assert run.attempt_count == 0
    assert run.next_attempt_at is not None


def test_stale_evaluation_is_reclaimed_with_autoflush_disabled(db: Session) -> None:
    user, _, _ = seed_evaluation(db)
    run, _ = enqueue_evaluation_run(db, request_id="evaluation-stale", user_id=user.id)
    db.commit()

    first_claim = claim_next_evaluation_run(db)
    assert first_claim is not None

    db.autoflush = False
    stale = db.get(EvaluationRun, run.id)
    stale.locked_at = utc_now() - timedelta(seconds=settings.evaluation_lease_seconds + 1)
    db.commit()

    replacement = claim_next_evaluation_run(db)

    assert replacement is not None
    assert replacement[0] == run.id
    assert replacement[1] != first_claim[1]
