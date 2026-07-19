import asyncio
import json
from datetime import datetime, timezone
from io import BytesIO

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.orchestration import (
    SPECIALIST_CAPABILITY_LABELS,
    build_specialist_capability_catalog,
    infer_required_specialist_capabilities,
)
from app.agent.team_performance import TeamPerformanceProfile, build_team_performance_profile
from app.api.deps import get_current_user
from app.api.routes.projects import get_project_for_user
from app.core.audit import record_audit
from app.core.config import get_settings
from app.core.database import SessionLocal, get_db
from app.langgraph.workflow import (
    initial_state,
    prepare_specialist_replan,
    prepare_specialist_retry,
    record_workflow_event,
    select_execution_plan_deliberation,
    select_execution_plan_version,
    snapshot_agent_configs,
    validate_execution_plan_for_dispatch,
)
from app.models import Project, Report, User, WorkflowArtifactPublication, WorkflowEvent, WorkflowRun, WorkflowSagaStep, WorkflowStatus
from app.schemas import WorkflowContinueRequest, WorkflowEventResponse, WorkflowPauseRequest, WorkflowPreflightRequest, WorkflowPreflightResponse, WorkflowPublicationOut, WorkflowPublishRequest, WorkflowRequest, WorkflowResponse, WorkflowRetryRequest, WorkflowSagaStepOut, WorkflowSpecialistPreflightOut
from app.services.billing import InsufficientTokensError, apply_token_change
from app.services.workflows import finish_workflow_compensation, refund_workflow_charge
from app.rag.service import DuplicateDocumentError, queue_document
from app.workflow_events import public_workflow_event_payload


