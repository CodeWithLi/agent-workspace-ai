import json

import pytest
from starlette.requests import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Project,
    Report,
    SagaStepStatus,
    Task,
    TaskComment,
    User,
    WorkflowEvent,
    WorkflowRun,
    WorkflowSagaStep,
    WorkflowStatus,
)
from app.api.routes.workflow import cancel_workflow, retry_workflow_compensation
from app.services.workflow_saga import (
    SagaCompensationConflict,
    SagaStateError,
    WorkflowLeaseLost,
    compensate_workflow_saga,
    execute_report_creation,
    execute_task_creation,
    transition_saga_step,
)
from app.services.workflows import process_workflow


def saga_context(db: Session) -> tuple[User, Project, WorkflowRun]:
    user = User(
        email="saga@example.com",
        name="Saga",
        password_hash="hash",
        permissions="projects:write",
    )
    db.add(user)
    db.flush()
    project = Project(name="Saga Project", description="Durable writes", owner_id=user.id)
    db.add(project)
    db.flush()
    workflow = WorkflowRun(
        project_id=project.id,
        user_id=user.id,
        status=WorkflowStatus.running,
        current_node="project_manager",
        state_json="{}",
        lease_token="lease-current",
        attempt_count=1,
        max_attempts=1,
    )
    db.add(workflow)
    db.commit()
    return user, project, workflow


def http_request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
    )


def test_saga_writes_are_idempotent_and_compensate_in_reverse_order(db: Session) -> None:
    _user, project, workflow = saga_context(db)

    first = execute_task_creation(
        db,
        workflow,
        ["Implement API", "Verify rollback"],
        expected_lease_token="lease-current",
    )
    repeated = execute_task_creation(
        db,
        workflow,
        ["Implement API", "Verify rollback"],
        expected_lease_token="lease-current",
    )
    execute_report_creation(
        db,
        workflow,
        title="Final report",
        content="Committed output",
        expected_lease_token="lease-current",
    )

    assert repeated == first
    assert db.scalar(select(func.count(Task.id)).where(Task.project_id == project.id)) == 2
    assert db.scalar(select(func.count(Report.id)).where(Report.project_id == project.id)) == 1
    assert db.scalar(
        select(func.count(WorkflowSagaStep.id)).where(WorkflowSagaStep.workflow_id == workflow.id)
    ) == 2

    compensate_workflow_saga(db, workflow.id)

    assert db.scalar(select(func.count(Task.id)).where(Task.project_id == project.id)) == 0
    assert db.scalar(select(func.count(Report.id)).where(Report.project_id == project.id)) == 0
    steps = list(
        db.scalars(
            select(WorkflowSagaStep)
            .where(WorkflowSagaStep.workflow_id == workflow.id)
            .order_by(WorkflowSagaStep.sequence)
        )
    )
    assert [step.status for step in steps] == [SagaStepStatus.compensated, SagaStepStatus.compensated]
    compensation_events = list(
        db.scalars(
            select(WorkflowEvent)
            .where(
                WorkflowEvent.workflow_id == workflow.id,
                WorkflowEvent.event_type == "SAGA_STEP_COMPENSATED",
            )
            .order_by(WorkflowEvent.id)
        )
    )
    assert [event.node for event in compensation_events] == ["report", "project_manager"]


def test_interrupted_execution_log_is_resumed_without_duplicate_write(db: Session) -> None:
    _user, project, workflow = saga_context(db)
    step = WorkflowSagaStep(
        workflow_id=workflow.id,
        sequence=10,
        node="project_manager",
        tool_name="task_create",
        compensation_action="delete_created_tasks",
        idempotency_key="project_manager:create_tasks",
        status=SagaStepStatus.executing,
        input_json=json.dumps({"project_id": project.id, "titles": ["Recovered"]}),
        transition_log_json="[]",
    )
    db.add(step)
    db.commit()

    output = execute_task_creation(
        db,
        workflow,
        ["Recovered"],
        expected_lease_token="lease-current",
    )

    db.refresh(step)
    assert [item["title"] for item in output["created_tasks"]] == ["Recovered"]
    assert step.status == SagaStepStatus.completed
    assert step.execute_attempts == 1
    assert db.scalar(select(func.count(Task.id)).where(Task.project_id == project.id)) == 1
    transitions = json.loads(step.transition_log_json)
    assert [item["to"] for item in transitions] == ["FAILED", "EXECUTING", "COMPLETED"]


