from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models import TraceAlertStatus, User, WorkflowStatus
from app.observability import (
    compare_trace_runs,
    get_trace_alerts,
    get_trace_detail,
    get_trace_health,
    get_trace_overview,
    sync_trace_alerts,
    transition_trace_alerts,
)
from app.schemas import (
    TraceAlertBulkUpdate,
    TraceAlertCollectionOut,
    TraceAlertOut,
    TraceAlertSyncOut,
    TraceComparisonOut,
    TraceDetailOut,
    TraceHealthOut,
    TraceOverviewOut,
)


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


@router.post("/alerts/sync", response_model=TraceAlertSyncOut)
def trace_alert_sync(
    days: int = Query(default=30, ge=1, le=90),
    project_id: int | None = Query(default=None, ge=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TraceAlertSyncOut:
    created_count = sync_trace_alerts(
        db,
        current_user,
        days=days,
        project_id=project_id,
    )
    db.commit()
    return TraceAlertSyncOut(created_count=created_count)


@router.get("/alerts", response_model=TraceAlertCollectionOut)
def trace_alerts(
    days: int = Query(default=30, ge=1, le=90),
    project_id: int | None = Query(default=None, ge=1),
    alert_status: TraceAlertStatus | None = Query(default=None, alias="status"),
    severity: str | None = Query(default=None, pattern="^(WARNING|CRITICAL)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TraceAlertCollectionOut:
    return get_trace_alerts(
        db,
        current_user,
        days=days,
        project_id=project_id,
        alert_status=alert_status,
        severity=severity,
    )


@router.post("/alerts/bulk", response_model=list[TraceAlertOut])
def trace_alert_bulk_update(
    payload: TraceAlertBulkUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TraceAlertOut]:
    alerts = transition_trace_alerts(
        db,
        current_user,
        alert_ids=payload.alert_ids,
        action=payload.action,
        resolution_note=payload.resolution_note,
    )
    db.commit()
    return alerts


@router.get("/{workflow_id}", response_model=TraceDetailOut)
def trace_detail(
    workflow_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TraceDetailOut:
    return get_trace_detail(db, current_user, workflow_id)