router = APIRouter()
settings = get_settings()
TERMINAL_STATUSES = {WorkflowStatus.completed, WorkflowStatus.failed, WorkflowStatus.cancelled}
ACTIVE_STATUSES = {
    WorkflowStatus.queued,
    WorkflowStatus.running,
    WorkflowStatus.cancelling,
    WorkflowStatus.compensating,
    WorkflowStatus.compensation_failed,
    WorkflowStatus.paused,
}
WORKFLOW_NODE_ORDER = {
    "requirement": 0,
    "product": 1,
    "architect": 2,
    "planning": 3,
    "plan_review": 4,
    "specialists": 5,
    "specialist_review": 5,
    "quality_gate": 6,
    "quality_review": 7,
    "project_manager": 8,
    "tester": 9,
    "report": 10,
    "completed": 11,
}
RETRY_CHECKPOINT_OUTPUTS = {
    "project_manager": {
        "state_defaults": {"tasks": [], "tests": {}, "report": ""},
        "document_types": {"PROJECT_PLAN", "TEST_PLAN", "FINAL_REPORT"},
        "message_roles": {"project_manager_agent", "tester_agent", "report_generator"},
    },
    "tester": {
        "state_defaults": {"tests": {}, "report": ""},
        "document_types": {"TEST_PLAN", "FINAL_REPORT"},
        "message_roles": {"tester_agent", "report_generator"},
    },
    "report": {
        "state_defaults": {"report": ""},
        "document_types": {"FINAL_REPORT"},
        "message_roles": {"report_generator"},
    },
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_response(workflow: WorkflowRun) -> WorkflowResponse:
    state = json.loads(workflow.state_json)
    state.pop("agent_snapshot", None)
    return WorkflowResponse(
        workflow_id=workflow.id,
        project_id=workflow.project_id,
        parent_workflow_id=workflow.parent_workflow_id,
        retry_from_node=workflow.retry_from_node,
        retry_sequence=workflow.retry_sequence,
        pause_requested_at=workflow.pause_requested_at,
        pause_requested_by_user_id=workflow.pause_requested_by_user_id,
        pause_reason=workflow.pause_reason,
        intervention_count=workflow.intervention_count,
        status=workflow.status,
        current_node=workflow.current_node,
        state=state,
        attempt_count=workflow.attempt_count,
        max_attempts=workflow.max_attempts,
        error=workflow.error,
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
        started_at=workflow.started_at,
        finished_at=workflow.finished_at,
    )


def workflow_state(workflow: WorkflowRun) -> dict:
    try:
        state = json.loads(workflow.state_json or "{}")
    except (json.JSONDecodeError, TypeError):
        state = {}
    return state if isinstance(state, dict) else {}


def build_workflow_preflight(
    agent_snapshot: dict,
    user_input: str,
    team_performance_profile: TeamPerformanceProfile,
) -> WorkflowPreflightResponse:
    minimum_required = 2
    catalog = build_specialist_capability_catalog(agent_snapshot)
    eligible = [profile for profile in catalog if profile.eligible]
    required = infer_required_specialist_capabilities(user_input)
    available = {
        capability
        for profile in eligible
        for capability in profile.capabilities
    }
    missing = required - available
    blockers: list[str] = []
    if len(eligible) < minimum_required:
        blockers.append(
            f"至少需要 {minimum_required} 个可用专业 Agent，当前仅 {len(eligible)} 个。"
        )
    if missing:
        labels = "、".join(SPECIALIST_CAPABILITY_LABELS[item] for item in sorted(missing))
        blockers.append(f"当前团队缺少所需能力：{labels}。")
    return WorkflowPreflightResponse(
        ready=not blockers,
        required_capabilities=sorted(required),
        available_capabilities=sorted(available),
        eligible_count=len(eligible),
        minimum_required=minimum_required,
        specialists=[
            WorkflowSpecialistPreflightOut.model_validate(profile.model_dump(mode="json"))
            for profile in catalog
        ],
        blockers=blockers,
        team_performance_profile=team_performance_profile,
    )


def retry_checkpoint_state(db: Session, workflow: WorkflowRun) -> dict:
    state = workflow_state(workflow)

    latest_started_node = db.scalar(
        select(WorkflowEvent.node)
        .where(
            WorkflowEvent.workflow_id == workflow.id,
            WorkflowEvent.event_type == "NODE_STARTED",
        )
        .order_by(WorkflowEvent.id.desc())
        .limit(1)
    )
    retry_index = WORKFLOW_NODE_ORDER.get(workflow.current_node)
    started_index = WORKFLOW_NODE_ORDER.get(latest_started_node or "")
    if retry_index is None or started_index is None or started_index <= retry_index:
        return state

    cleanup = RETRY_CHECKPOINT_OUTPUTS.get(workflow.current_node)
    if not cleanup:
        return state
    for key, default in cleanup["state_defaults"].items():
        state[key] = default
    documents = state.get("documents")
    if isinstance(documents, list):
        state["documents"] = [
            item
            for item in documents
            if not isinstance(item, dict) or item.get("type") not in cleanup["document_types"]
        ]
    messages = state.get("messages")
    if isinstance(messages, list):
        state["messages"] = [
            item
            for item in messages
            if not isinstance(item, dict) or item.get("role") not in cleanup["message_roles"]
        ]
    return state


def get_owned_workflow(workflow_id: int, current_user: User, db: Session, *, write: bool = False) -> WorkflowRun:
    workflow = db.get(WorkflowRun, workflow_id)
    if not workflow or workflow.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    get_project_for_user(workflow.project_id, current_user, db, write=write)
    return workflow


def to_event_response(event: WorkflowEvent) -> WorkflowEventResponse:
    try:
        payload = json.loads(event.payload_json)
    except (json.JSONDecodeError, TypeError):
        payload = {}
    return WorkflowEventResponse(
        id=event.id,
        workflow_id=event.workflow_id,
        node=event.node,
        event_type=event.event_type,
        message=event.message,
        payload=public_workflow_event_payload(payload) if isinstance(payload, dict) else {},
        created_at=event.created_at,
    )


@router.post("/run", response_model=WorkflowResponse, status_code=status.HTTP_202_ACCEPTED)
async def run_workflow(
    payload: WorkflowRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowResponse:
    project = get_project_for_user(payload.project_id, current_user, db, write=True)
    existing = db.scalar(select(WorkflowRun).where(WorkflowRun.request_id == payload.request_id))
    if existing:
        if existing.user_id != current_user.id or existing.project_id != project.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Workflow request ID is already in use")
        return to_response(existing)

    project = db.scalar(select(Project).where(Project.id == project.id).with_for_update())
    existing = db.scalar(select(WorkflowRun).where(WorkflowRun.request_id == payload.request_id))
    if existing:
        return to_response(existing)
    active = db.scalar(
        select(WorkflowRun).where(
            WorkflowRun.project_id == project.id,
            WorkflowRun.status.in_(ACTIVE_STATUSES),
        )
    )
    if active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Project already has an active workflow: {active.id}",
        )
    agent_snapshot = snapshot_agent_configs(db, current_user.role)
    specialist_roles = [
        profile.role for profile in build_specialist_capability_catalog(agent_snapshot)
    ]
    team_performance_profile = build_team_performance_profile(
        db,
        project.id,
        specialist_roles,
        current_agent_snapshot=agent_snapshot,
    )
    preflight = build_workflow_preflight(
        agent_snapshot,
        payload.user_input,
        team_performance_profile,
    )
    if not preflight.ready:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=" ".join(preflight.blockers),
        )
    try:
        billing = apply_token_change(
            db,
            current_user.id,
            -settings.workflow_token_cost,
            "CONSUME",
            idempotency_key=f"workflow:{current_user.id}:{payload.request_id}",
            reference_type="workflow",
            reference_id=payload.request_id,
            description="多 Agent 项目工作流",
        )
    except InsufficientTokensError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc)) from exc

    workflow = WorkflowRun(
        project_id=project.id,
        user_id=current_user.id,
        status=WorkflowStatus.queued,
        current_node="requirement",
        state_json=json.dumps(
            initial_state(
                project,
                payload.user_input,
                agent_snapshot,
                require_plan_approval=payload.require_plan_approval,
                team_performance_profile=team_performance_profile.model_dump(mode="json"),
            ),
            ensure_ascii=False,
        ),
        request_id=payload.request_id,
        billing_transaction_id=billing.id,
        pause_before_report=payload.pause_before_report,
        max_attempts=settings.workflow_max_attempts,
    )
    db.add(workflow)
    db.flush()
    record_workflow_event(
        db,
        workflow,
        "TEAM_PERFORMANCE_SNAPSHOTTED",
        "Same-project specialist performance evidence frozen",
        payload={
            "workflow_count": team_performance_profile.workflow_count,
            "branch_sample_count": team_performance_profile.branch_sample_count,
            "excluded_branch_sample_count": team_performance_profile.excluded_branch_sample_count,
            "observed_role_count": team_performance_profile.observed_role_count,
            "sufficient_role_count": team_performance_profile.sufficient_role_count,
        },
    )
    record_workflow_event(db, workflow, "QUEUED", "Workflow queued")
    record_audit(
        db,
        "workflow.queued",
        current_user.id,
        project.id,
        "workflow",
        workflow.id,
        {
            "request_id": payload.request_id,
            "require_plan_approval": payload.require_plan_approval,
        },
        request,
    )
    db.commit()
    db.refresh(workflow)
    return to_response(workflow)


