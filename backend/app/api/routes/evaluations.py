import json
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.audit import record_audit
from app.core.database import get_db
from app.evaluation import (
    EvaluationRequestConflict,
    cancel_evaluation_run,
    enqueue_evaluation_run,
    retry_evaluation_run,
)
from app.models import EvaluationCase, EvaluationResult, EvaluationRun, EvaluationSuiteRevision, User
from app.schemas import (
    EvaluationCaseCreate,
    EvaluationCaseOut,
    EvaluationCaseUpdate,
    EvaluationResultOut,
    EvaluationRunCreate,
    EvaluationRunDetailOut,
    EvaluationRunOut,
)


router = APIRouter()


def _json_loads(value: str | None, default):
    try:
        return json.loads(value or "")
    except (json.JSONDecodeError, TypeError):
        return default


def case_out(item: EvaluationCase) -> EvaluationCaseOut:
    return EvaluationCaseOut(
        id=item.id,
        name=item.name,
        agent_role=str(getattr(item.agent_role, "value", item.agent_role)),
        input_text=item.input_text,
        expected_keywords=_json_loads(item.expected_keywords_json, []),
        forbidden_keywords=_json_loads(item.forbidden_keywords_json, []),
        rubric=item.rubric,
        minimum_score=item.minimum_score,
        weight=item.weight,
        enabled=item.enabled,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def result_out(item: EvaluationResult) -> EvaluationResultOut:
    case = _json_loads(item.case_snapshot_json, {})
    agent = _json_loads(item.agent_snapshot_json, {})
    details = _json_loads(item.details_json, {})
    return EvaluationResultOut(
        id=item.id,
        case_id=item.case_id,
        case_name=str(case.get("name") or f"Case {item.case_id}"),
        agent_role=str(case.get("agent_role") or agent.get("role") or ""),
        agent_name=str(agent.get("name") or "Unassigned Agent"),
        agent_version=int(agent["version"]) if agent.get("version") is not None else None,
        model=str(agent.get("model") or ""),
        input_text=str(case.get("input_text") or ""),
        expected_keywords=list(case.get("expected_keywords") or []),
        forbidden_keywords=list(case.get("forbidden_keywords") or []),
        rubric=str(case.get("rubric") or ""),
        answer=item.answer,
        score=item.score,
        baseline_answer=item.baseline_answer,
        baseline_score=item.baseline_score,
        score_delta=item.score_delta,
        dimensions=_json_loads(item.dimension_scores_json, {}),
        baseline_dimensions=_json_loads(item.baseline_dimension_scores_json, {}),
        score_source=item.score_source,
        latency_ms=item.latency_ms,
        regressed=item.regressed,
        passed=item.passed,
        matched_keywords=list(details.get("matched") or []),
        missing_keywords=list(details.get("missing") or []),
        forbidden_hits=list(details.get("forbidden_hits") or []),
        judge_reason=str(details.get("judge_reason") or ""),
        judge_error=str(details.get("judge_error") or ""),
        error=item.error,
        created_at=item.created_at,
    )


def run_out(item: EvaluationRun, db: Session) -> EvaluationRunOut:
    revision = db.get(EvaluationSuiteRevision, item.suite_revision_id) if item.suite_revision_id else None
    raw_agents = _json_loads(item.agent_snapshot_json, {})
    agents = [
        {
            "id": int(agent["id"]),
            "name": str(agent.get("name") or role),
            "role": str(agent.get("role") or role),
            "version": int(agent.get("version") or 1),
            "model": str(agent.get("model") or ""),
        }
        for role, agent in raw_agents.items()
        if isinstance(agent, dict) and agent.get("id") is not None
    ]
    return EvaluationRunOut(
        id=item.id,
        request_id=item.request_id,
        status=item.status,
        suite_revision=revision.version if revision else None,
        baseline_run_id=item.baseline_run_id,
        total_cases=item.total_cases,
        completed_cases=item.completed_cases,
        progress_percent=round(item.completed_cases / max(item.total_cases, 1) * 100),
        passed_cases=item.passed_cases,
        average_score=item.average_score,
        baseline_average_score=item.baseline_average_score,
        score_delta=item.score_delta,
        gate_passed=item.gate_passed,
        gate_failures=_json_loads(item.gate_failures_json, []),
        dimension_averages=_json_loads(item.dimension_averages_json, {}),
        baseline_dimension_averages=_json_loads(item.baseline_dimension_averages_json, {}),
        agent_snapshots=agents,
        error=item.error,
        attempt_count=item.attempt_count,
        max_attempts=item.max_attempts,
        retryable=item.status in {"FAILED", "CANCELLED"},
        created_by_user_id=item.created_by_user_id,
        created_at=item.created_at,
        started_at=item.started_at,
        finished_at=item.finished_at,
    )


def detail_out(item: EvaluationRun, db: Session) -> EvaluationRunDetailOut:
    summary = run_out(item, db)
    results = list(
        db.scalars(
            select(EvaluationResult)
            .where(EvaluationResult.run_id == item.id)
            .order_by(EvaluationResult.case_id)
        )
    )
    return EvaluationRunDetailOut(**summary.model_dump(), results=[result_out(result) for result in results])


def _get_run(run_id: int, db: Session) -> EvaluationRun:
    item = db.get(EvaluationRun, run_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation run not found")
    return item


@router.get("/cases", response_model=list[EvaluationCaseOut])
def list_evaluation_cases(
    enabled_only: bool = False,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[EvaluationCaseOut]:
    stmt = select(EvaluationCase)
    if enabled_only:
        stmt = stmt.where(EvaluationCase.enabled.is_(True))
    return [case_out(item) for item in db.scalars(stmt.order_by(EvaluationCase.id))]


@router.post("/cases", response_model=EvaluationCaseOut, status_code=status.HTTP_201_CREATED)
def create_evaluation_case(
    payload: EvaluationCaseCreate,
    request: Request,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> EvaluationCaseOut:
    item = EvaluationCase(
        name=payload.name.strip(),
        agent_role=payload.agent_role.value,
        input_text=payload.input_text.strip(),
        expected_keywords_json=json.dumps(payload.expected_keywords, ensure_ascii=False),
        forbidden_keywords_json=json.dumps(payload.forbidden_keywords, ensure_ascii=False),
        rubric=payload.rubric.strip(),
        minimum_score=payload.minimum_score,
        weight=payload.weight,
        enabled=payload.enabled,
        created_by_user_id=current_admin.id,
    )
    db.add(item)
    db.flush()
    record_audit(
        db,
        "evaluation.case_create",
        current_admin.id,
        resource_type="evaluation_case",
        resource_id=item.id,
        details={"agent_role": payload.agent_role.value},
        request=request,
    )
    db.commit()
    db.refresh(item)
    return case_out(item)


@router.patch("/cases/{case_id}", response_model=EvaluationCaseOut)
def update_evaluation_case(
    case_id: int,
    payload: EvaluationCaseUpdate,
    request: Request,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> EvaluationCaseOut:
    item = db.get(EvaluationCase, case_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation case not found")
    item.name = payload.name.strip()
    item.agent_role = payload.agent_role.value
    item.input_text = payload.input_text.strip()
    item.expected_keywords_json = json.dumps(payload.expected_keywords, ensure_ascii=False)
    item.forbidden_keywords_json = json.dumps(payload.forbidden_keywords, ensure_ascii=False)
    item.rubric = payload.rubric.strip()
    item.minimum_score = payload.minimum_score
    item.weight = payload.weight
    item.enabled = payload.enabled
    record_audit(
        db,
        "evaluation.case_update",
        current_admin.id,
        resource_type="evaluation_case",
        resource_id=item.id,
        details={"agent_role": payload.agent_role.value, "enabled": payload.enabled},
        request=request,
    )
    db.commit()
    db.refresh(item)
    return case_out(item)


@router.delete("/cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_evaluation_case(
    case_id: int,
    request: Request,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> None:
    item = db.get(EvaluationCase, case_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation case not found")
    item.enabled = False
    record_audit(
        db,
        "evaluation.case_archive",
        current_admin.id,
        resource_type="evaluation_case",
        resource_id=item.id,
        request=request,
    )
    db.commit()


def _enqueue(
    payload: EvaluationRunCreate,
    request: Request,
    response: Response,
    current_admin: User,
    db: Session,
) -> EvaluationRunOut:
    try:
        try:
            item, created = enqueue_evaluation_run(
                db,
                request_id=payload.request_id,
                user_id=current_admin.id,
                baseline_run_id=payload.baseline_run_id,
            )
        except IntegrityError:
            db.rollback()
            item, created = enqueue_evaluation_run(
                db,
                request_id=payload.request_id,
                user_id=current_admin.id,
                baseline_run_id=payload.baseline_run_id,
            )
    except EvaluationRequestConflict as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if created:
        record_audit(
            db,
            "evaluation.run_queued",
            current_admin.id,
            resource_type="evaluation_run",
            resource_id=item.id,
            details={
                "request_id": item.request_id,
                "suite_revision_id": item.suite_revision_id,
                "baseline_run_id": item.baseline_run_id,
            },
            request=request,
        )
    db.commit()
    db.refresh(item)
    response.headers["Location"] = str(request.url_for("get_evaluation_run", run_id=item.id))
    return run_out(item, db)


@router.post("/runs", response_model=EvaluationRunOut, status_code=status.HTTP_202_ACCEPTED)
def create_evaluation_run(
    payload: EvaluationRunCreate,
    request: Request,
    response: Response,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> EvaluationRunOut:
    return _enqueue(payload, request, response, current_admin, db)


@router.post("/run", response_model=EvaluationRunOut, status_code=status.HTTP_202_ACCEPTED)
def execute_evaluation_legacy(
    request: Request,
    response: Response,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> EvaluationRunOut:
    payload = EvaluationRunCreate(request_id=f"legacy-{uuid4().hex}")
    return _enqueue(payload, request, response, current_admin, db)


@router.get("/runs", response_model=list[EvaluationRunOut])
def list_evaluation_runs(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[EvaluationRunOut]:
    items = list(db.scalars(select(EvaluationRun).order_by(EvaluationRun.created_at.desc()).limit(100)))
    return [run_out(item, db) for item in items]


@router.get("/runs/{run_id}", response_model=EvaluationRunDetailOut, name="get_evaluation_run")
def get_evaluation_run(
    run_id: int,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> EvaluationRunDetailOut:
    return detail_out(_get_run(run_id, db), db)


@router.post("/runs/{run_id}/cancel", response_model=EvaluationRunOut)
def cancel_run(
    run_id: int,
    request: Request,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> EvaluationRunOut:
    item = _get_run(run_id, db)
    try:
        cancel_evaluation_run(db, item)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    record_audit(
        db,
        "evaluation.run_cancel",
        current_admin.id,
        resource_type="evaluation_run",
        resource_id=item.id,
        request=request,
    )
    db.commit()
    db.refresh(item)
    return run_out(item, db)


@router.post("/runs/{run_id}/retry", response_model=EvaluationRunOut, status_code=status.HTTP_202_ACCEPTED)
def retry_run(
    run_id: int,
    request: Request,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> EvaluationRunOut:
    item = _get_run(run_id, db)
    try:
        retry_evaluation_run(db, item)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    record_audit(
        db,
        "evaluation.run_retry",
        current_admin.id,
        resource_type="evaluation_run",
        resource_id=item.id,
        request=request,
    )
    db.commit()
    db.refresh(item)
    return run_out(item, db)
