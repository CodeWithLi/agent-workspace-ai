import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.routes.projects import get_project_for_user
from app.core.database import get_db
from app.core.audit import record_audit
from app.langgraph.workflow import continue_workspace_graph, run_workspace_graph
from app.models import User, WorkflowRun
from app.schemas import WorkflowContinueRequest, WorkflowRequest, WorkflowResponse

router = APIRouter()


def to_response(workflow: WorkflowRun) -> WorkflowResponse:
    return WorkflowResponse(
        workflow_id=workflow.id,
        project_id=workflow.project_id,
        status=workflow.status,
        current_node=workflow.current_node,
        state=json.loads(workflow.state_json),
    )


@router.post("/run", response_model=WorkflowResponse)
async def run_workflow(
    payload: WorkflowRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowResponse:
    project = get_project_for_user(payload.project_id, current_user, db, write=True)
    workflow = await run_workspace_graph(db, project, current_user.id, payload.user_input, payload.pause_before_report)
    record_audit(db, "workflow.run", current_user.id, project.id, "workflow", workflow.id, {"status": workflow.status.value}, request)
    db.commit()
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
    record_audit(db, "workflow.continue", current_user.id, workflow.project_id, "workflow", workflow.id, {"status": workflow.status.value}, request)
    db.commit()
    return to_response(workflow)
