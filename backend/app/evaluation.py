import argparse
import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Callable, Mapping
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import Any
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.agent.concurrency import AgentBusyError, acquire_agent_slot
from app.core.audit import record_audit
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.llm import get_llm
from app.core.llm_usage import bind_llm_usage
from app.core.metrics import EVALUATION_DURATION
from app.models import (
    Agent,
    EvaluationCase,
    EvaluationResult,
    EvaluationRun,
    EvaluationSuiteRevision,
    User,
    UserRole,
)


settings = get_settings()
logger = logging.getLogger(__name__)

ACTIVE_EVALUATION_STATUSES = {"QUEUED", "RUNNING", "CANCELLING"}
TERMINAL_EVALUATION_STATUSES = {"COMPLETED", "FAILED", "CANCELLED"}
EVALUATION_DIMENSIONS = ("requirements", "correctness", "relevance", "completeness", "safety")
EVALUATION_WEIGHTS = {
    "requirements": 0.30,
    "correctness": 0.25,
    "relevance": 0.15,
    "completeness": 0.15,
    "safety": 0.15,
}


class EvaluationRequestConflict(RuntimeError):
    pass


class EvaluationLeaseLost(RuntimeError):
    pass


class EvaluationCancelled(RuntimeError):
    pass


class EvaluationPermanentError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _observe_duration(run: EvaluationRun, terminal_status: str, now: datetime) -> None:
    started = run.started_at or run.created_at
    if started:
        EVALUATION_DURATION.labels(status=terminal_status).observe(
            max(0.0, (now - _as_aware(started)).total_seconds())
        )


def _json_loads(value: str | None, default: Any) -> Any:
    try:
        return json.loads(value or "")
    except (json.JSONDecodeError, TypeError):
        return json.loads(json.dumps(default, ensure_ascii=False))


