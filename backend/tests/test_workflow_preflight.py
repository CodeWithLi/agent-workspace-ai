from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.agent.service import ensure_default_agents
from app.api.routes.workflow import preflight_workflow, run_workflow
from app.models import Agent, AgentRole, AgentTool, Project, TokenTransaction, User, UserRole, WorkflowRun
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
    assert db.scalar(select(func.count(WorkflowRun.id))) == 0
    assert db.scalar(select(func.count(TokenTransaction.id))) == 0
    assert db.get(User, user.id).ai_token_balance == 1000


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