@router.post("/preflight", response_model=WorkflowPreflightResponse)
def preflight_workflow(
    payload: WorkflowPreflightRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowPreflightResponse:
    project = get_project_for_user(payload.project_id, current_user, db, write=True)
    agent_snapshot = snapshot_agent_configs(db, current_user.role)
    specialist_roles = [
        profile.role for profile in build_specialist_capability_catalog(agent_snapshot)
    ]
    return build_workflow_preflight(
        agent_snapshot,
        payload.user_input,
        build_team_performance_profile(
            db,
            project.id,
            specialist_roles,
            current_agent_snapshot=agent_snapshot,
        ),
    )


@router.get("", response_model=list[WorkflowResponse])
def list_workflows(
    project_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[WorkflowResponse]:
    stmt = select(WorkflowRun).where(WorkflowRun.user_id == current_user.id)
    if project_id is not None:
        get_project_for_user(project_id, current_user, db)
        stmt = stmt.where(WorkflowRun.project_id == project_id)
    workflows = list(db.scalars(stmt.order_by(WorkflowRun.created_at.desc()).limit(100)))
    return [to_response(item) for item in workflows]


@router.get("/{workflow_id}", response_model=WorkflowResponse)
def get_workflow(
    workflow_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowResponse:
    return to_response(get_owned_workflow(workflow_id, current_user, db))


@router.get("/{workflow_id}/saga-steps", response_model=list[WorkflowSagaStepOut])
def list_workflow_saga_steps(
    workflow_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[WorkflowSagaStep]:
    get_owned_workflow(workflow_id, current_user, db)
    return list(
        db.scalars(
            select(WorkflowSagaStep)
            .where(WorkflowSagaStep.workflow_id == workflow_id)
            .order_by(WorkflowSagaStep.sequence, WorkflowSagaStep.id)
        )
    )


@router.get("/{workflow_id}/events/history", response_model=list[WorkflowEventResponse])
def list_workflow_event_history(
    workflow_id: int,
    limit: int = Query(default=100, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[WorkflowEventResponse]:
    get_owned_workflow(workflow_id, current_user, db)
    events = list(
        db.scalars(
            select(WorkflowEvent)
            .where(WorkflowEvent.workflow_id == workflow_id)
            .order_by(WorkflowEvent.id.desc())
            .limit(limit)
        )
    )
    return [to_event_response(event) for event in reversed(events)]


@router.get("/{workflow_id}/events")
async def stream_workflow_events(
    workflow_id: int,
    last_event_id: int = 0,
    header_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    get_owned_workflow(workflow_id, current_user, db)
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
                workflow = event_db.get(WorkflowRun, workflow_id)
                event_user = event_db.get(User, user_id)
                project = event_db.get(Project, workflow.project_id) if workflow else None
                if (
                    not workflow
                    or workflow.user_id != user_id
                    or not event_user
                    or not event_user.is_active
                    or not project
                ):
                    return
                try:
                    get_project_for_user(project.id, event_user, event_db)
                except HTTPException:
                    return
                events = list(
                    event_db.scalars(
                        select(WorkflowEvent)
                        .where(WorkflowEvent.workflow_id == workflow_id, WorkflowEvent.id > cursor)
                        .order_by(WorkflowEvent.id)
                        .limit(100)
                    )
                )
                terminal = workflow.status in TERMINAL_STATUSES or workflow.status in {
                    WorkflowStatus.paused,
                    WorkflowStatus.compensation_failed,
                }
                for event in events:
                    cursor = event.id
                    data = to_event_response(event).model_dump_json()
                    yield f"id: {event.id}\nevent: workflow\ndata: {data}\n\n"
                if events:
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


@router.post("/{workflow_id}/pause", response_model=WorkflowResponse)
def pause_workflow(
    workflow_id: int,
    payload: WorkflowPauseRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowResponse:
    workflow = db.scalar(select(WorkflowRun).where(WorkflowRun.id == workflow_id).with_for_update())
    if not workflow or workflow.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    get_project_for_user(workflow.project_id, current_user, db, write=True)
    if workflow.pause_request_id == payload.request_id:
        return to_response(workflow)
    if workflow.pause_requested_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Workflow already has a pending pause request")
    if workflow.status not in {WorkflowStatus.queued, WorkflowStatus.running}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only queued or running workflows can be paused")

    workflow.pause_requested_at = utc_now()
    workflow.pause_requested_by_user_id = current_user.id
    workflow.pause_reason = payload.reason.strip()
    workflow.pause_request_id = payload.request_id
    record_workflow_event(
        db,
        workflow,
        "PAUSE_REQUESTED",
        "Operator requested a safe-boundary pause",
        payload={"requested_by_user_id": current_user.id, "reason_chars": len(workflow.pause_reason)},
    )
    if workflow.status == WorkflowStatus.queued:
        workflow.status = WorkflowStatus.paused
        workflow.intervention_count += 1
        record_workflow_event(
            db,
            workflow,
            "PAUSED",
            "Workflow paused before worker execution",
            payload={
                "approval_gate": "operator",
                "requested_by_user_id": current_user.id,
                "reason_chars": len(workflow.pause_reason),
                "intervention_count": workflow.intervention_count,
            },
        )
        record_audit(
            db,
            "workflow.operator_paused",
            current_user.id,
            workflow.project_id,
            "workflow",
            workflow.id,
            {
                "reason_chars": len(workflow.pause_reason),
                "intervention_count": workflow.intervention_count,
            },
            request,
        )
    record_audit(
        db,
        "workflow.pause_requested",
        current_user.id,
        workflow.project_id,
        "workflow",
        workflow.id,
        {"request_id": payload.request_id, "reason_chars": len(workflow.pause_reason)},
        request,
    )
    db.commit()
    db.refresh(workflow)
    return to_response(workflow)


@router.post("/continue", response_model=WorkflowResponse, status_code=status.HTTP_202_ACCEPTED)
async def continue_workflow(
    payload: WorkflowContinueRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowResponse:
    workflow = db.scalar(select(WorkflowRun).where(WorkflowRun.id == payload.workflow_id).with_for_update())
    if not workflow or workflow.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    get_project_for_user(workflow.project_id, current_user, db, write=True)
    if workflow.status != WorkflowStatus.paused:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Workflow is not waiting for human confirmation")

    feedback = payload.human_feedback.strip()
    operator_pause = workflow.pause_requested_at is not None
    gate = "operator" if operator_pause else workflow.current_node
    reviewed_plan_version: int | None = None
    if payload.plan_version is not None and (operator_pause or workflow.current_node != "plan_review"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Plan version can only be selected during plan review",
        )
    if operator_pause:
        if not feedback:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Resume instruction is required after an operator pause",
            )
        state = workflow_state(workflow)
        interventions = state.get("interventions")
        if not isinstance(interventions, list):
            interventions = []
        state["interventions"] = [
            *interventions,
            {
                "reason": workflow.pause_reason,
                "instruction": feedback,
                "resume_from_node": workflow.current_node,
            },
        ][-10:]
        if workflow.current_node == "quality_review":
            state["revision_feedback"] = feedback
            state["manual_revision_count"] = int(state.get("manual_revision_count", 0)) + 1
            workflow.current_node = "specialists"
            workflow.pause_before_report = True
        elif workflow.current_node == "plan_review":
            try:
                selected_plan, reviewed_plan_version = select_execution_plan_version(state)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=str(exc),
                ) from exc
            selected_deliberation = select_execution_plan_deliberation(
                state,
                reviewed_plan_version,
            )
            state["execution_plan"] = selected_plan
            state["plan_version"] = reviewed_plan_version
            state["plan_deliberation"] = selected_deliberation
            state["plan_approved"] = False
            state["plan_revision_feedback"] = feedback
            state["plan_revision_count"] = int(state.get("plan_revision_count", 0)) + 1
            workflow.current_node = "planning"
            record_workflow_event(
                db,
                workflow,
                "PLAN_REVISION_REQUESTED",
                "Operator instruction requested execution plan revision",
                node="plan_review",
                payload={
                    "instruction_chars": len(feedback),
                    "revision_count": state["plan_revision_count"],
                    "source_plan_version": reviewed_plan_version,
                },
            )
        elif workflow.current_node == "specialist_review":
            try:
                roles, recovery_count = prepare_specialist_retry(state, feedback)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=str(exc),
                ) from exc
            workflow.current_node = "specialists"
            workflow.pause_before_report = True
            record_workflow_event(
                db,
                workflow,
                "SPECIALIST_RETRY_REQUESTED",
                "Operator resume instruction triggered targeted specialist recovery",
                node="specialist_review",
                payload={"roles": roles, "recovery_count": recovery_count},
            )
        elif workflow.current_node == "report":
            workflow.pause_before_report = False
        workflow.state_json = json.dumps(state, ensure_ascii=False)
        workflow.pause_requested_at = None
        workflow.pause_requested_by_user_id = None
        workflow.pause_reason = ""
        record_workflow_event(
            db,
            workflow,
            "INTERVENTION_APPLIED",
            "Operator instruction applied to workflow context",
            payload={
                "resume_from_node": state["interventions"][-1]["resume_from_node"],
                "instruction_chars": len(feedback),
                "intervention_count": workflow.intervention_count,
            },
        )
    elif workflow.current_node == "plan_review":
        if payload.decision is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Plan review decision must be APPROVE or REVISE",
            )
        state = workflow_state(workflow)
        try:
            selected_plan, selected_version = select_execution_plan_version(state, payload.plan_version)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
        selected_deliberation = select_execution_plan_deliberation(state, selected_version)
        state["execution_plan"] = selected_plan
        state["plan_version"] = selected_version
        state["plan_deliberation"] = selected_deliberation
        reviewed_plan_version = selected_version
        if payload.decision == "REVISE":
            if not feedback:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Revision instruction is required for plan review",
                )
            state["plan_approved"] = False
            state["plan_revision_feedback"] = feedback
            state["plan_revision_count"] = int(state.get("plan_revision_count", 0)) + 1
            workflow.current_node = "planning"
            record_workflow_event(
                db,
                workflow,
                "PLAN_REVISION_REQUESTED",
                "Execution plan revision requested",
                node="plan_review",
                payload={
                    "instruction_chars": len(feedback),
                    "revision_count": state["plan_revision_count"],
                    "source_plan_version": selected_version,
                },
            )
        elif payload.decision == "APPROVE":
            try:
                state["execution_plan"] = validate_execution_plan_for_dispatch(
                    state,
                    selected_plan,
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=str(exc),
                ) from exc
            state["plan_approved"] = True
            workflow.current_node = "specialists"
            record_workflow_event(
                db,
                workflow,
                "PLAN_APPROVED",
                "Execution plan approved for specialist dispatch",
                node="plan_review",
                payload={
                    "branch_count": len(state.get("execution_plan", {}).get("assignments", [])),
                    "revision_count": int(state.get("plan_revision_count", 0)),
                    "plan_version": selected_version,
                },
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Plan review decision must be APPROVE or REVISE",
            )
        workflow.state_json = json.dumps(state, ensure_ascii=False)
    elif workflow.current_node == "specialist_review":
        if not feedback:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Recovery instruction is required for specialist review",
            )
        state = workflow_state(workflow)
        if payload.decision == "RETRY":
            try:
                roles, recovery_count = prepare_specialist_retry(state, feedback)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=str(exc),
                ) from exc
            workflow.current_node = "specialists"
            record_workflow_event(
                db,
                workflow,
                "SPECIALIST_RETRY_REQUESTED",
                "Operator requested targeted specialist recovery",
                node="specialist_review",
                payload={"roles": roles, "recovery_count": recovery_count},
            )
        elif payload.decision == "REPLAN":
            try:
                roles, revision_count = prepare_specialist_replan(state, feedback)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=str(exc),
                ) from exc
            workflow.current_node = "planning"
            record_workflow_event(
                db,
                workflow,
                "SPECIALIST_REPLAN_REQUESTED",
                "Operator returned failed specialist work to planning",
                node="specialist_review",
                payload={
                    "roles": roles,
                    "revision_count": revision_count,
                    "source_plan_version": int(state.get("plan_version", 0)),
                },
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Specialist review decision must be RETRY or REPLAN",
            )
        state["specialist_failures"] = []
        workflow.state_json = json.dumps(state, ensure_ascii=False)
        workflow.pause_before_report = True
    elif workflow.current_node == "quality_review":
        if not feedback:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Revision instruction is required for quality review",
            )
        state = workflow_state(workflow)
        state["revision_feedback"] = feedback
        state["manual_revision_count"] = int(state.get("manual_revision_count", 0)) + 1
        workflow.state_json = json.dumps(state, ensure_ascii=False)
        workflow.current_node = "specialists"
        workflow.pause_before_report = True
    elif workflow.current_node == "report":
        workflow.pause_before_report = False
    else:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Workflow is not waiting for human confirmation")

    if not operator_pause and gate != "plan_review":
        workflow.human_feedback = feedback
    workflow.status = WorkflowStatus.queued
    workflow.error = ""
    workflow.finished_at = None
    record_workflow_event(
        db,
        workflow,
        "QUEUED",
        "Workflow continued after human review",
        payload={
            "approval_gate": gate,
            "decision": payload.decision,
            "plan_version": reviewed_plan_version,
        },
    )
    audit_action = "workflow.continue"
    if gate == "plan_review" and payload.decision == "APPROVE":
        audit_action = "workflow.plan_approved"
    elif gate == "plan_review" and payload.decision == "REVISE":
        audit_action = "workflow.plan_revision_requested"
    elif gate == "specialist_review" and payload.decision == "RETRY":
        audit_action = "workflow.specialist_retry_requested"
    elif gate == "specialist_review" and payload.decision == "REPLAN":
        audit_action = "workflow.specialist_replan_requested"
    record_audit(
        db,
        audit_action,
        current_user.id,
        workflow.project_id,
        "workflow",
        workflow.id,
        {
            "approval_gate": gate,
            "decision": payload.decision,
            "instruction_chars": len(feedback),
            "plan_version": reviewed_plan_version,
        },
        request,
    )
    db.commit()
    db.refresh(workflow)
    return to_response(workflow)


