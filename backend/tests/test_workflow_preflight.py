from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.agent.service import ensure_default_agents
from app.api.routes.workflow import preflight_workflow, run_workflow
from app.langgraph.workflow import snapshot_agent_configs
from app.models import Agent, AgentRole, AgentTool, Project, TokenTransaction, User, UserRole, WorkflowEvent, WorkflowRun, WorkflowStatus
from app.schemas import WorkflowPreflightRequest, WorkflowRequest


def http_request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 1234),
        }
    )


def create_workspace(db: Session, email: str) -> tuple[User, Project]:
    user = User(
        email=email,
        name="Preflight Owner",
        password_hash="hash",
        role=UserRole.member,
        permissions="projects:write",
        ai_token_balance=1000,
    )
    db.add(user)
    db.flush()
    project = Project(name="Preflight Project", description="Validate team before billing", owner_id=user.id)
    db.add(project)
    db.commit()
    return user, project


def test_workflow_preflight_is_read_only_and_reports_eligible_team(db: Session) -> None:
    ensure_default_agents(db)
    user, project = create_workspace(db, "preflight-ready@example.com")

    result = preflight_workflow(
        WorkflowPreflightRequest(project_id=project.id, user_input="设计可灰度发布的会员平台"),
        user,
        db,
    )

    assert result.ready is True
    assert result.required_capabilities == []
    assert result.eligible_count == 4
    assert result.minimum_required == 2
    assert result.blockers == []
    assert {profile.role for profile in result.specialists if profile.eligible} == {
        "test_engineer",
        "operations_analyst",
        "knowledge_admin",
        "notification_secretary",
    }
    assert result.team_performance_profile.project_id == project.id
    assert result.team_performance_profile.workflow_count == 0
    assert result.team_performance_profile.configuration_scope == "CURRENT_CONFIGURATION"
    assert result.team_performance_profile.branch_sample_count == 0
    assert result.team_performance_profile.excluded_branch_sample_count == 0
    assert result.team_performance_profile.observed_role_count == 0
    assert {item.role for item in result.team_performance_profile.roles} == {
        "test_engineer",
        "operations_analyst",
        "knowledge_admin",
        "notification_secretary",
    }
    assert all(
        item.evidence_level == "INSUFFICIENT"
        for item in result.team_performance_profile.roles
    )
    assert db.scalar(select(func.count(WorkflowRun.id))) == 0
    assert db.scalar(select(func.count(TokenTransaction.id))) == 0
    assert db.get(User, user.id).ai_token_balance == 1000


def test_workflow_preflight_uses_only_current_agent_configuration_history(
    db: Session,
) -> None:
    ensure_default_agents(db)
    user, project = create_workspace(db, "preflight-aligned@example.com")
    current_snapshot = snapshot_agent_configs(db, user.role)
    stale_snapshot = json.loads(json.dumps(current_snapshot))
    stale_snapshot["test_engineer"]["model"] = "retired-model"

    for snapshot in (current_snapshot, stale_snapshot):
        workflow = WorkflowRun(
            project_id=project.id,
            user_id=user.id,
            status=WorkflowStatus.completed,
            current_node="completed",
            state_json=json.dumps({"agent_snapshot": snapshot}),
        )
        db.add(workflow)
        db.flush()
        db.add_all(
            [
                WorkflowEvent(
                    workflow_id=workflow.id,
                    node="specialists",
                    event_type="BRANCH_STARTED",
                    message="started",
                    payload_json=json.dumps(
                        {"role": "test_engineer", "wave": 1, "branch_attempt": 1}
                    ),
                ),
                WorkflowEvent(
                    workflow_id=workflow.id,
                    node="specialists",
                    event_type="BRANCH_COMPLETED",
                    message="completed",
                    payload_json=json.dumps(
                        {"role": "test_engineer", "wave": 1, "branch_attempt": 1}
                    ),
                ),
            ]
        )
    db.commit()

    result = preflight_workflow(
        WorkflowPreflightRequest(project_id=project.id, user_input="规划可验证交付"),
        user,
        db,
    )

    profile = result.team_performance_profile
    evidence = profile.for_role("test_engineer")
    assert profile.workflow_count == 2
    assert profile.branch_sample_count == 1
    assert profile.excluded_branch_sample_count == 1
    assert evidence is not None
    assert evidence.sample_count == 1
    assert evidence.excluded_sample_count == 1