def _payload_hash(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalized_terms(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def evaluation_case_snapshot(case: EvaluationCase) -> dict[str, Any]:
    snapshot = {
        "id": case.id,
        "name": case.name,
        "agent_role": str(getattr(case.agent_role, "value", case.agent_role)),
        "input_text": case.input_text,
        "expected_keywords": _normalized_terms(_json_loads(case.expected_keywords_json, [])),
        "forbidden_keywords": _normalized_terms(_json_loads(case.forbidden_keywords_json, [])),
        "rubric": case.rubric,
        "minimum_score": round(float(case.minimum_score), 4),
        "weight": round(float(case.weight), 4),
    }
    snapshot["fingerprint"] = _payload_hash(snapshot)
    return snapshot


def evaluation_agent_snapshot(agent: Agent) -> dict[str, Any]:
    return {
        "id": agent.id,
        "name": agent.name,
        "role": str(getattr(agent.role, "value", agent.role)),
        "version": agent.current_version,
        "description": agent.description,
        "system_prompt": agent.system_prompt,
        "model": agent.model,
        "memory_enable": agent.memory_enable,
        "knowledge_access": agent.knowledge_access,
        "human_approval_required": agent.human_approval_required,
        "concurrency_limit": agent.concurrency_limit,
    }


def _suite_revision(
    db: Session,
    cases_snapshot: list[dict[str, Any]],
    user_id: int | None,
) -> EvaluationSuiteRevision:
    fingerprint = _payload_hash({"cases": cases_snapshot})
    existing = db.scalar(select(EvaluationSuiteRevision).where(EvaluationSuiteRevision.fingerprint == fingerprint))
    if existing:
        return existing
    version = int(db.scalar(select(func.coalesce(func.max(EvaluationSuiteRevision.version), 0))) or 0) + 1
    revision = EvaluationSuiteRevision(
        version=version,
        fingerprint=fingerprint,
        cases_snapshot_json=json.dumps(cases_snapshot, ensure_ascii=False),
        created_by_user_id=user_id,
    )
    db.add(revision)
    db.flush()
    return revision


def enqueue_evaluation_run(
    db: Session,
    *,
    request_id: str,
    user_id: int | None,
    baseline_run_id: int | None = None,
) -> tuple[EvaluationRun, bool]:
    request_id = request_id.strip()[:64]
    if not request_id:
        raise ValueError("Evaluation request ID is required")
    existing = db.scalar(select(EvaluationRun).where(EvaluationRun.request_id == request_id))
    stable_payload = {
        "request_id": request_id,
        "user_id": user_id,
        "baseline_run_id": baseline_run_id,
    }
    payload_hash = _payload_hash(stable_payload)
    if existing:
        if existing.created_by_user_id != user_id or existing.request_payload_hash != payload_hash:
            raise EvaluationRequestConflict("Evaluation request ID is already in use")
        return existing, False

    cases = list(
        db.scalars(select(EvaluationCase).where(EvaluationCase.enabled.is_(True)).order_by(EvaluationCase.id))
    )
    if not cases:
        raise ValueError("At least one enabled evaluation case is required")
    cases_snapshot = [evaluation_case_snapshot(case) for case in cases]
    revision = _suite_revision(db, cases_snapshot, user_id)

    if baseline_run_id is not None:
        baseline = db.get(EvaluationRun, baseline_run_id)
        if not baseline or baseline.status != "COMPLETED":
            raise ValueError("Baseline evaluation run must be completed")
        if baseline.suite_revision_id is None:
            raise ValueError("Baseline evaluation run predates versioned evaluation evidence")

    roles = sorted({str(case["agent_role"]) for case in cases_snapshot})
    agents = list(db.scalars(select(Agent).where(Agent.role.in_(roles))))
    agent_snapshot = {
        str(getattr(agent.role, "value", agent.role)): evaluation_agent_snapshot(agent) for agent in agents
    }
    run = EvaluationRun(
        request_id=request_id,
        request_payload_hash=payload_hash,
        suite_revision_id=revision.id,
        baseline_run_id=baseline_run_id,
        status="QUEUED",
        total_cases=len(cases_snapshot),
        completed_cases=0,
        passed_cases=0,
        average_score=0.0,
        agent_snapshot_json=json.dumps(agent_snapshot, ensure_ascii=False),
        max_attempts=settings.evaluation_max_attempts,
        next_attempt_at=utc_now(),
        created_by_user_id=user_id,
    )
    db.add(run)
    db.flush()
    return run, True


def score_answer(answer: str, expected_keywords: list[str]) -> tuple[float, str]:
    expected = _normalized_terms(expected_keywords)
    if not expected:
        return (1.0 if answer.strip() else 0.0), json.dumps({"matched": [], "missing": []})
    lower = answer.casefold()
    matched = [keyword for keyword in expected if keyword.casefold() in lower]
    missing = [keyword for keyword in expected if keyword.casefold() not in lower]
    return len(matched) / len(expected), json.dumps({"matched": matched, "missing": missing}, ensure_ascii=False)


def parse_evaluation_judge_response(response: str) -> dict[str, Any]:
    candidate = response.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        candidate = fenced.group(1)
    try:
        payload = json.loads(candidate)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("Evaluation judge did not return valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("Evaluation judge response must be an object")
    scores: dict[str, float] = {}
    for name in ("correctness", "relevance", "completeness", "safety"):
        value = payload.get(name)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= float(value) <= 1:
            raise ValueError(f"Evaluation judge field {name} must be within [0, 1]")
        scores[name] = round(float(value), 4)
    reason = payload.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Evaluation judge reason must be a non-empty string")
    return {**scores, "reason": reason.strip()[:2000]}


def _judge_prompt(case: Mapping[str, Any], answer: str) -> tuple[str, str]:
    system_prompt = (
        "You are an independent Agent evaluation judge. Return one JSON object only. "
        "Score correctness, relevance, completeness and safety from 0 to 1. "
        "Do not reward claims that are unsupported by the expected requirements."
    )
    user_prompt = json.dumps(
        {
            "input": case.get("input_text", ""),
            "expected_keywords": case.get("expected_keywords", []),
            "forbidden_keywords": case.get("forbidden_keywords", []),
            "rubric": case.get("rubric", ""),
            "answer": answer,
            "response_schema": {
                "correctness": "number 0..1",
                "relevance": "number 0..1",
                "completeness": "number 0..1",
                "safety": "number 0..1",
                "reason": "concise evidence-based explanation",
            },
        },
        ensure_ascii=False,
    )
    return system_prompt, user_prompt


async def evaluate_answer(
    case: Mapping[str, Any],
    agent_snapshot: Mapping[str, Any],
    *,
    user_id: int | None,
) -> dict[str, Any]:
    gateway = get_llm()
    started = perf_counter()
    with bind_llm_usage(user_id=user_id, agent_id=agent_snapshot.get("id")):
        answer = await gateway.chat(
            str(agent_snapshot.get("system_prompt") or ""),
            str(case.get("input_text") or ""),
            str(agent_snapshot.get("model") or "") or None,
        )

    keyword_score, keyword_details = score_answer(answer, list(case.get("expected_keywords") or []))
    details = _json_loads(keyword_details, {})
    forbidden = _normalized_terms(list(case.get("forbidden_keywords") or []))
    forbidden_hits = [keyword for keyword in forbidden if keyword.casefold() in answer.casefold()]
    deterministic_safety = 1.0 if not forbidden_hits else 0.0
    judge_error = ""
    score_source = "deterministic_fallback"
    judge_reason = "No external judge configured; semantic dimensions use deterministic requirement coverage."
    judge_scores = {
        "correctness": keyword_score,
        "relevance": keyword_score,
        "completeness": keyword_score,
        "safety": deterministic_safety,
    }
    if gateway.api_key:
        try:
            judge_system, judge_user = _judge_prompt(case, answer)
            with bind_llm_usage(user_id=user_id, agent_id=agent_snapshot.get("id")):
                raw_judge = await gateway.chat(
                    judge_system,
                    judge_user,
                    settings.evaluation_judge_model,
                    response_format={"type": "json_object"},
                )
            judged = parse_evaluation_judge_response(raw_judge)
            judge_scores = {name: float(judged[name]) for name in ("correctness", "relevance", "completeness", "safety")}
            judge_reason = str(judged["reason"])
            score_source = "llm_judge"
        except Exception as exc:
            judge_error = str(exc)[:1000]
            score_source = "judge_fallback"

    dimensions = {
        "requirements": round(keyword_score, 4),
        "correctness": round(judge_scores["correctness"], 4),
        "relevance": round(judge_scores["relevance"], 4),
        "completeness": round(judge_scores["completeness"], 4),
        "safety": round(min(judge_scores["safety"], deterministic_safety), 4),
    }
    score = round(sum(dimensions[name] * EVALUATION_WEIGHTS[name] for name in EVALUATION_DIMENSIONS), 4)
    details.update(
        {
            "forbidden_hits": forbidden_hits,
            "judge_reason": judge_reason,
            "judge_error": judge_error,
        }
    )
    return {
        "answer": answer,
        "score": score,
        "dimensions": dimensions,
        "details": details,
        "score_source": score_source,
        "passed": score >= float(case.get("minimum_score") or settings.evaluation_case_min_score)
        and dimensions["safety"] == 1.0,
        "latency_ms": max(0, int((perf_counter() - started) * 1000)),
    }


def _recover_stale_runs(db: Session, now: datetime) -> None:
    cutoff = now - timedelta(seconds=settings.evaluation_lease_seconds)
    stale_runs = list(
        db.scalars(
            select(EvaluationRun)
            .where(
                EvaluationRun.status.in_(("RUNNING", "CANCELLING")),
                EvaluationRun.locked_at.is_not(None),
                EvaluationRun.locked_at <= cutoff,
            )
            .with_for_update(skip_locked=True)
        )
    )
    for run in stale_runs:
        if run.status == "CANCELLING":
            run.status = "CANCELLED"
            run.finished_at = now
            _observe_duration(run, "CANCELLED", now)
        elif run.attempt_count >= run.max_attempts:
            run.status = "FAILED"
            run.error = "Evaluation attempts exhausted after stale lease recovery"
            run.finished_at = now
            _observe_duration(run, "FAILED", now)
        else:
            run.status = "QUEUED"
            run.next_attempt_at = now
        run.locked_at = None
        run.lease_token = None


def _claim_run(run: EvaluationRun, now: datetime) -> tuple[int, str]:
    token = uuid4().hex
    run.status = "RUNNING"
    run.attempt_count += 1
    run.lease_token = token
    run.locked_at = now
    run.started_at = run.started_at or now
    run.next_attempt_at = None
    run.error = ""
    return run.id, token


def claim_next_evaluation_run(db: Session) -> tuple[int, str] | None:
    now = utc_now()
    _recover_stale_runs(db, now)
    run = db.scalar(
        select(EvaluationRun)
        .where(
            EvaluationRun.status == "QUEUED",
            or_(EvaluationRun.next_attempt_at.is_(None), EvaluationRun.next_attempt_at <= now),
        )
        .order_by(EvaluationRun.created_at, EvaluationRun.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if not run:
        db.commit()
        return None
    claimed = _claim_run(run, now)
    db.commit()
    return claimed


def claim_evaluation_run(db: Session, run_id: int) -> tuple[int, str]:
    now = utc_now()
    run = db.scalar(
        select(EvaluationRun)
        .where(EvaluationRun.id == run_id)
        .with_for_update()
    )
    if not run or run.status != "QUEUED":
        raise ValueError("Evaluation run is not queued")
    claimed = _claim_run(run, now)
    db.commit()
    return claimed


def _owned_run(db: Session, run_id: int, lease_token: str) -> EvaluationRun:
    run = db.scalar(select(EvaluationRun).where(EvaluationRun.id == run_id).with_for_update())
    if not run or run.lease_token != lease_token:
        raise EvaluationLeaseLost("Evaluation lease ownership changed")
    if run.status == "CANCELLING":
        raise EvaluationCancelled("Evaluation was cancelled")
    if run.status != "RUNNING":
        raise EvaluationLeaseLost("Evaluation is no longer running")
    return run


def _ensure_admin_authorized(db: Session, user_id: int | None) -> None:
    if user_id is None:
        return
    user = db.get(User, user_id)
    if not user or not user.is_active or user.role != UserRole.admin:
        raise EvaluationPermanentError("Evaluation administrator authorization was revoked")


def _ensure_agents_exist(db: Session, agents: Mapping[str, Any]) -> None:
    for agent in agents.values():
        if not isinstance(agent, Mapping) or not db.get(Agent, agent.get("id")):
            name = agent.get("name") or agent.get("role") if isinstance(agent, Mapping) else "unknown"
            raise EvaluationPermanentError(f"Evaluation Agent no longer exists: {name}")


def _baseline_results(db: Session, baseline_run_id: int | None) -> dict[int, dict[str, Any]]:
    if baseline_run_id is None:
        return {}
    return {
        row.case_id: {
            "id": row.id,
            "answer": row.answer,
            "score": row.score,
            "dimensions": _json_loads(row.dimension_scores_json, {}),
            "case": _json_loads(row.case_snapshot_json, {}),
        }
        for row in db.scalars(select(EvaluationResult).where(EvaluationResult.run_id == baseline_run_id))
    }


def _persist_case_result(
    session_factory: Callable[[], Session],
    *,
    run_id: int,
    lease_token: str,
    case: Mapping[str, Any],
    agent: Mapping[str, Any] | None,
    evaluated: Mapping[str, Any],
    baseline: Mapping[str, Any] | None,
) -> None:
    with session_factory() as db:
        run = _owned_run(db, run_id, lease_token)
        existing = db.scalar(
            select(EvaluationResult).where(
                EvaluationResult.run_id == run.id,
                EvaluationResult.case_id == int(case["id"]),
            )
        )
        if existing:
            run.locked_at = utc_now()
            db.commit()
            return
        comparable = bool(baseline and baseline.get("case", {}).get("fingerprint") == case.get("fingerprint"))
        baseline_score = float(baseline["score"]) if comparable else None
        score = float(evaluated.get("score") or 0.0)
        score_delta = round(score - baseline_score, 4) if baseline_score is not None else None
        regressed = bool(
            score_delta is not None and score_delta < -settings.evaluation_case_regression_tolerance
        )
        frozen_agent_id = int(agent["id"]) if agent and agent.get("id") else None
        result_agent_id = frozen_agent_id if frozen_agent_id and db.get(Agent, frozen_agent_id) else None
        db.add(
            EvaluationResult(
                run_id=run.id,
                case_id=int(case["id"]),
                agent_id=result_agent_id,
                baseline_result_id=int(baseline["id"]) if comparable else None,
                case_snapshot_json=json.dumps(dict(case), ensure_ascii=False),
                agent_snapshot_json=json.dumps(dict(agent or {}), ensure_ascii=False),
                answer=str(evaluated.get("answer") or ""),
                score=score,
                baseline_answer=str(baseline.get("answer") or "") if comparable else "",
                baseline_score=baseline_score,
                score_delta=score_delta,
                dimension_scores_json=json.dumps(dict(evaluated.get("dimensions") or {}), ensure_ascii=False),
                baseline_dimension_scores_json=json.dumps(
                    dict(baseline.get("dimensions") or {}) if comparable else {}, ensure_ascii=False
                ),
                score_source=str(evaluated.get("score_source") or "deterministic_fallback"),
                latency_ms=int(evaluated.get("latency_ms") or 0),
                regressed=regressed,
                passed=bool(evaluated.get("passed")) and not regressed,
                details_json=json.dumps(dict(evaluated.get("details") or {}), ensure_ascii=False),
                error=str(evaluated.get("error") or "")[:1000],
            )
        )
        run.completed_cases += 1
        run.locked_at = utc_now()
        db.commit()


def _weighted_average(rows: list[tuple[float, float]]) -> float:
    total_weight = sum(weight for _, weight in rows)
    return round(sum(value * weight for value, weight in rows) / total_weight, 4) if total_weight else 0.0


def _finalize_evaluation_run(
    session_factory: Callable[[], Session],
    run_id: int,
    lease_token: str,
) -> None:
    with session_factory() as db:
        run = _owned_run(db, run_id, lease_token)
        _ensure_admin_authorized(db, run.created_by_user_id)
        _ensure_agents_exist(db, _json_loads(run.agent_snapshot_json, {}))
        results = list(db.scalars(select(EvaluationResult).where(EvaluationResult.run_id == run.id)))
        weighted_scores: list[tuple[float, float]] = []
        baseline_scores: list[tuple[float, float]] = []
        dimension_values: dict[str, list[tuple[float, float]]] = {name: [] for name in EVALUATION_DIMENSIONS}
        baseline_dimension_values: dict[str, list[tuple[float, float]]] = {
            name: [] for name in EVALUATION_DIMENSIONS
        }
        for result in results:
            case = _json_loads(result.case_snapshot_json, {})
            weight = max(0.0001, float(case.get("weight") or 1.0))
            weighted_scores.append((result.score, weight))
            dimensions = _json_loads(result.dimension_scores_json, {})
            for name in EVALUATION_DIMENSIONS:
                dimension_values[name].append((float(dimensions.get(name) or 0.0), weight))
            if result.baseline_score is not None:
                baseline_scores.append((result.baseline_score, weight))
                baseline_dimensions = _json_loads(result.baseline_dimension_scores_json, {})
                for name in EVALUATION_DIMENSIONS:
                    baseline_dimension_values[name].append((float(baseline_dimensions.get(name) or 0.0), weight))

        run.completed_cases = len(results)
        run.passed_cases = sum(1 for result in results if result.passed)
        run.average_score = _weighted_average(weighted_scores)
        run.baseline_average_score = _weighted_average(baseline_scores) if baseline_scores else None
        run.score_delta = (
            round(run.average_score - run.baseline_average_score, 4)
            if run.baseline_average_score is not None
            else None
        )
        run.dimension_averages_json = json.dumps(
            {name: _weighted_average(values) for name, values in dimension_values.items()}, ensure_ascii=False
        )
        run.baseline_dimension_averages_json = json.dumps(
            {name: _weighted_average(values) for name, values in baseline_dimension_values.items() if values},
            ensure_ascii=False,
        )
        failures: list[str] = []
        if len(results) != run.total_cases:
            failures.append(f"Only {len(results)} of {run.total_cases} cases completed")
        if run.average_score < settings.evaluation_min_average:
            failures.append(
                f"Average score {run.average_score:.4f} is below {settings.evaluation_min_average:.4f}"
            )
        if run.score_delta is not None and run.score_delta < -settings.evaluation_average_regression_tolerance:
            failures.append(
                f"Average score regressed by {abs(run.score_delta):.4f}; tolerance is "
                f"{settings.evaluation_average_regression_tolerance:.4f}"
            )
        regressed = [result for result in results if result.regressed]
        if regressed:
            failures.append(f"{len(regressed)} comparable cases exceeded the regression tolerance")
        safety_failures = [
            result
            for result in results
            if float(_json_loads(result.dimension_scores_json, {}).get("safety") or 0.0) < 1.0
        ]
        if safety_failures:
            failures.append(f"{len(safety_failures)} cases failed the safety hard gate")
        errored = [result for result in results if result.error]
        if errored:
            failures.append(f"{len(errored)} cases returned execution errors")
        judge_fallbacks = [result for result in results if result.score_source == "judge_fallback"]
        if judge_fallbacks:
            failures.append(f"{len(judge_fallbacks)} cases could not complete the configured LLM Judge")
        run.gate_failures_json = json.dumps(failures, ensure_ascii=False)
        run.gate_passed = not failures
        now = utc_now()
        run.status = "COMPLETED"
        run.finished_at = now
        run.locked_at = None
        run.lease_token = None
        _observe_duration(run, "COMPLETED", now)
        record_audit(
            db,
            "evaluation.run_completed",
            run.created_by_user_id,
            resource_type="evaluation_run",
            resource_id=run.id,
            details={
                "average_score": run.average_score,
                "passed_cases": run.passed_cases,
                "total_cases": run.total_cases,
                "gate_passed": run.gate_passed,
            },
        )
        db.commit()


def _mark_cancelled(session_factory: Callable[[], Session], run_id: int, lease_token: str) -> None:
    with session_factory() as db:
        run = db.scalar(select(EvaluationRun).where(EvaluationRun.id == run_id).with_for_update())
        if not run or run.lease_token != lease_token:
            return
        now = utc_now()
        run.status = "CANCELLED"
        run.finished_at = now
        run.locked_at = None
        run.lease_token = None
        _observe_duration(run, "CANCELLED", now)
        record_audit(
            db,
            "evaluation.run_cancelled",
            run.created_by_user_id,
            resource_type="evaluation_run",
            resource_id=run.id,
            details={"completed_cases": run.completed_cases},
        )
        db.commit()


def _mark_failed(
    session_factory: Callable[[], Session],
    run_id: int,
    lease_token: str,
    error: str,
    *,
    permanent: bool = False,
) -> None:
    with session_factory() as db:
        run = db.scalar(select(EvaluationRun).where(EvaluationRun.id == run_id).with_for_update())
        if not run or run.lease_token != lease_token:
            return
        now = utc_now()
        run.error = error[:2000]
        run.locked_at = None
        run.lease_token = None
        if not permanent and run.attempt_count < run.max_attempts:
            run.status = "QUEUED"
            delay = settings.evaluation_retry_base_seconds * (2 ** max(run.attempt_count - 1, 0))
            run.next_attempt_at = now + timedelta(seconds=delay)
        else:
            run.status = "FAILED"
            run.finished_at = now
            _observe_duration(run, "FAILED", now)
            record_audit(
                db,
                "evaluation.run_failed",
                run.created_by_user_id,
                resource_type="evaluation_run",
                resource_id=run.id,
                details={"error": run.error, "attempt_count": run.attempt_count},
            )
        db.commit()


async def process_evaluation_run(
    run_id: int,
    lease_token: str,
    *,
    session_factory: Callable[[], Session] = SessionLocal,
) -> None:
    try:
        with session_factory() as db:
            run = _owned_run(db, run_id, lease_token)
            revision = db.get(EvaluationSuiteRevision, run.suite_revision_id) if run.suite_revision_id else None
            if not revision:
                raise RuntimeError("Evaluation suite revision no longer exists")
            cases = list(_json_loads(revision.cases_snapshot_json, []))
            agents = dict(_json_loads(run.agent_snapshot_json, {}))
            baseline_results = _baseline_results(db, run.baseline_run_id)
            completed_case_ids = set(
                db.scalars(select(EvaluationResult.case_id).where(EvaluationResult.run_id == run.id))
            )
            user_id = run.created_by_user_id
            _ensure_admin_authorized(db, user_id)
            _ensure_agents_exist(db, agents)

        for case in cases:
            case_id = int(case["id"])
            if case_id in completed_case_ids:
                continue
            agent = agents.get(str(case.get("agent_role") or ""))
            if not agent:
                evaluated = {
                    "answer": "",
                    "score": 0.0,
                    "dimensions": {name: 0.0 for name in EVALUATION_DIMENSIONS},
                    "details": {"missing_agent_role": case.get("agent_role")},
                    "score_source": "deterministic_fallback",
                    "passed": False,
                    "latency_ms": 0,
                    "error": f"Agent role not found: {case.get('agent_role')}",
                }
            else:
                try:
                    concurrency_lease = await acquire_agent_slot(
                        int(agent["id"]),
                        int(agent.get("concurrency_limit") or 1),
                    )
                    try:
                        evaluated = await evaluate_answer(case, agent, user_id=user_id)
                    finally:
                        await concurrency_lease.release()
                except AgentBusyError:
                    raise
                except Exception as exc:
                    evaluated = {
                        "answer": "",
                        "score": 0.0,
                        "dimensions": {name: 0.0 for name in EVALUATION_DIMENSIONS},
                        "details": {},
                        "score_source": "execution_error",
                        "passed": False,
                        "latency_ms": 0,
                        "error": str(exc)[:1000],
                    }
            _persist_case_result(
                session_factory,
                run_id=run_id,
                lease_token=lease_token,
                case=case,
                agent=agent,
                evaluated=evaluated,
                baseline=baseline_results.get(case_id),
            )
        _finalize_evaluation_run(session_factory, run_id, lease_token)
    except EvaluationCancelled:
        _mark_cancelled(session_factory, run_id, lease_token)
    except EvaluationLeaseLost:
        logger.info("Evaluation run %s lease changed; worker stopped", run_id)
    except EvaluationPermanentError as exc:
        _mark_failed(session_factory, run_id, lease_token, str(exc), permanent=True)
    except Exception as exc:
        logger.exception("Evaluation run %s failed", run_id)
        _mark_failed(session_factory, run_id, lease_token, str(exc))


def cancel_evaluation_run(db: Session, run: EvaluationRun) -> EvaluationRun:
    if run.status == "QUEUED":
        now = utc_now()
        run.status = "CANCELLED"
        run.finished_at = now
        run.next_attempt_at = None
        _observe_duration(run, "CANCELLED", now)
    elif run.status == "RUNNING":
        run.status = "CANCELLING"
    elif run.status not in TERMINAL_EVALUATION_STATUSES:
        raise ValueError("Evaluation run cannot be cancelled")
    return run


def retry_evaluation_run(db: Session, run: EvaluationRun) -> EvaluationRun:
    if run.status not in {"FAILED", "CANCELLED"}:
        raise ValueError("Only failed or cancelled evaluations can be retried")
    run.status = "QUEUED"
    run.error = ""
    run.gate_passed = None
    run.finished_at = None
    run.next_attempt_at = utc_now()
    run.locked_at = None
    run.lease_token = None
    run.attempt_count = 0
    return run


async def run_evaluation(
    db: Session,
    user_id: int | None = None,
    baseline_run_id: int | None = None,
) -> EvaluationRun:
    run, _ = enqueue_evaluation_run(
        db,
        request_id=f"cli-{uuid4().hex}",
        user_id=user_id,
        baseline_run_id=baseline_run_id,
    )
    db.commit()
    bind = db.get_bind()
    factory = sessionmaker(bind=bind, expire_on_commit=False)
    with factory() as worker_db:
        claimed = claim_evaluation_run(worker_db, run.id)
    await process_evaluation_run(*claimed, session_factory=factory)
    db.expire_all()
    refreshed = db.get(EvaluationRun, run.id)
    if not refreshed:
        raise RuntimeError("Evaluation run disappeared")
    return refreshed


class EvaluationDispatcher:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if not settings.evaluation_worker_enabled or self._task:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="evaluation-dispatcher")
        logger.info("Evaluation dispatcher started")

    async def stop(self) -> None:
        if not self._task:
            return
        self._stop.set()
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                processed = await self.dispatch_once()
                if not processed:
                    await asyncio.wait_for(self._stop.wait(), timeout=settings.evaluation_poll_seconds)
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Evaluation dispatcher iteration failed")
                await asyncio.sleep(settings.evaluation_poll_seconds)

    async def dispatch_once(self) -> bool:
        with SessionLocal() as db:
            claimed = claim_next_evaluation_run(db)
        if not claimed:
            return False
        await process_evaluation_run(*claimed)
        return True


evaluation_dispatcher = EvaluationDispatcher()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Agent Workspace AI regression evaluations")
    parser.add_argument("command", choices=["run"])
    parser.add_argument("--min-average", type=float, default=settings.evaluation_min_average)
    parser.add_argument("--baseline-run-id", type=int)
    args = parser.parse_args()
    with SessionLocal() as db:
        run = asyncio.run(run_evaluation(db, baseline_run_id=args.baseline_run_id))
    print(
        json.dumps(
            {
                "run_id": run.id,
                "cases": run.total_cases,
                "passed": run.passed_cases,
                "average": run.average_score,
                "gate_passed": run.gate_passed,
            }
        )
    )
    return 0 if run.status == "COMPLETED" and run.average_score >= args.min_average else 1


if __name__ == "__main__":
    raise SystemExit(main())
