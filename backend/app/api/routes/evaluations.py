import json
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
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
from app.models import (
    Agent,
    AgentEvaluationRelease,
    EvaluationCase,
    EvaluationResult,
    EvaluationRun,
    EvaluationSuiteRevision,
    Notification,
    User,
    UserRole,
)
from app.schemas import (
    AgentEvaluationReleaseOut,
    EvaluationCaseCreate,
    EvaluationCaseOut,
    EvaluationCaseUpdate,
    EvaluationFeedbackCandidateOut,
    EvaluationFeedbackDismissRequest,
    EvaluationFeedbackPromoteRequest,
    EvaluationResultOut,
    EvaluationReleaseRequest,
    EvaluationRunCreate,
    EvaluationRunDetailOut,
    EvaluationRunOut,
)
from app.services.evaluation_releases import (
    EvaluationReleaseConflict,
    publish_candidate_release,
    rollback_candidate_release,
)
from app.services.evaluation_feedback import (
    EvaluationFeedbackConflict,
    dismiss_feedback_candidate,
    list_feedback_candidates,
    promote_feedback_to_case,
    reviewed_feedback_candidate,
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


def feedback_candidate_out(data: dict) -> EvaluationFeedbackCandidateOut:
    return EvaluationFeedbackCandidateOut(**data)


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


def release_out(
    item: AgentEvaluationRelease,
    db: Session,
) -> AgentEvaluationReleaseOut:
    agent = db.get(Agent, item.agent_id)
    return AgentEvaluationReleaseOut(
        id=item.id,
        evaluation_run_id=item.evaluation_run_id,
        agent_id=item.agent_id,
        agent_name=agent.name if agent else f"Agent #{item.agent_id}",
        candidate_version_id=item.candidate_version_id,
        candidate_version=item.candidate_version,
        previous_version=item.previous_version,
        expected_current_version=item.expected_current_version,
        status=item.status,
        published_by_user_id=item.published_by_user_id,
        published_at=item.published_at,
        rollback_version=item.rollback_version,
        rolled_back_by_user_id=item.rolled_back_by_user_id,
        rolled_back_at=item.rolled_back_at,
    )


def run_out(
    item: EvaluationRun,
    db: Session,
    releases_by_run: dict[int, AgentEvaluationRelease] | None = None,
) -> EvaluationRunOut:
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
    release = (
        releases_by_run.get(item.id)
        if releases_by_run is not None
        else db.scalar(
            select(AgentEvaluationRelease).where(
                AgentEvaluationRelease.evaluation_run_id == item.id
            )
        )
    )
    candidate_agent_name = next(
        (
            str(agent.get("name") or "")
            for agent in raw_agents.values()
            if isinstance(agent, dict) and agent.get("id") == item.candidate_agent_id
        ),
        "",
    )
    return EvaluationRunOut(
        id=item.id,
        request_id=item.request_id,
        status=item.status,
        suite_revision=revision.version if revision else None,
        baseline_run_id=item.baseline_run_id,
        candidate_agent_id=item.candidate_agent_id,
        candidate_agent_name=candidate_agent_name,
        candidate_version_id=item.candidate_version_id,
        candidate_version=item.candidate_version,
        expected_current_version=item.expected_current_version,
        release=release_out(release, db) if release else None,
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


@router.get("/feedback", response_model=list[EvaluationFeedbackCandidateOut])
def list_evaluation_feedback(
    status_filter: str = Query(default="PENDING", alias="status"),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[EvaluationFeedbackCandidateOut]:
    try:
        rows = list_feedback_candidates(db, status_filter.strip().upper())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return [feedback_candidate_out(row) for row in rows]


@router.post(
    "/feedback/{feedback_id}/promote",
    response_model=EvaluationFeedbackCandidateOut,
    status_code=status.HTTP_201_CREATED,
)
def promote_evaluation_feedback(
    feedback_id: int,
    payload: EvaluationFeedbackPromoteRequest,
    request: Request,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> EvaluationFeedbackCandidateOut:
    values = payload.model_dump(exclude={"request_id"})
    try:
        try:
            review, created = promote_feedback_to_case(
                db,
                feedback_id=feedback_id,
                request_id=payload.request_id,
                user_id=current_admin.id,
                case_values=values,
            )
        except IntegrityError:
            db.rollback()
            review, created = promote_feedback_to_case(
                db,
                feedback_id=feedback_id,
                request_id=payload.request_id,
                user_id=current_admin.id,
                case_values=values,
            )
    except EvaluationFeedbackConflict as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if created:
        record_audit(
            db,
            "evaluation.feedback_convert",
            current_admin.id,
            resource_type="evaluation_feedback_review",
            resource_id=review.id,
            details={
                "feedback_id": feedback_id,
                "evaluation_case_id": review.evaluation_case_id,
                "agent_id": review.agent_id,
                "agent_role": review.agent_role,
            },
            request=request,
        )
        db.commit()
        db.refresh(review)
    return feedback_candidate_out(reviewed_feedback_candidate(review))


@router.post(
    "/feedback/{feedback_id}/dismiss",
    response_model=EvaluationFeedbackCandidateOut,
)
def dismiss_evaluation_feedback(
    feedback_id: int,
    payload: EvaluationFeedbackDismissRequest,
    request: Request,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> EvaluationFeedbackCandidateOut:
    try:
        try:
            review, created = dismiss_feedback_candidate(
                db,
                feedback_id=feedback_id,
                request_id=payload.request_id,
                user_id=current_admin.id,
                reason=payload.reason,
            )
        except IntegrityError:
            db.rollback()
            review, created = dismiss_feedback_candidate(
                db,
                feedback_id=feedback_id,
                request_id=payload.request_id,
                user_id=current_admin.id,
                reason=payload.reason,
            )
    except EvaluationFeedbackConflict as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if created:
        record_audit(
            db,
            "evaluation.feedback_dismiss",
            current_admin.id,
            resource_type="evaluation_feedback_review",
            resource_id=review.id,
            details={
                "feedback_id": feedback_id,
                "agent_id": review.agent_id,
                "agent_role": review.agent_role,
                "reason_chars": len(review.resolution_note),
            },
            request=request,
        )
        db.commit()
        db.refresh(review)
    return feedback_candidate_out(reviewed_feedback_candidate(review))


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
                candidate_version_id=payload.candidate_version_id,
            )
        except IntegrityError:
            db.rollback()
            item, created = enqueue_evaluation_run(
                db,
                request_id=payload.request_id,
                user_id=current_admin.id,
                baseline_run_id=payload.baseline_run_id,
                candidate_version_id=payload.candidate_version_id,
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
                "candidate_agent_id": item.candidate_agent_id,
                "candidate_version": item.candidate_version,
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
    run_ids = [item.id for item in items]
    releases = (
        list(
            db.scalars(
                select(AgentEvaluationRelease).where(
                    AgentEvaluationRelease.evaluation_run_id.in_(run_ids)
                )
            )
        )
        if run_ids
        else []
    )
    releases_by_run = {release.evaluation_run_id: release for release in releases}
    return [run_out(item, db, releases_by_run) for item in items]


@router.get("/runs/{run_id}", response_model=EvaluationRunDetailOut, name="get_evaluation_run")
def get_evaluation_run(
    run_id: int,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> EvaluationRunDetailOut:
    return detail_out(_get_run(run_id, db), db)


def _notify_release_admins(
    db: Session,
    *,
    title: str,
    content: str,
    sent_at,
) -> None:
    recipients = list(
        db.scalars(
            select(User).where(
                User.role == UserRole.admin,
                User.is_active.is_(True),
            )
        )
    )
    for recipient in recipients:
        db.add(
            Notification(
                user_id=recipient.id,
                recipient_user_id=recipient.id,
                recipient_email=recipient.email,
                title=title,
                content=content,
                channel="in_app",
                status="SENT",
                sent_at=sent_at,
            )
        )


@router.post(
    "/runs/{run_id}/publish",
    response_model=AgentEvaluationReleaseOut,
    status_code=status.HTTP_201_CREATED,
)
def publish_evaluation_run(
    run_id: int,
    payload: EvaluationReleaseRequest,
    request: Request,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AgentEvaluationReleaseOut:
    try:
        release, created = publish_candidate_release(
            db,
            run_id=run_id,
            request_id=payload.request_id,
            user_id=current_admin.id,
        )
    except IntegrityError:
        db.rollback()
        try:
            release, created = publish_candidate_release(
                db,
                run_id=run_id,
                request_id=payload.request_id,
                user_id=current_admin.id,
            )
        except EvaluationReleaseConflict as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except EvaluationReleaseConflict as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if created:
        record_audit(
            db,
            "evaluation.release_publish",
            current_admin.id,
            resource_type="agent_evaluation_release",
            resource_id=release.id,
            details={
                "evaluation_run_id": release.evaluation_run_id,
                "agent_id": release.agent_id,
                "candidate_version": release.candidate_version,
                "previous_version": release.previous_version,
            },
            request=request,
        )
        _notify_release_admins(
            db,
            title="Agent 候选版本已发布",
            content=(
                f"评测运行 #{release.evaluation_run_id} 已通过门禁并发布 "
                f"Agent #{release.agent_id} v{release.candidate_version}，"
                f"原生产版本为 v{release.previous_version}。"
            ),
            sent_at=release.published_at,
        )
        db.commit()
        db.refresh(release)
    return release_out(release, db)


@router.post(
    "/releases/{release_id}/rollback",
    response_model=AgentEvaluationReleaseOut,
)
def rollback_evaluation_release(
    release_id: int,
    payload: EvaluationReleaseRequest,
    request: Request,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AgentEvaluationReleaseOut:
    try:
        release, created = rollback_candidate_release(
            db,
            release_id=release_id,
            request_id=payload.request_id,
            user_id=current_admin.id,
        )
    except IntegrityError:
        db.rollback()
        try:
            release, created = rollback_candidate_release(
                db,
                release_id=release_id,
                request_id=payload.request_id,
                user_id=current_admin.id,
            )
        except EvaluationReleaseConflict as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except EvaluationReleaseConflict as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if created:
        record_audit(
            db,
            "evaluation.release_rollback",
            current_admin.id,
            resource_type="agent_evaluation_release",
            resource_id=release.id,
            details={
                "evaluation_run_id": release.evaluation_run_id,
                "agent_id": release.agent_id,
                "candidate_version": release.candidate_version,
                "rollback_version": release.rollback_version,
            },
            request=request,
        )
        _notify_release_admins(
            db,
            title="Agent 发布已回滚",
            content=(
                f"评测发布 #{release.id} 已回滚，Agent #{release.agent_id} "
                f"当前为恢复版本 v{release.rollback_version}。"
            ),
            sent_at=release.rolled_back_at,
        )
        db.commit()
        db.refresh(release)
    return release_out(release, db)


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
