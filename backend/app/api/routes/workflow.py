import asyncio
import json
from datetime import datetime, timezone
from io import BytesIO

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
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
from app.models import Project, Report, TokenTransaction, User, WorkflowArtifactPublication, WorkflowEvent, WorkflowRun, WorkflowSagaStep, WorkflowStatus
from app.schemas import WorkflowContinueRequest, WorkflowPublicationOut, WorkflowPublishRequest, WorkflowRequest, WorkflowResponse, WorkflowRetryRequest, WorkflowSagaStepOut
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


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_response(workflow: WorkflowRun) -> WorkflowResponse:
    state = json.loads(workflow.state_json)
    state.pop("agent_snapshot", None)
    return WorkflowResponse(
        workflow_id=workflow.id,
        project_id=workflow.project_id,
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


def get_owned_workflow(workflow_id: int, current_user: User, db: Session, *, write: bool = False) -> WorkflowRun:
    workflow = db.get(WorkflowRun, workflow_id)
    if not workflow or workflow.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    get_project_for_user(workflow.project_id, current_user, db, write=write)
    return workflow


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
        while True:
            with SessionLocal() as event_db:
                workflow = event_db.get(WorkflowRun, workflow_id)
                if not workflow or workflow.user_id != user_id:
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
                    data = json.dumps(
                        {
                            "id": event.id,
                            "workflow_id": event.workflow_id,
                            "node": event.node,
                            "event_type": event.event_type,
                            "message": event.message,
                            "payload": json.loads(event.payload_json),
                            "created_at": event.created_at.isoformat(),
                        },
                        ensure_ascii=False,
                    )
                    yield f"id: {event.id}\nevent: workflow\ndata: {data}\n\n"
                if terminal and not events:
                    return
            await asyncio.sleep(1)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
    if workflow.status != WorkflowStatus.paused or workflow.current_node != "report":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Workflow is not waiting for human confirmation")
    workflow.human_feedback = payload.human_feedback
    workflow.pause_before_report = False
    workflow.status = WorkflowStatus.queued
    workflow.error = ""
    workflow.finished_at = None
    record_workflow_event(db, workflow, "QUEUED", "Workflow continued after human review")
    record_audit(
        db,
        "workflow.continue",
        current_user.id,
        workflow.project_id,
        "workflow",
        workflow.id,
        request=request,
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
    workflow = db.scalar(select(WorkflowRun).where(WorkflowRun.id == workflow_id).with_for_update())
    if not workflow or workflow.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    get_project_for_user(workflow.project_id, current_user, db, write=True)
    idempotency_key = f"workflow-retry:{current_user.id}:{workflow.id}:{payload.request_id}"
    current_charge = db.get(TokenTransaction, workflow.billing_transaction_id) if workflow.billing_transaction_id else None
    if workflow.status == WorkflowStatus.queued and current_charge and current_charge.idempotency_key == idempotency_key:
        return to_response(workflow)
    if workflow.status != WorkflowStatus.failed:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only failed workflows can be retried")
    try:
        billing = apply_token_change(
            db,
            current_user.id,
            -settings.workflow_token_cost,
            "CONSUME",
            idempotency_key=idempotency_key,
            reference_type="workflow",
            reference_id=workflow.request_id or str(workflow.id),
            description="重试多 Agent 项目工作流",
        )
    except InsufficientTokensError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc)) from exc
    workflow.billing_transaction_id = billing.id
    workflow.status = WorkflowStatus.queued
    workflow.attempt_count = 0
    workflow.error = ""
    workflow.finished_at = None
    workflow.cancel_requested_at = None
    record_workflow_event(db, workflow, "QUEUED", "Failed workflow queued for retry")
    record_audit(
        db,
        "workflow.retry",
        current_user.id,
        workflow.project_id,
        "workflow",
        workflow.id,
        {"request_id": payload.request_id},
        request,
    )
    db.commit()
    db.refresh(workflow)
    return to_response(workflow)


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
