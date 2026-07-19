import asyncio
import logging
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.agent.orchestration import ReviewerPanelQuorumError
from app.core.audit import record_audit
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.langgraph.workflow import WorkflowCancelled, WorkflowPauseRequested, execute_workspace_graph, record_workflow_event
from app.models import WorkflowRun, WorkflowStatus
from app.services.billing import refund_consumption
from app.services.workflow_saga import (
    WorkflowLeaseLost,
    compensate_workflow_saga,
    earliest_compensated_node,
)


logger = logging.getLogger(__name__)
settings = get_settings()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def refund_workflow_charge(db: Session, workflow: WorkflowRun, reason: str) -> None:
    if workflow.billing_transaction_id:
        refund_consumption(db, workflow.billing_transaction_id, reason)


class WorkflowLeaseHeartbeat:
    def __init__(self, bind: Engine, workflow_id: int, lease_token: str) -> None:
        self.bind = bind
        self.workflow_id = workflow_id
        self.lease_token = lease_token
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        self.lost = False

    async def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name=f"workflow-lease-{self.workflow_id}")

    async def stop(self) -> None:
        if not self._task:
            return
        self._stop.set()
        await self._task
        self._task = None

    async def _run(self) -> None:
        interval = max(1.0, settings.workflow_lease_seconds / 3)
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
                return
            except TimeoutError:
                pass
            try:
                with Session(self.bind) as heartbeat_db:
                    result = heartbeat_db.execute(
                        update(WorkflowRun)
                        .where(
                            WorkflowRun.id == self.workflow_id,
                            WorkflowRun.lease_token == self.lease_token,
                            WorkflowRun.status.in_(
                                {
                                    WorkflowStatus.running,
                                    WorkflowStatus.cancelling,
                                    WorkflowStatus.compensating,
                                }
                            ),
                        )
                        .values(locked_at=utc_now())
                    )
                    heartbeat_db.commit()
                if result.rowcount != 1:
                    self.lost = True
                    return
            except Exception:
                logger.exception("Workflow lease heartbeat failed: workflow_id=%s", self.workflow_id)


def finish_workflow_compensation(
    db: Session,
    workflow: WorkflowRun,
    *,
    target_status: WorkflowStatus | None = None,
    reason: str,
) -> WorkflowRun:
    target = target_status or (
        WorkflowStatus.cancelled if workflow.cancel_requested_at else WorkflowStatus.failed
    )
    workflow.status = WorkflowStatus.compensating
    workflow.locked_at = utc_now()
    record_workflow_event(db, workflow, "COMPENSATION_STARTED", "Workflow Saga compensation started")
    db.commit()
    try:
        compensate_workflow_saga(
            db,
            workflow.id,
            max_attempts=settings.workflow_compensation_max_attempts,
        )
    except Exception as exc:
        db.rollback()
        workflow = db.get(WorkflowRun, workflow.id)
        workflow.status = WorkflowStatus.compensation_failed
        workflow.locked_at = None
        workflow.lease_token = None
        workflow.pause_requested_at = None
        workflow.pause_requested_by_user_id = None
        workflow.pause_reason = ""
        workflow.error = f"{reason}; compensation failed: {exc}"[:2000]
        refund_workflow_charge(db, workflow, "Multi-agent workflow failed and requires reconciliation")
        record_workflow_event(
            db,
            workflow,
            "COMPENSATION_FAILED",
            "Workflow compensation requires manual intervention",
            payload={"error": str(exc)[:2000], "target_status": target.value},
        )
        record_audit(
            db,
            "workflow.compensation_failed",
            workflow.user_id,
            workflow.project_id,
            "workflow",
            workflow.id,
            {"error": str(exc)[:2000], "target_status": target.value},
        )
        db.commit()
        return workflow

    workflow = db.get(WorkflowRun, workflow.id)
    restart_node = earliest_compensated_node(db, workflow.id)
    if restart_node:
        workflow.current_node = restart_node
    workflow.status = target
    workflow.locked_at = None
    workflow.lease_token = None
    workflow.pause_requested_at = None
    workflow.pause_requested_by_user_id = None
    workflow.pause_reason = ""
    workflow.finished_at = utc_now()
    workflow.error = reason[:2000] if target == WorkflowStatus.failed else ""
    refund_workflow_charge(db, workflow, f"Multi-agent workflow {target.value.lower()}")
    record_workflow_event(
        db,
        workflow,
        "COMPENSATED",
        "Workflow writes were compensated in reverse order",
        payload={"target_status": target.value, "restart_node": restart_node},
    )
    record_workflow_event(
        db,
        workflow,
        target.value,
        f"Workflow {target.value.lower()} after compensation",
    )
    db.commit()
    return workflow


