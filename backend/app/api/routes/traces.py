from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models import User, WorkflowStatus
from app.observability import get_trace_detail, get_trace_overview
from app.schemas import TraceDetailOut, TraceOverviewOut


router = APIRouter()


@router.get("/overview", response_model=TraceOverviewOut)
def trace_overview(
    days: int = Query(default=7, ge=1, le=90),
    project_id: int | None = Query(default=None, ge=1),
    workflow_status: WorkflowStatus | None = Query(default=None, alias="status"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TraceOverviewOut:
    return get_trace_overview(
        db,
        current_user,
        days=days,
        project_id=project_id,
        workflow_status=workflow_status,
    )


@router.get("/{workflow_id}", response_model=TraceDetailOut)
def trace_detail(
    workflow_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TraceDetailOut:
    return get_trace_detail(db, current_user, workflow_id)
