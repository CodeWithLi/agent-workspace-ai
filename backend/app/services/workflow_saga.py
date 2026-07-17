import json
from collections.abc import Callable
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.metrics import SAGA_COMPENSATION_DURATION, SAGA_STEPS
from app.models import (
    Report,
    SagaStepStatus,
    Task,
    TaskComment,
    WorkflowEvent,
    WorkflowRun,
    WorkflowSagaStep,
)
from app.tools.project_tools import task_create


class SagaStateError(RuntimeError):
    pass


class SagaCompensationError(RuntimeError):
    pass


class SagaCompensationConflict(SagaCompensationError):
    pass


class WorkflowLeaseLost(RuntimeError):
    pass


VALID_TRANSITIONS: dict[SagaStepStatus, set[SagaStepStatus]] = {
    SagaStepStatus.pending: {SagaStepStatus.executing},
    SagaStepStatus.executing: {SagaStepStatus.completed, SagaStepStatus.failed},
    SagaStepStatus.completed: {SagaStepStatus.compensating},
    SagaStepStatus.failed: {SagaStepStatus.executing},
    SagaStepStatus.compensating: {SagaStepStatus.compensated, SagaStepStatus.compensation_failed},
    SagaStepStatus.compensated: {SagaStepStatus.executing},
    SagaStepStatus.compensation_failed: {SagaStepStatus.compensating},
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def transition_saga_step(step: WorkflowSagaStep, target: SagaStepStatus, message: str = "") -> None:
    current = step.status
    if target not in VALID_TRANSITIONS.get(current, set()):
        raise SagaStateError(f"Illegal Saga transition: {current.value} -> {target.value}")
    history = json.loads(step.transition_log_json or "[]")
    history.append(
        {
            "from": current.value,
            "to": target.value,
            "message": message[:500],
            "at": utc_now().isoformat(),
        }
    )
    step.status = target
    step.transition_log_json = json.dumps(history[-100:], ensure_ascii=False)
    SAGA_STEPS.labels(tool=step.tool_name, status=target.value).inc()


def _workflow_event(
    db: Session,
    workflow_id: int,
    node: str,
    event_type: str,
    message: str,
    payload: dict[str, Any],
) -> None:
    db.add(
        WorkflowEvent(
            workflow_id=workflow_id,
            node=node,
            event_type=event_type,
            message=message,
            payload_json=json.dumps(payload, ensure_ascii=False),
        )
    )


def _lock_workflow(
    db: Session,
    workflow_id: int,
    expected_lease_token: str | None,
) -> WorkflowRun:
    workflow = db.scalar(
        select(WorkflowRun).where(WorkflowRun.id == workflow_id).with_for_update()
    )
    if not workflow:
        raise LookupError("Workflow not found")
    if expected_lease_token is not None and workflow.lease_token != expected_lease_token:
        raise WorkflowLeaseLost("Workflow lease ownership changed")
    workflow.locked_at = utc_now()
    return workflow


def execute_saga_step(
    db: Session,
    workflow: WorkflowRun,
    *,
    sequence: int,
    node: str,
    tool_name: str,
    compensation_action: str,
    idempotency_key: str,
    input_data: dict[str, Any],
    executor: Callable[[], dict[str, Any]],
    expected_lease_token: str | None = None,
) -> dict[str, Any]:
    step = db.scalar(
        select(WorkflowSagaStep).where(
            WorkflowSagaStep.workflow_id == workflow.id,
            WorkflowSagaStep.idempotency_key == idempotency_key,
        )
    )
    if step and step.status == SagaStepStatus.completed:
        return json.loads(step.output_json)
    if step is None:
        step = WorkflowSagaStep(
            workflow_id=workflow.id,
            sequence=sequence,
            node=node,
            tool_name=tool_name,
            compensation_action=compensation_action,
            idempotency_key=idempotency_key,
            status=SagaStepStatus.pending,
            input_json=json.dumps(input_data, ensure_ascii=False, default=str),
            transition_log_json="[]",
        )
        db.add(step)
        db.commit()
        db.refresh(step)
    elif step.status == SagaStepStatus.executing:
        transition_saga_step(step, SagaStepStatus.failed, "Recovered interrupted execution")
        step.error = "Execution interrupted before completion"
        db.commit()
    elif step.status in {SagaStepStatus.compensating, SagaStepStatus.compensation_failed}:
        raise SagaStateError("Saga step must finish compensation before it can execute again")

    transition_saga_step(step, SagaStepStatus.executing, "Tool execution started")
    step.execute_attempts += 1
    step.started_at = utc_now()
    step.error = ""
    db.commit()

    try:
        _lock_workflow(db, workflow.id, expected_lease_token)
        output = executor()
        step = db.get(WorkflowSagaStep, step.id)
        transition_saga_step(step, SagaStepStatus.completed, "Tool execution committed")
        step.output_json = json.dumps(output, ensure_ascii=False, default=str)
        step.completed_at = utc_now()
        _workflow_event(
            db,
            workflow.id,
            node,
            "SAGA_STEP_COMPLETED",
            f"Committed compensatable tool {tool_name}",
            {"saga_step_id": step.id, "tool": tool_name, "sequence": sequence},
        )
        db.commit()
        return output
    except BaseException as exc:
        db.rollback()
        step = db.get(WorkflowSagaStep, step.id)
        if step and step.status == SagaStepStatus.executing:
            transition_saga_step(step, SagaStepStatus.failed, str(exc))
            step.error = str(exc)[:2000]
            db.commit()
        raise


def _task_snapshot(db: Session, task: Task) -> dict[str, Any]:
    status = task.status.value if hasattr(task.status, "value") else str(task.status)
    return {
        "id": task.id,
        "project_id": task.project_id,
        "title": task.title,
        "description": task.description,
        "priority": task.priority,
        "status": status,
        "assignee_agent_id": task.assignee_agent_id,
        "assignee_user_id": task.assignee_user_id,
        "due_date": task.due_date,
        "due_at": task.due_at.isoformat() if task.due_at else None,
        "comment_ids": list(
            db.scalars(select(TaskComment.id).where(TaskComment.task_id == task.id).order_by(TaskComment.id))
        ),
    }


def execute_task_creation(
    db: Session,
    workflow: WorkflowRun,
    titles: list[str],
    *,
    expected_lease_token: str | None = None,
) -> dict[str, Any]:
    def create() -> dict[str, Any]:
        tasks = task_create(db, workflow.project_id, titles)
        return {"created_tasks": [_task_snapshot(db, task) for task in tasks]}

    return execute_saga_step(
        db,
        workflow,
        sequence=10,
        node="project_manager",
        tool_name="task_create",
        compensation_action="delete_created_tasks",
        idempotency_key="project_manager:create_tasks",
        input_data={"project_id": workflow.project_id, "titles": titles},
        executor=create,
        expected_lease_token=expected_lease_token,
    )


def execute_report_creation(
    db: Session,
    workflow: WorkflowRun,
    *,
    title: str,
    content: str,
    expected_lease_token: str | None = None,
) -> dict[str, Any]:
    def create() -> dict[str, Any]:
        report = Report(
            project_id=workflow.project_id,
            user_id=workflow.user_id,
            report_type="workflow",
            title=title,
            content=content,
        )
        db.add(report)
        db.flush()
        return {
            "created_report": {
                "id": report.id,
                "project_id": report.project_id,
                "user_id": report.user_id,
                "report_type": report.report_type,
                "title": report.title,
                "content": report.content,
            }
        }

    return execute_saga_step(
        db,
        workflow,
        sequence=20,
        node="report",
        tool_name="report_create",
        compensation_action="delete_created_report",
        idempotency_key="report:create_final_report",
        input_data={"project_id": workflow.project_id, "title": title},
        executor=create,
        expected_lease_token=expected_lease_token,
    )


def _compensate_tasks(db: Session, output: dict[str, Any]) -> None:
    for snapshot in reversed(output.get("created_tasks", [])):
        task = db.get(Task, snapshot["id"])
        if task is None:
            continue
        if _task_snapshot(db, task) != snapshot:
            raise SagaCompensationConflict(
                f"Task {task.id} changed after Saga creation; manual reconciliation required"
            )
        db.delete(task)


def _compensate_report(db: Session, output: dict[str, Any]) -> None:
    snapshot = output.get("created_report")
    if not snapshot:
        return
    report = db.get(Report, snapshot["id"])
    if report is None:
        return
    current = {
        "id": report.id,
        "project_id": report.project_id,
        "user_id": report.user_id,
        "report_type": report.report_type,
        "title": report.title,
        "content": report.content,
    }
    if current != snapshot:
        raise SagaCompensationConflict(
            f"Report {report.id} changed after Saga creation; manual reconciliation required"
        )
    db.delete(report)


COMPENSATORS: dict[str, Callable[[Session, dict[str, Any]], None]] = {
    "delete_created_tasks": _compensate_tasks,
    "delete_created_report": _compensate_report,
}


def _compensate_step(db: Session, step_id: int) -> None:
    step = db.get(WorkflowSagaStep, step_id)
    if not step or step.status == SagaStepStatus.compensated:
        return
    if step.status == SagaStepStatus.compensating:
        transition_saga_step(step, SagaStepStatus.compensation_failed, "Recovered interrupted compensation")
        step.error = "Compensation interrupted before completion"
        db.commit()
    transition_saga_step(step, SagaStepStatus.compensating, "Compensation started")
    step.compensation_attempts += 1
    step.error = ""
    db.commit()
    try:
        compensator = COMPENSATORS.get(step.compensation_action)
        if compensator is None:
            raise SagaCompensationError(f"Unknown compensation action: {step.compensation_action}")
        compensator(db, json.loads(step.output_json or "{}"))
        step = db.get(WorkflowSagaStep, step_id)
        transition_saga_step(step, SagaStepStatus.compensated, "Compensation committed")
        step.compensated_at = utc_now()
        _workflow_event(
            db,
            step.workflow_id,
            step.node,
            "SAGA_STEP_COMPENSATED",
            f"Compensated tool {step.tool_name}",
            {"saga_step_id": step.id, "tool": step.tool_name, "sequence": step.sequence},
        )
        db.commit()
    except BaseException as exc:
        db.rollback()
        step = db.get(WorkflowSagaStep, step_id)
        if step and step.status == SagaStepStatus.compensating:
            transition_saga_step(step, SagaStepStatus.compensation_failed, str(exc))
            step.error = str(exc)[:2000]
            _workflow_event(
                db,
                step.workflow_id,
                step.node,
                "SAGA_COMPENSATION_FAILED",
                f"Compensation failed for {step.tool_name}",
                {"saga_step_id": step.id, "tool": step.tool_name, "error": step.error},
            )
            db.commit()
        raise


def compensate_workflow_saga(
    db: Session,
    workflow_id: int,
    *,
    max_attempts: int = 3,
) -> list[WorkflowSagaStep]:
    started = perf_counter()
    try:
        steps = list(
            db.scalars(
                select(WorkflowSagaStep)
                .where(
                    WorkflowSagaStep.workflow_id == workflow_id,
                    WorkflowSagaStep.status.in_(
                        {
                            SagaStepStatus.completed,
                            SagaStepStatus.compensating,
                            SagaStepStatus.compensation_failed,
                        }
                    ),
                )
                .order_by(WorkflowSagaStep.sequence.desc(), WorkflowSagaStep.id.desc())
            )
        )
        for step in steps:
            while step.status != SagaStepStatus.compensated:
                try:
                    _compensate_step(db, step.id)
                except SagaCompensationConflict:
                    raise
                except Exception as exc:
                    db.refresh(step)
                    if step.compensation_attempts >= max_attempts:
                        raise SagaCompensationError(
                            f"Compensation failed after {step.compensation_attempts} attempts: {exc}"
                        ) from exc
                db.refresh(step)
        return steps
    finally:
        SAGA_COMPENSATION_DURATION.observe(perf_counter() - started)


def earliest_compensated_node(db: Session, workflow_id: int) -> str | None:
    step = db.scalar(
        select(WorkflowSagaStep)
        .where(
            WorkflowSagaStep.workflow_id == workflow_id,
            WorkflowSagaStep.status == SagaStepStatus.compensated,
        )
        .order_by(WorkflowSagaStep.sequence, WorkflowSagaStep.id)
        .limit(1)
    )
    return step.node if step else None
