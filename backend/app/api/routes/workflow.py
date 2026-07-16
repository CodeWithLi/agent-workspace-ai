import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.routes.projects import get_project_for_user
from app.core.database import get_db
from app.core.audit import record_audit
from app.langgraph.workflow import continue_workspace_graph, run_workspace_graph
from app.models import Project, TokenTransaction, User, WorkflowRun, WorkflowStatus
from app.schemas import WorkflowContinueRequest, WorkflowRequest, WorkflowResponse
from app.core.config import get_settings
from app.services.billing import InsufficientTokensError, apply_token_change, refund_consumption

router = APIRouter()
settings = get_settings()


def to_response(workflow: WorkflowRun) -> WorkflowResponse:
    return WorkflowResponse(
        workflow_id=workflow.id,
        project_id=workflow.project_id,
        status=workflow.status,
        current_node=workflow.current_node,
        state=json.loads(workflow.state_json),
    )


def refund_workflow_charge(db: Session, workflow: WorkflowRun, reason: str) -> None:
    if not workflow.request_id:
        return
    transaction = db.scalar(
        select(TokenTransaction).where(
            TokenTransaction.transaction_type == "CONSUME",
            TokenTransaction.reference_type == "workflow",
            TokenTransaction.reference_id == workflow.request_id,
        )
    )
    if transaction:
        refund_consumption(db, transaction.id, reason)
        db.commit()


@router.post("/run", response_model=WorkflowResponse)
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
            WorkflowRun.status.in_([WorkflowStatus.running, WorkflowStatus.paused]),
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
    try:
        workflow = await run_workspace_graph(
            db,
            project,
            current_user.id,
            payload.user_input,
            payload.pause_before_report,
            payload.request_id,
        )
    except Exception:
        db.rollback()
        refund_consumption(db, billing.id, "Multi-agent workflow failed")
        db.commit()
        raise
    record_audit(db, "workflow.run", current_user.id, project.id, "workflow", workflow.id, {"status": workflow.status.value}, request)
    db.commit()
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
    workflow = db.get(WorkflowRun, workflow_id)
    if not workflow or workflow.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    get_project_for_user(workflow.project_id, current_user, db)
    return to_response(workflow)


@router.post("/continue", response_model=WorkflowResponse)
async def continue_workflow(
    payload: WorkflowContinueRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowResponse:
    workflow = db.scalar(select(WorkflowRun).where(WorkflowRun.id == payload.workflow_id).with_for_update())
    if not workflow or workflow.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    try:
        workflow = await continue_workspace_graph(db, workflow, payload.human_feedback)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        refund_workflow_charge(db, workflow, "Multi-agent workflow continuation failed")
        raise
    record_audit(db, "workflow.continue", current_user.id, workflow.project_id, "workflow", workflow.id, {"status": workflow.status.value}, request)
    db.commit()
    return to_response(workflow)
