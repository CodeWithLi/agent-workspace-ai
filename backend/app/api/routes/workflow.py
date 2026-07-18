import asyncio
import json
from datetime import datetime, timezone
from io import BytesIO

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.routes.projects import get_project_for_user
from app.core.audit import record_audit
from app.core.config import get_settings
from app.core.database import SessionLocal, get_db
from app.langgraph.workflow import initial_state, record_workflow_event, snapshot_agent_configs
from app.models import Project, Report, User, WorkflowArtifactPublication, WorkflowEvent, WorkflowRun, WorkflowSagaStep, WorkflowStatus
from app.schemas import WorkflowContinueRequest, WorkflowEventResponse, WorkflowPauseRequest, WorkflowPublicationOut, WorkflowPublishRequest, WorkflowRequest, WorkflowResponse, WorkflowRetryRequest, WorkflowSagaStepOut
from app.services.billing import InsufficientTokensError, apply_token_change
from app.services.workflows import finish_workflow_compensation, refund_workflow_charge
from app.rag.service import DuplicateDocumentError, queue_document


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
    "specialists": 4,
    "quality_gate": 5,
    "quality_review": 6,
    "project_manager": 7,
    "tester": 8,
    "report": 9,
    "completed": 10,
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
        payload=payload if isinstance(payload, dict) else {},
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
            initial_state(project, payload.user_input, snapshot_agent_configs(db)),
            ensure_ascii=False,
        ),
        request_id=payload.request_id,
        billing_transaction_id=billing.id,
        pause_before_report=payload.pause_before_report,
        max_attempts=settings.workflow_max_attempts,
    )
    db.add(workflow)
    db.flush()
    record_workflow_event(db, workflow, "QUEUED", "Workflow queued")
    record_audit(
        db,
        "workflow.queued",
        current_user.id,
        project.id,
        "workflow",
        workflow.id,
        {"request_id": payload.request_id},
        request,
    )
    db.commit()
    db.refresh(workflow)
    return to_response(workflow)


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

    if not operator_pause:
        workflow.human_feedback = feedback
    workflow.status = WorkflowStatus.queued
    workflow.error = ""
    workflow.finished_at = None
    record_workflow_event(
        db,
        workflow,
        "QUEUED",
        "Workflow continued after human review",
        payload={"approval_gate": gate},
    )
    record_audit(
        db,
        "workflow.continue",
        current_user.id,
        workflow.project_id,
        "workflow",
        workflow.id,
        {"approval_gate": gate, "instruction_chars": len(feedback)},
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