@router.post("/{workflow_id}/cancel", response_model=WorkflowResponse)
def cancel_workflow(
    workflow_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowResponse:
    workflow = db.scalar(select(WorkflowRun).where(WorkflowRun.id == workflow_id).with_for_update())
    if not workflow or workflow.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    get_project_for_user(workflow.project_id, current_user, db, write=True)
    if workflow.status in TERMINAL_STATUSES:
        return to_response(workflow)
    if workflow.status in {
        WorkflowStatus.cancelling,
        WorkflowStatus.compensating,
        WorkflowStatus.compensation_failed,
    }:
        return to_response(workflow)
    workflow.cancel_requested_at = utc_now()
    if workflow.status == WorkflowStatus.queued:
        workflow.status = WorkflowStatus.cancelled
        workflow.finished_at = utc_now()
        workflow.locked_at = None
        workflow.lease_token = None
        refund_workflow_charge(db, workflow, "Cancelled multi-agent workflow")
        record_workflow_event(db, workflow, "CANCELLED", "Workflow cancelled before execution")
    elif workflow.status == WorkflowStatus.paused:
        workflow.status = WorkflowStatus.compensating
        record_workflow_event(db, workflow, "CANCEL_REQUESTED", "Paused workflow cancellation requested")
    else:
        workflow.status = WorkflowStatus.cancelling
        record_workflow_event(db, workflow, "CANCEL_REQUESTED", "Workflow cancellation requested")
    record_audit(
        db,
        "workflow.cancel_requested",
        current_user.id,
        workflow.project_id,
        "workflow",
        workflow.id,
        request=request,
    )
    db.commit()
    db.refresh(workflow)
    if workflow.status == WorkflowStatus.compensating:
        workflow = finish_workflow_compensation(
            db,
            workflow,
            target_status=WorkflowStatus.cancelled,
            reason="Workflow cancellation requested during human review",
        )
    return to_response(workflow)


@router.post("/{workflow_id}/retry-compensation", response_model=WorkflowResponse)
def retry_workflow_compensation(
    workflow_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowResponse:
    workflow = db.scalar(select(WorkflowRun).where(WorkflowRun.id == workflow_id).with_for_update())
    if not workflow or workflow.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    get_project_for_user(workflow.project_id, current_user, db, write=True)
    if workflow.status != WorkflowStatus.compensation_failed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Workflow is not waiting for compensation recovery",
        )
    record_audit(
        db,
        "workflow.compensation_retry",
        current_user.id,
        workflow.project_id,
        "workflow",
        workflow.id,
        request=request,
    )
    db.commit()
    target = WorkflowStatus.cancelled if workflow.cancel_requested_at else WorkflowStatus.failed
    workflow = finish_workflow_compensation(
        db,
        workflow,
        target_status=target,
        reason=workflow.error or "Manual compensation retry",
    )
    return to_response(workflow)


@router.post("/{workflow_id}/retry", response_model=WorkflowResponse, status_code=status.HTTP_202_ACCEPTED)
def retry_workflow(
    workflow_id: int,
    payload: WorkflowRetryRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowResponse:
    source = db.get(WorkflowRun, workflow_id)
    if not source or source.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    get_project_for_user(source.project_id, current_user, db, write=True)
    db.scalar(select(Project).where(Project.id == source.project_id).with_for_update())

    existing = db.scalar(select(WorkflowRun).where(WorkflowRun.request_id == payload.request_id))
    if existing:
        if existing.user_id == current_user.id and existing.parent_workflow_id == source.id:
            return to_response(existing)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Workflow retry request ID is already in use",
        )

    source = db.scalar(select(WorkflowRun).where(WorkflowRun.id == workflow_id).with_for_update())
    if not source or source.status != WorkflowStatus.failed:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only failed workflows can be retried")
    active = db.scalar(
        select(WorkflowRun).where(
            WorkflowRun.project_id == source.project_id,
            WorkflowRun.status.in_(ACTIVE_STATUSES),
        )
    )
    if active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Project already has an active workflow: {active.id}",
        )

    idempotency_key = f"workflow-retry:{current_user.id}:{source.id}:{payload.request_id}"
    try:
        billing = apply_token_change(
            db,
            current_user.id,
            -settings.workflow_token_cost,
            "CONSUME",
            idempotency_key=idempotency_key,
            reference_type="workflow",
            reference_id=payload.request_id,
            description="重试多 Agent 项目工作流",
        )
    except InsufficientTokensError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc)) from exc

    child = WorkflowRun(
        project_id=source.project_id,
        user_id=source.user_id,
        parent_workflow_id=source.id,
        retry_from_node=source.current_node,
        retry_sequence=source.retry_sequence + 1,
        status=WorkflowStatus.queued,
        current_node=source.current_node,
        state_json=json.dumps(retry_checkpoint_state(db, source), ensure_ascii=False),
        human_feedback=source.human_feedback,
        request_id=payload.request_id,
        billing_transaction_id=billing.id,
        pause_before_report=source.pause_before_report,
        attempt_count=0,
        max_attempts=source.max_attempts,
    )
    db.add(child)
    db.flush()
    record_workflow_event(
        db,
        source,
        "RETRY_CREATED",
        "Checkpoint retry created as a new workflow run",
        payload={
            "retry_workflow_id": child.id,
            "retry_from_node": child.retry_from_node,
            "retry_sequence": child.retry_sequence,
        },
    )
    record_workflow_event(
        db,
        child,
        "RETRY_QUEUED",
        "Workflow queued from an immutable failed run",
        payload={
            "parent_workflow_id": source.id,
            "retry_from_node": child.retry_from_node,
            "retry_sequence": child.retry_sequence,
        },
    )
    record_workflow_event(db, child, "QUEUED", "Checkpoint retry queued")
    record_audit(
        db,
        "workflow.retry",
        current_user.id,
        child.project_id,
        "workflow",
        child.id,
        {
            "request_id": payload.request_id,
            "parent_workflow_id": source.id,
            "retry_from_node": child.retry_from_node,
            "retry_sequence": child.retry_sequence,
        },
        request,
    )
    db.commit()
    db.refresh(child)
    return to_response(child)


