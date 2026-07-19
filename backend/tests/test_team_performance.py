from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.service import ensure_default_agents
from app.agent.team_performance import build_team_performance_profile
from app.langgraph.workflow import snapshot_agent_configs
from app.models import (
    Agent,
    AgentRole,
    LLMUsage,
    Project,
    User,
    WorkflowEvent,
    WorkflowRun,
    WorkflowStatus,
)


def add_branch_event(
    db: Session,
    workflow_id: int,
    event_type: str,
    role: str,
    created_at: datetime,
    *,
    branch_attempt: int = 1,
) -> None:
    db.add(
        WorkflowEvent(
            workflow_id=workflow_id,
            node=(
                "quality_gate"
                if event_type in {"REVISION_REQUESTED", "QUALITY_GATE_FAILED"}
                else "specialists"
            ),
            event_type=event_type,
            message=event_type,
            payload_json=json.dumps(
                {
                    "role": role,
                    "revision_roles": (
                        [role]
                        if event_type in {"REVISION_REQUESTED", "QUALITY_GATE_FAILED"}
                        else []
                    ),
                    "wave": 1,
                    "revision_round": 0,
                    "workflow_attempt": 1,
                    "branch_attempt": branch_attempt,
                }
            ),
            created_at=created_at,
        )
    )


def create_terminal_workflow(
    db: Session,
    project: Project,
    user: User,
    status: WorkflowStatus,
    finished_at: datetime,
    *,
    state: dict | None = None,
) -> WorkflowRun:
    workflow = WorkflowRun(
        project_id=project.id,
        user_id=user.id,
        status=status,
        current_node="completed",
        state_json=json.dumps(state or {}),
        finished_at=finished_at,
    )
    db.add(workflow)
    db.flush()
    return workflow


def test_team_performance_profile_aggregates_final_role_outcomes_and_telemetry(
    db: Session,
) -> None:
    ensure_default_agents(db)
    user = User(email="performance@example.com", name="Performance", password_hash="hash")
    db.add(user)
    db.flush()
    project = Project(name="Observed Project", owner_id=user.id)
    other_project = Project(name="Other Project", owner_id=user.id)
    db.add_all([project, other_project])
    db.flush()
    test_agent = db.scalar(select(Agent).where(Agent.role == AgentRole.test_engineer))
    assert test_agent is not None
    started = datetime(2026, 7, 19, 8, 0, tzinfo=timezone.utc)

    first = create_terminal_workflow(db, project, user, WorkflowStatus.completed, started)
    add_branch_event(db, first.id, "BRANCH_STARTED", "test_engineer", started)
    add_branch_event(db, first.id, "BRANCH_COMPLETED", "test_engineer", started + timedelta(seconds=1))

    second = create_terminal_workflow(
        db, project, user, WorkflowStatus.completed, started + timedelta(minutes=1)
    )
    add_branch_event(db, second.id, "BRANCH_STARTED", "test_engineer", started + timedelta(minutes=1))
    add_branch_event(
        db,
        second.id,
        "BRANCH_FAILED",
        "test_engineer",
        started + timedelta(minutes=1, milliseconds=500),
    )
    add_branch_event(
        db,
        second.id,
        "BRANCH_RETRY_SCHEDULED",
        "test_engineer",
        started + timedelta(minutes=1, milliseconds=500),
    )
    add_branch_event(
        db,
        second.id,
        "BRANCH_STARTED",
        "test_engineer",
        started + timedelta(minutes=1, seconds=1),
        branch_attempt=2,
    )
    add_branch_event(
        db,
        second.id,
        "BRANCH_COMPLETED",
        "test_engineer",
        started + timedelta(minutes=1, seconds=2),
        branch_attempt=2,
    )
    add_branch_event(
        db,
        second.id,
        "REVISION_REQUESTED",
        "test_engineer",
        started + timedelta(minutes=1, seconds=3),
    )

    third = create_terminal_workflow(
        db, project, user, WorkflowStatus.failed, started + timedelta(minutes=2)
    )
    add_branch_event(db, third.id, "BRANCH_STARTED", "test_engineer", started + timedelta(minutes=2))
    add_branch_event(
        db,
        third.id,
        "BRANCH_FAILED",
        "test_engineer",
        started + timedelta(minutes=2, seconds=2),
    )

    ignored = create_terminal_workflow(
        db, other_project, user, WorkflowStatus.completed, started + timedelta(minutes=3)
    )
    add_branch_event(db, ignored.id, "BRANCH_STARTED", "test_engineer", started + timedelta(minutes=3))
    add_branch_event(
        db,
        ignored.id,
        "BRANCH_COMPLETED",
        "test_engineer",
        started + timedelta(minutes=3, seconds=10),
    )
    active = WorkflowRun(
        project_id=project.id,
        user_id=user.id,
        status=WorkflowStatus.running,
        current_node="specialists",
        state_json="{}",
    )
    db.add(active)
    db.flush()
    add_branch_event(db, active.id, "BRANCH_STARTED", "test_engineer", started + timedelta(minutes=4))
    add_branch_event(
        db,
        active.id,
        "BRANCH_COMPLETED",
        "test_engineer",
        started + timedelta(minutes=4, seconds=20),
    )

    for workflow, timestamp, cost in (
        (first, started + timedelta(milliseconds=750), 100),
        (second, started + timedelta(minutes=1, milliseconds=250), 100),
        (second, started + timedelta(minutes=1, seconds=1, milliseconds=750), 200),
        (third, started + timedelta(minutes=2, seconds=1), 500),
    ):
        db.add(
            LLMUsage(
                user_id=user.id,
                project_id=project.id,
                agent_id=test_agent.id,
                workflow_id=workflow.id,
                operation="chat",
                provider="test",
                model="test-model",
                estimated_cost_micros=cost,
                latency_ms=100,
                created_at=timestamp,
            )
        )
    db.commit()

    profile = build_team_performance_profile(
        db,
        project.id,
        roles=["test_engineer", "operations_analyst"],
        now=started + timedelta(hours=1),
    )

    assert profile.workflow_count == 3
    assert profile.branch_sample_count == 3
    assert profile.observed_role_count == 1
    assert profile.sufficient_role_count == 1
    evidence = profile.for_role("test_engineer")
    assert evidence is not None
    assert evidence.sample_count == 3
    assert evidence.success_count == 2
    assert evidence.failure_count == 1
    assert evidence.retry_count == 1
    assert evidence.revision_count == 1
    assert evidence.success_rate == pytest.approx(2 / 3, abs=0.0001)
    assert evidence.retry_rate == pytest.approx(1 / 3, abs=0.0001)
    assert evidence.revision_rate == pytest.approx(1 / 3, abs=0.0001)
    assert evidence.reliability_score == pytest.approx(0.6625)
    assert evidence.median_latency_ms == 1500
    assert evidence.average_cost_micros == 300
    assert evidence.evidence_level == "LOW"
    unobserved = profile.for_role("operations_analyst")
    assert unobserved is not None
    assert unobserved.sample_count == 0
    assert unobserved.evidence_level == "INSUFFICIENT"