@pytest.mark.asyncio
async def test_preflight_and_run_block_missing_required_capability_before_billing(
    db: Session,
) -> None:
    ensure_default_agents(db)
    user, project = create_workspace(db, "preflight-blocked@example.com")
    notification = db.scalar(
        select(Agent).where(Agent.role == AgentRole.notification_secretary)
    )
    delivery_tool = db.scalar(
        select(AgentTool).where(
            AgentTool.agent_id == notification.id,
            AgentTool.name == "notification_create",
        )
    )
    delivery_tool.allowed_roles = "admin"
    db.commit()

    preflight = preflight_workflow(
        WorkflowPreflightRequest(project_id=project.id, user_input="生成并发送项目邮件通知"),
        user,
        db,
    )

    assert preflight.ready is False
    assert preflight.required_capabilities == ["notification_delivery"]
    assert "notification_delivery" not in preflight.available_capabilities
    assert preflight.blockers == ["当前团队缺少所需能力：通知投递。"]
    profile = next(item for item in preflight.specialists if item.role == "notification_secretary")
    assert profile.eligible is True
    assert "notification_delivery" not in profile.capabilities

    with pytest.raises(HTTPException) as blocked:
        await run_workflow(
            WorkflowRequest(
                project_id=project.id,
                user_input="生成并发送项目邮件通知",
                request_id="preflight-blocked-run",
            ),
            http_request("/api/v1/workflow/run"),
            user,
            db,
        )
    assert blocked.value.status_code == 422
    assert "通知投递" in blocked.value.detail
    assert db.scalar(select(func.count(WorkflowRun.id))) == 0
    assert db.scalar(select(func.count(TokenTransaction.id))) == 0
    assert db.get(User, user.id).ai_token_balance == 1000


def test_workflow_preflight_requires_two_eligible_specialists(db: Session) -> None:
    ensure_default_agents(db)
    user, project = create_workspace(db, "preflight-capacity@example.com")
    test_agent = db.scalar(select(Agent).where(Agent.role == AgentRole.test_engineer))
    for tool in db.scalars(select(AgentTool).where(AgentTool.agent_id != test_agent.id)):
        tool.enabled = False
    db.commit()

    result = preflight_workflow(
        WorkflowPreflightRequest(project_id=project.id, user_input="规划普通项目交付"),
        user,
        db,
    )

    assert result.ready is False
    assert result.eligible_count == 1
    assert result.blockers == ["至少需要 2 个可用专业 Agent，当前仅 1 个。"]
    assert [profile.role for profile in result.specialists if profile.eligible] == [
        "test_engineer"
    ]


@pytest.mark.asyncio
async def test_workflow_run_freezes_team_performance_and_emits_count_only_snapshot(
    db: Session,
) -> None:
    ensure_default_agents(db)
    user, project = create_workspace(db, "preflight-freeze@example.com")

    response = await run_workflow(
        WorkflowRequest(
            project_id=project.id,
            user_input="规划可灰度发布并可验证的企业协作流程",
            request_id="performance-profile-freeze",
            require_plan_approval=True,
        ),
        http_request("/api/v1/workflow/run"),
        user,
        db,
    )

    workflow = db.get(WorkflowRun, response.workflow_id)
    assert workflow is not None
    state = json.loads(workflow.state_json)
    profile = state["team_performance_profile"]
    assert profile["project_id"] == project.id
    assert profile["workflow_count"] == 0
    assert profile["branch_sample_count"] == 0
    assert profile["configuration_scope"] == "CURRENT_CONFIGURATION"
    assert profile["excluded_branch_sample_count"] == 0
    assert len(profile["roles"]) == 4
    event = db.scalar(
        select(WorkflowEvent).where(
            WorkflowEvent.workflow_id == workflow.id,
            WorkflowEvent.event_type == "TEAM_PERFORMANCE_SNAPSHOTTED",
        )
    )
    assert event is not None
    assert json.loads(event.payload_json) == {
        "workflow_count": 0,
        "branch_sample_count": 0,
        "excluded_branch_sample_count": 0,
        "observed_role_count": 0,
        "sufficient_role_count": 0,
    }