def test_compensation_refuses_to_delete_business_data_changed_by_a_human(db: Session) -> None:
    _user, project, workflow = saga_context(db)
    output = execute_task_creation(
        db,
        workflow,
        ["Human owned task"],
        expected_lease_token="lease-current",
    )
    task = db.get(Task, output["created_tasks"][0]["id"])
    task.title = "Human changed this task"
    db.commit()

    with pytest.raises(SagaCompensationConflict):
        compensate_workflow_saga(db, workflow.id, max_attempts=1)

    step = db.scalar(select(WorkflowSagaStep).where(WorkflowSagaStep.workflow_id == workflow.id))
    assert step.status == SagaStepStatus.compensation_failed
    assert db.get(Task, task.id).title == "Human changed this task"


def test_compensation_preserves_task_with_human_comment(db: Session) -> None:
    user, _project, workflow = saga_context(db)
    output = execute_task_creation(
        db,
        workflow,
        ["Discuss before rollback"],
        expected_lease_token="lease-current",
    )
    task_id = output["created_tasks"][0]["id"]
    db.add(TaskComment(task_id=task_id, user_id=user.id, content="Keep this decision"))
    db.commit()

    with pytest.raises(SagaCompensationConflict):
        compensate_workflow_saga(db, workflow.id, max_attempts=1)

    assert db.get(Task, task_id) is not None
    assert db.scalar(select(func.count(TaskComment.id)).where(TaskComment.task_id == task_id)) == 1


@pytest.mark.asyncio
async def test_terminal_workflow_failure_compensates_writes_and_sets_restart_node(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _user, project, workflow = saga_context(db)
    execute_task_creation(
        db,
        workflow,
        ["Temporary task"],
        expected_lease_token="lease-current",
    )
    workflow.current_node = "tester"
    db.commit()

    async def fail_graph(*_args, **_kwargs):
        raise RuntimeError("tester unavailable")

    monkeypatch.setattr("app.services.workflows.execute_workspace_graph", fail_graph)
    result = await process_workflow(db, workflow.id, claimed=True)

    assert result.status == WorkflowStatus.failed
    assert result.current_node == "project_manager"
    assert "tester unavailable" in result.error
    assert db.scalar(select(func.count(Task.id)).where(Task.project_id == project.id)) == 0
    step = db.scalar(select(WorkflowSagaStep).where(WorkflowSagaStep.workflow_id == workflow.id))
    assert step.status == SagaStepStatus.compensated


def test_stale_worker_cannot_commit_a_saga_write(db: Session) -> None:
    _user, project, workflow = saga_context(db)
    workflow.lease_token = "lease-new-owner"
    db.commit()

    with pytest.raises(WorkflowLeaseLost):
        execute_task_creation(
            db,
            workflow,
            ["Must not exist"],
            expected_lease_token="lease-old-owner",
        )

    assert db.scalar(select(func.count(Task.id)).where(Task.project_id == project.id)) == 0
    step = db.scalar(select(WorkflowSagaStep).where(WorkflowSagaStep.workflow_id == workflow.id))
    assert step.status == SagaStepStatus.failed


def test_saga_state_machine_rejects_illegal_jump(db: Session) -> None:
    _user, _project, workflow = saga_context(db)
    step = WorkflowSagaStep(
        workflow_id=workflow.id,
        sequence=10,
        node="project_manager",
        tool_name="task_create",
        compensation_action="delete_created_tasks",
        idempotency_key="illegal-transition",
        status=SagaStepStatus.pending,
    )

    with pytest.raises(SagaStateError):
        transition_saga_step(step, SagaStepStatus.completed)


def test_paused_workflow_cancel_compensates_and_manual_retry_resolves_conflict(db: Session) -> None:
    user, project, workflow = saga_context(db)
    output = execute_task_creation(
        db,
        workflow,
        ["Review before cancellation"],
        expected_lease_token="lease-current",
    )
    task = db.get(Task, output["created_tasks"][0]["id"])
    task.title = "Human edit blocks rollback"
    workflow.status = WorkflowStatus.paused
    workflow.current_node = "report"
    workflow.lease_token = None
    db.commit()

    conflicted = cancel_workflow(
        workflow.id,
        http_request(f"/api/v1/workflow/{workflow.id}/cancel"),
        user,
        db,
    )
    assert conflicted.status == WorkflowStatus.compensation_failed
    assert db.get(Task, task.id) is not None

    task = db.get(Task, task.id)
    task.title = "Review before cancellation"
    db.commit()
    recovered = retry_workflow_compensation(
        workflow.id,
        http_request(f"/api/v1/workflow/{workflow.id}/retry-compensation"),
        user,
        db,
    )

    assert recovered.status == WorkflowStatus.cancelled
    assert db.scalar(select(func.count(Task.id)).where(Task.project_id == project.id)) == 0
