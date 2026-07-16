import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.agent.service import ensure_default_agents, infer_tool_calls
from app.api.routes.agents import approve_agent_action, reject_agent_action
from app.models import Agent, AgentAction, AgentRole, Project, Task, User, UserRole


def request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/agents/actions/1/approve",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 1234),
        }
    )


def setup_action_context(db: Session) -> tuple[User, Project, Agent]:
    ensure_default_agents(db)
    user = User(
        email="approver@example.com",
        name="Approver",
        password_hash="hash",
        role=UserRole.member,
        permissions="agents:read,projects:write",
    )
    db.add(user)
    db.flush()
    project = Project(name="Approval", description="", owner_id=user.id)
    db.add(project)
    db.flush()
    agent = db.scalar(select(Agent).where(Agent.role == AgentRole.project_manager))
    assert agent is not None
    assert agent.human_approval_required is True
    return user, project, agent


@pytest.mark.asyncio
async def test_pending_task_action_is_idempotent_and_executes_once(db: Session) -> None:
    user, project, agent = setup_action_context(db)

    first = await infer_tool_calls(db, user, agent, project, "请拆解并创建任务")
    second = await infer_tool_calls(db, user, agent, project, "请拆解并创建任务")
    first_output = first[-1]["output"]
    second_output = second[-1]["output"]

    assert first_output["status"] == "PENDING_APPROVAL"
    assert first_output["action_id"] == second_output["action_id"]
    assert db.scalar(select(func.count(AgentAction.id))) == 1
    assert db.scalar(select(func.count(Task.id))) == 0

    action = approve_agent_action(first_output["action_id"], request(), user, db)
    assert action.status == "EXECUTED"
    assert db.scalar(select(func.count(Task.id))) == 5

    with pytest.raises(HTTPException) as repeated:
        approve_agent_action(action.id, request(), user, db)
    assert repeated.value.status_code == 409
    assert db.scalar(select(func.count(Task.id))) == 5


@pytest.mark.asyncio
async def test_revoked_tool_cannot_be_approved(db: Session) -> None:
    user, project, agent = setup_action_context(db)
    calls = await infer_tool_calls(db, user, agent, project, "请创建任务")
    action_id = calls[-1]["output"]["action_id"]
    task_tool = next(tool for tool in agent.tool_links if tool.name == "task_create")
    task_tool.enabled = False
    db.flush()

    with pytest.raises(HTTPException) as revoked:
        approve_agent_action(action_id, request(), user, db)
    assert revoked.value.status_code == 409
    assert db.scalar(select(func.count(Task.id))) == 0
    assert db.get(AgentAction, action_id).status == "PENDING"


@pytest.mark.asyncio
async def test_rejected_action_never_creates_tasks(db: Session) -> None:
    user, project, agent = setup_action_context(db)
    calls = await infer_tool_calls(db, user, agent, project, "请创建任务")
    action_id = calls[-1]["output"]["action_id"]

    action = reject_agent_action(action_id, request(), user, db)
    assert action.status == "REJECTED"
    assert db.scalar(select(func.count(Task.id))) == 0