def claim_workflow(db: Session) -> int | None:
    cutoff = utc_now() - timedelta(seconds=settings.workflow_lease_seconds)
    workflow = db.scalar(
        select(WorkflowRun)
        .where(
            or_(
                WorkflowRun.status == WorkflowStatus.queued,
                (WorkflowRun.status == WorkflowStatus.running)
                & (or_(WorkflowRun.locked_at.is_(None), WorkflowRun.locked_at <= cutoff)),
                (WorkflowRun.status == WorkflowStatus.cancelling)
                & (or_(WorkflowRun.locked_at.is_(None), WorkflowRun.locked_at <= cutoff)),
                (WorkflowRun.status == WorkflowStatus.compensating)
                & (or_(WorkflowRun.locked_at.is_(None), WorkflowRun.locked_at <= cutoff)),
            )
        )
        .order_by(WorkflowRun.created_at, WorkflowRun.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if not workflow:
        return None
    recovered = workflow.status in {
        WorkflowStatus.running,
        WorkflowStatus.cancelling,
        WorkflowStatus.compensating,
    }
    if workflow.status == WorkflowStatus.queued:
        workflow.status = WorkflowStatus.running
    workflow.locked_at = utc_now()
    workflow.lease_token = str(uuid4())
    workflow.started_at = workflow.started_at or utc_now()
    workflow.attempt_count += 1
    workflow.error = ""
    record_workflow_event(
        db,
        workflow,
        "RECOVERED" if recovered else "STARTED",
        "Recovered stale workflow lease" if recovered else "Workflow worker started",
    )
    db.commit()
    return workflow.id


async def process_workflow(db: Session, workflow_id: int, *, claimed: bool = False) -> WorkflowRun:
    workflow = db.get(WorkflowRun, workflow_id)
    if not workflow:
        raise LookupError("Workflow not found")
    if workflow.status == WorkflowStatus.compensating:
        return finish_workflow_compensation(
            db,
            workflow,
            reason=workflow.error or "Recovered interrupted compensation",
        )
    if not claimed:
        if workflow.status != WorkflowStatus.queued:
            return workflow
        workflow.status = WorkflowStatus.running
        workflow.locked_at = utc_now()
        workflow.lease_token = str(uuid4())
        workflow.started_at = workflow.started_at or utc_now()
        workflow.attempt_count += 1
        workflow.error = ""
        record_workflow_event(db, workflow, "STARTED", "Workflow worker started")
        db.commit()
    heartbeat = WorkflowLeaseHeartbeat(db.get_bind(), workflow.id, workflow.lease_token)
    await heartbeat.start()
    try:
        result = await execute_workspace_graph(db, workflow, workflow.pause_before_report)
        if heartbeat.lost:
            raise WorkflowLeaseLost("Workflow lease ownership changed during execution")
        return result
    except WorkflowLeaseLost:
        db.rollback()
        logger.warning("Stopped stale workflow worker: workflow_id=%s", workflow_id)
        return db.get(WorkflowRun, workflow_id)
    except WorkflowCancelled:
        db.rollback()
        workflow = db.get(WorkflowRun, workflow_id)
        record_audit(
            db,
            "workflow.cancellation_compensation",
            workflow.user_id,
            workflow.project_id,
            "workflow",
            workflow.id,
        )
        db.commit()
        return finish_workflow_compensation(
            db,
            workflow,
            target_status=WorkflowStatus.cancelled,
            reason="Workflow cancellation requested",
        )
    except WorkflowPauseRequested:
        db.rollback()
        workflow = db.get(WorkflowRun, workflow_id)
        if workflow.status == WorkflowStatus.cancelling:
            return finish_workflow_compensation(
                db,
                workflow,
                target_status=WorkflowStatus.cancelled,
                reason="Workflow cancellation superseded an operator pause",
            )
        workflow.status = WorkflowStatus.paused
        workflow.locked_at = None
        workflow.lease_token = None
        workflow.error = ""
        workflow.intervention_count += 1
        record_workflow_event(
            db,
            workflow,
            "PAUSED",
            "Workflow paused at a committed node boundary",
            payload={
                "approval_gate": "operator",
                "requested_by_user_id": workflow.pause_requested_by_user_id,
                "reason_chars": len(workflow.pause_reason),
                "intervention_count": workflow.intervention_count,
            },
        )
        record_audit(
            db,
            "workflow.operator_paused",
            workflow.pause_requested_by_user_id or workflow.user_id,
            workflow.project_id,
            "workflow",
            workflow.id,
            {
                "reason_chars": len(workflow.pause_reason),
                "intervention_count": workflow.intervention_count,
            },
        )
        db.commit()
        return workflow
    except Exception as exc:
        db.rollback()
        workflow = db.get(WorkflowRun, workflow_id)
        workflow.locked_at = None
        workflow.error = str(exc)[:2000]
        failure_payload = {
            "workflow_attempt": workflow.attempt_count,
            "error": workflow.error,
        }
        if isinstance(exc, ReviewerPanelQuorumError):
            failure_payload.update(
                {
                    "reviewer_count": exc.panel_count,
                    "reviewer_valid_count": exc.valid_count,
                    "reviewer_quorum": exc.quorum,
                }
            )
        record_workflow_event(
            db,
            workflow,
            "NODE_FAILED",
            f"Failed {workflow.current_node}",
            node=workflow.current_node,
            payload=failure_payload,
        )
        if workflow.attempt_count < workflow.max_attempts:
            workflow.status = WorkflowStatus.queued
            workflow.lease_token = None
            record_workflow_event(
                db,
                workflow,
                "RETRY_SCHEDULED",
                f"Workflow attempt {workflow.attempt_count} failed; retry scheduled",
                payload={
                    "workflow_attempt": workflow.attempt_count,
                    "error": workflow.error,
                },
            )
        else:
            db.commit()
            logger.exception("Workflow %s execution failed", workflow_id)
            return finish_workflow_compensation(
                db,
                workflow,
                target_status=WorkflowStatus.failed,
                reason=workflow.error,
            )
        db.commit()
        logger.exception("Workflow %s execution failed", workflow_id)
        return workflow
    finally:
        with suppress(Exception):
            await heartbeat.stop()


class WorkflowDispatcher:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if not settings.workflow_worker_enabled or self._task:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="workflow-dispatcher")
        logger.info("Workflow dispatcher started")

    async def stop(self) -> None:
        if not self._task:
            return
        self._stop.set()
        await self._task
        self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                processed = await self.dispatch_once()
            except Exception:
                processed = False
                logger.exception("Workflow dispatcher iteration failed")
            if processed:
                continue
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=settings.workflow_poll_seconds)
            except TimeoutError:
                pass

    async def dispatch_once(self) -> bool:
        with SessionLocal() as db:
            workflow_id = claim_workflow(db)
            if workflow_id is None:
                return False
            await process_workflow(db, workflow_id, claimed=True)
            return True


workflow_dispatcher = WorkflowDispatcher()
