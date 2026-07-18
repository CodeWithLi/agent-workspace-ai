from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models import User, WorkflowStatus
from app.observability import compare_trace_runs, get_trace_detail, get_trace_health, get_trace_overview
from app.schemas import TraceComparisonOut, TraceDetailOut, TraceHealthOut, TraceOverviewOut


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


@router.get("/compare", response_model=TraceComparisonOut)
def trace_comparison(
    baseline_id: int = Query(ge=1),
    candidate_id: int = Query(ge=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TraceComparisonOut:
    return compare_trace_runs(
        db,
        current_user,
        baseline_id=baseline_id,
        candidate_id=candidate_id,
    )


@router.get("/health", response_model=TraceHealthOut)
def trace_health(
    days: int = Query(default=7, ge=1, le=90),
    project_id: int | None = Query(default=None, ge=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TraceHealthOut:
    return get_trace_health(
        db,
        current_user,
        days=days,
        project_id=project_id,
    )


@router.get("/{workflow_id}", response_model=TraceDetailOut)
def trace_detail(
    workflow_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TraceDetailOut:
    return get_trace_detail(db, current_user, workflow_id)