@router.post("/{workflow_id}/publish", response_model=WorkflowPublicationOut)
async def publish_workflow_artifact(
    workflow_id: int,
    payload: WorkflowPublishRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowPublicationOut:
    workflow = get_owned_workflow(workflow_id, current_user, db, write=True)
    existing_request = db.scalar(
        select(WorkflowArtifactPublication).where(WorkflowArtifactPublication.request_id == payload.request_id)
    )
    if existing_request:
        return WorkflowPublicationOut.model_validate(existing_request, from_attributes=True)
    existing_target = db.scalar(
        select(WorkflowArtifactPublication).where(
            WorkflowArtifactPublication.workflow_id == workflow.id,
            WorkflowArtifactPublication.document_type == payload.document_type,
            WorkflowArtifactPublication.target == payload.target,
        )
    )
    if existing_target:
        return WorkflowPublicationOut.model_validate(existing_target, from_attributes=True)
    state = json.loads(workflow.state_json)
    artifact = next(
        (
            item
            for item in state.get("documents", [])
            if item.get("type") == payload.document_type and isinstance(item.get("content"), str)
        ),
        None,
    )
    if not artifact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow artifact not found")
    project = db.get(Project, workflow.project_id)
    report_id = None
    document_id = None
    if payload.target == "report":
        report = Report(
            project_id=project.id,
            user_id=current_user.id,
            report_type=f"workflow_{payload.document_type.lower()}",
            title=f"{project.name} {payload.document_type}",
            content=artifact["content"],
        )
        db.add(report)
        db.flush()
        report_id = report.id
    else:
        filename = f"{project.name}-{payload.document_type}.md"
        upload = UploadFile(filename=filename, file=BytesIO(artifact["content"].encode("utf-8")))
        try:
            document = await queue_document(
                db,
                current_user,
                upload,
                project.id,
                tags=["workflow", payload.document_type.lower()],
                source_label=f"workflow:{workflow.id}",
            )
            document_id = document.id
        except DuplicateDocumentError as exc:
            document_id = exc.document_id
    publication = WorkflowArtifactPublication(
        workflow_id=workflow.id,
        document_type=payload.document_type,
        target=payload.target,
        report_id=report_id,
        document_id=document_id,
        request_id=payload.request_id,
        created_by_user_id=current_user.id,
    )
    db.add(publication)
    db.flush()
    record_audit(
        db,
        "workflow.artifact_publish",
        current_user.id,
        workflow.project_id,
        "workflow_artifact",
        publication.id,
        {"document_type": payload.document_type, "target": payload.target},
        request,
    )
    db.commit()
    db.refresh(publication)
    return WorkflowPublicationOut.model_validate(publication, from_attributes=True)
