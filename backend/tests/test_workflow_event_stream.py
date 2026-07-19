import json

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session, sessionmaker

from app.api.routes import workflow as workflow_routes
from app.api.routes.workflow import list_workflow_event_history, stream_workflow_events
from app.models import Project, User, WorkflowEvent, WorkflowRun, WorkflowStatus
from app.workflow_events import public_workflow_event_payload


def workflow_context(
    db: Session,
    suffix: str = "owner",
    *,
    status: WorkflowStatus = WorkflowStatus.running,
) -> tuple[User, Project, WorkflowRun]:
    user = User(
        email=f"workflow-stream-{suffix}@example.com",
        name=f"Workflow Stream {suffix}",
        password_hash="hash",
    )
    db.add(user)
    db.flush()
    project = Project(name=f"Workflow Stream {suffix}", owner_id=user.id)
    db.add(project)
    db.flush()
    workflow = WorkflowRun(
        project_id=project.id,
        user_id=user.id,
        status=status,
        current_node="product",
        state_json="{}",
    )
    db.add(workflow)
    db.commit()
    return user, project, workflow


def add_event(db: Session, workflow: WorkflowRun, event_type: str, sequence: int) -> WorkflowEvent:
    event = WorkflowEvent(
        workflow_id=workflow.id,
        node="completed" if event_type == "COMPLETED" else "product",
        event_type=event_type,
        message=f"event {sequence}",
        payload_json=json.dumps(
            {
                "plan_version": sequence,
                "decision_count": sequence,
                "conflict_count": 1,
                "open_blocker_count": 0,
                "recovery_count": sequence,
                "retryable_count": 1,
                "lineage_sealed": True,
                "upstream_count": sequence - 1,
                "reviewer_count": 3,
                "reviewer_valid_count": 3,
                "reviewer_quorum": 2,
                "reviewer_pass_count": sequence,
                "reviewer_disagreement_count": 3 - sequence,
                "input_fingerprint": "a" * 64,
                "output_fingerprint": "b" * 64,
                "error": f"secret-error-{sequence}",
                "human_feedback": f"secret-feedback-{sequence}",
                "prompt": f"secret-prompt-{sequence}",
            }
        ),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def test_plan_deliberation_event_exposes_summary_without_candidate_content() -> None:
    payload = public_workflow_event_payload(
        {
            "candidate_count": 3,
            "distinct_candidate_count": 2,
            "invalid_candidate_count": 1,
            "ready_candidate_count": 1,
            "commitment_count": 6,
            "commitment_accept_count": 4,
            "commitment_challenge_count": 1,
            "commitment_abstain_count": 1,
            "selected_candidate_id": "risk_control",
            "arbitration_mode": "independent_arbiter",
            "score": 94,
            "plan_version": 2,
            "candidates": [{"objective": "secret candidate plan"}],
            "selection_reason": "secret arbiter reasoning",
            "plan_fingerprint": "a" * 64,
        }
    )

    assert payload == {
        "candidate_count": 3,
        "distinct_candidate_count": 2,
        "invalid_candidate_count": 1,
        "ready_candidate_count": 1,
        "commitment_count": 6,
        "commitment_accept_count": 4,
        "commitment_challenge_count": 1,
        "commitment_abstain_count": 1,
        "selected_candidate_id": "risk_control",
        "arbitration_mode": "independent_arbiter",
        "score": 94,
        "plan_version": 2,
    }


def test_event_history_returns_latest_window_in_chronological_order_and_is_tenant_scoped(
    db: Session,
) -> None:
    owner, _project, workflow = workflow_context(db)
    outsider, _other_project, _other_workflow = workflow_context(db, "outsider")
    events = [add_event(db, workflow, "NODE_COMPLETED", sequence) for sequence in range(1, 4)]

    history = list_workflow_event_history(workflow.id, limit=2, current_user=owner, db=db)

    assert [event.id for event in history] == [events[1].id, events[2].id]
    assert [event.payload for event in history] == [
        {"plan_version": 2, "decision_count": 2, "conflict_count": 1, "open_blocker_count": 0, "recovery_count": 2, "retryable_count": 1, "lineage_sealed": True, "upstream_count": 1, "reviewer_count": 3, "reviewer_valid_count": 3, "reviewer_quorum": 2, "reviewer_pass_count": 2, "reviewer_disagreement_count": 1},
        {"plan_version": 3, "decision_count": 3, "conflict_count": 1, "open_blocker_count": 0, "recovery_count": 3, "retryable_count": 1, "lineage_sealed": True, "upstream_count": 2, "reviewer_count": 3, "reviewer_valid_count": 3, "reviewer_quorum": 2, "reviewer_pass_count": 3, "reviewer_disagreement_count": 0},
    ]
    assert "secret-" not in "".join(event.model_dump_json() for event in history)
    with pytest.raises(HTTPException) as hidden:
        list_workflow_event_history(workflow.id, limit=100, current_user=outsider, db=db)
    assert hidden.value.status_code == 404


@pytest.mark.asyncio
async def test_workflow_sse_resumes_after_header_cursor_and_emits_reconnect_contract(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, _project, workflow = workflow_context(db, status=WorkflowStatus.completed)
    first = add_event(db, workflow, "NODE_COMPLETED", 1)
    terminal = add_event(db, workflow, "COMPLETED", 2)
    monkeypatch.setattr(workflow_routes, "SessionLocal", sessionmaker(bind=db.get_bind()))

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(workflow_routes.asyncio, "sleep", no_sleep)
    response = await stream_workflow_events(
        workflow.id,
        last_event_id=0,
        header_event_id=str(first.id),
        current_user=owner,
        db=db,
    )
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
    body = "".join(chunks)

    assert response.media_type == "text/event-stream"
    assert response.headers["connection"] == "keep-alive"
    assert "retry: 1500" in body
    assert f"id: {terminal.id}" in body
    assert f"id: {first.id}\n" not in body
    assert '"event_type":"COMPLETED"' in body
    assert '"payload":{"plan_version":2,"decision_count":2,"conflict_count":1,"open_blocker_count":0,"recovery_count":2,"retryable_count":1,"lineage_sealed":true,"upstream_count":1,"reviewer_count":3,"reviewer_valid_count":3,"reviewer_quorum":2,"reviewer_pass_count":2,"reviewer_disagreement_count":1}' in body
    assert "secret-" not in body


@pytest.mark.asyncio
async def test_workflow_sse_revalidates_user_access_during_a_live_connection(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, _project, workflow = workflow_context(db)
    event = add_event(db, workflow, "NODE_COMPLETED", 1)
    monkeypatch.setattr(workflow_routes, "SessionLocal", sessionmaker(bind=db.get_bind()))
    response = await stream_workflow_events(
        workflow.id,
        last_event_id=0,
        header_event_id=None,
        current_user=owner,
        db=db,
    )

    owner.is_active = False
    db.commit()
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
    body = "".join(chunks)

    assert "retry: 1500" in body
    assert f"id: {event.id}" not in body