def test_team_performance_profile_excludes_stale_agent_configs_and_counts_quality_failures(
    db: Session,
) -> None:
    ensure_default_agents(db)
    user = User(email="aligned-performance@example.com", name="Aligned", password_hash="hash")
    db.add(user)
    db.flush()
    project = Project(name="Configuration Aligned", owner_id=user.id)
    db.add(project)
    db.flush()
    current_snapshot = snapshot_agent_configs(db)
    started = datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)

    for index in range(3):
        workflow = create_terminal_workflow(
            db,
            project,
            user,
            WorkflowStatus.completed,
            started + timedelta(minutes=index),
            state={"agent_snapshot": current_snapshot},
        )
        branch_started = started + timedelta(minutes=index)
        add_branch_event(db, workflow.id, "BRANCH_STARTED", "test_engineer", branch_started)
        add_branch_event(
            db,
            workflow.id,
            "BRANCH_COMPLETED",
            "test_engineer",
            branch_started + timedelta(seconds=1),
        )
        if index == 2:
            add_branch_event(
                db,
                workflow.id,
                "QUALITY_GATE_FAILED",
                "test_engineer",
                branch_started + timedelta(seconds=2),
            )

    stale_snapshot = json.loads(json.dumps(current_snapshot))
    stale_snapshot["test_engineer"]["prompt_version"] -= 1
    stale = create_terminal_workflow(
        db,
        project,
        user,
        WorkflowStatus.completed,
        started + timedelta(minutes=4),
        state={"agent_snapshot": stale_snapshot},
    )
    add_branch_event(db, stale.id, "BRANCH_STARTED", "test_engineer", started + timedelta(minutes=4))
    add_branch_event(
        db,
        stale.id,
        "BRANCH_COMPLETED",
        "test_engineer",
        started + timedelta(minutes=4, seconds=1),
    )
    db.commit()

    profile = build_team_performance_profile(
        db,
        project.id,
        roles=["test_engineer"],
        current_agent_snapshot=current_snapshot,
        now=started + timedelta(hours=1),
    )

    assert profile.configuration_scope == "CURRENT_CONFIGURATION"
    assert profile.workflow_count == 4
    assert profile.branch_sample_count == 3
    assert profile.excluded_branch_sample_count == 1
    evidence = profile.for_role("test_engineer")
    assert evidence is not None
    assert evidence.sample_count == 3
    assert evidence.excluded_sample_count == 1
    assert evidence.success_count == 3
    assert evidence.quality_failure_count == 1
    assert evidence.quality_failure_rate == pytest.approx(1 / 3, abs=0.0001)
    assert evidence.reliability_score == pytest.approx(0.7812)
    assert evidence.evidence_level == "LOW"
