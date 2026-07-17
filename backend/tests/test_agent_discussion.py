import json

import pytest
from fastapi import HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.agent import discussion as discussion_service
from app.agent.discussion import DISCUSSION_ROLES, select_discussion_agents, stream_discussion_events
from app.agent.service import ensure_default_agents
from app.api.routes.agents import create_agent_run, discussion_stream
from app.models import AgentRun, Conversation, Message, Project, TokenTransaction, User, UserRole
from app.schemas import DiscussionRequest
from app.services.billing import apply_token_change


def create_discussion_context(db: Session) -> tuple[User, Project, AgentRun]:
    ensure_default_agents(db)
    user = User(
        email="discussion@example.com",
        name="Discussion Owner",
        password_hash="hash",
        role=UserRole.member,
        permissions="agents:read,projects:write",
        ai_token_balance=500,
    )
    db.add(user)
    db.flush()
    project = Project(name="Discussion Project", description="Build a collaboration product", owner_id=user.id)
    db.add(project)
    db.flush()
    coordinator = select_discussion_agents(db)[-1]
    run = AgentRun(
        request_id="discussion-request-001",
        user_id=user.id,
        project_id=project.id,
        agent_id=coordinator.id,
        status="RUNNING",
    )
    db.add(run)
    db.commit()
    return user, project, run


@pytest.mark.asyncio
async def test_discussion_stream_shares_context_and_persists_each_speaker(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, project, run = create_discussion_context(db)
    prompts: list[str] = []
    released: list[int] = []

    class FakeLLM:
        async def stream(self, system_prompt: str, prompt: str, model: str):
            prompts.append(prompt)
            yield f"观点 {len(prompts)}"

    class FakeLease:
        def __init__(self, agent_id: int):
            self.agent_id = agent_id

        async def release(self):
            released.append(self.agent_id)

    async def acquire(agent_id: int, concurrency_limit: int):
        return FakeLease(agent_id)

    monkeypatch.setattr(discussion_service, "SessionLocal", sessionmaker(bind=db.get_bind()))
    monkeypatch.setattr(discussion_service, "get_llm", lambda: FakeLLM())
    monkeypatch.setattr(discussion_service, "acquire_agent_slot", acquire)

    events = [
        event
        async for event in stream_discussion_events(
            user.id,
            "设计一个多 AI 协作工作室",
            project.id,
            None,
            run.id,
            None,
        )
    ]

    assert len([event for event in events if "event: speaker_start" in event]) == len(DISCUSSION_ROLES)
    assert "观点 1" in prompts[1]
    assert "event: done" in events[-1]
    db.expire_all()
    conversation = db.scalar(select(Conversation).where(Conversation.user_id == user.id))
    assert conversation is not None
    assert conversation.mode == "TEAM"
    messages = list(db.scalars(select(Message).where(Message.conversation_id == conversation.id).order_by(Message.id)))
    assert [message.role for message in messages] == ["user"] + ["assistant"] * len(DISCUSSION_ROLES)
    assert [message.stage for message in messages[1:]] == ["product", "architecture", "quality", "operations", "final"]
    assert all(message.agent_id for message in messages[1:])
    assert db.get(AgentRun, run.id).status == "COMPLETED"
    assert len(released) == len(DISCUSSION_ROLES)


@pytest.mark.asyncio
async def test_discussion_failure_refunds_once(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    user, project, run = create_discussion_context(db)
    debit = apply_token_change(
        db,
        user.id,
        -50,
        "CONSUME",
        idempotency_key="discussion-debit",
        reference_type="agent_run",
        reference_id=run.request_id,
    )
    run.billing_transaction_id = debit.id
    db.commit()

    class FailingLLM:
        async def stream(self, system_prompt: str, prompt: str, model: str):
            raise RuntimeError("provider unavailable")
            yield "unreachable"

    class FakeLease:
        async def release(self):
            pass

    async def acquire(agent_id: int, concurrency_limit: int):
        return FakeLease()

    monkeypatch.setattr(discussion_service, "SessionLocal", sessionmaker(bind=db.get_bind()))
    monkeypatch.setattr(discussion_service, "get_llm", lambda: FailingLLM())
    monkeypatch.setattr(discussion_service, "acquire_agent_slot", acquire)

    events = [
        event
        async for event in stream_discussion_events(
            user.id,
            "讨论失败场景",
            project.id,
            None,
            run.id,
            debit.id,
        )
    ]

    assert any("event: error" in event for event in events)
    db.expire_all()
    assert db.get(User, user.id).ai_token_balance == 500
    assert db.get(AgentRun, run.id).status == "FAILED"
    assert db.scalar(
        select(func.count(TokenTransaction.id)).where(TokenTransaction.transaction_type == "REFUND")
    ) == 1


def test_discussion_uses_existing_specialists_in_stable_order(db: Session) -> None:
    ensure_default_agents(db)
    agents = select_discussion_agents(db)

    assert [agent.role.value for agent in agents] == [role.value for role, _stage in DISCUSSION_ROLES]
    assert json.loads(json.dumps([agent.name for agent in agents], ensure_ascii=False))[-1] == "AI项目经理"


def request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/agents/discussion/stream",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
    )


def test_discussion_run_uses_team_cost_and_request_idempotency(db: Session) -> None:
    ensure_default_agents(db)
    user = User(
        email="discussion-billing@example.com",
        name="Discussion Billing",
        password_hash="hash",
        permissions="agents:read",
        ai_token_balance=100,
    )
    db.add(user)
    db.flush()
    coordinator = select_discussion_agents(db)[-1]
    payload = DiscussionRequest(message="讨论计费", request_id="discussion-billing-001")

    run = create_agent_run(
        db,
        request(),
        user,
        coordinator,
        None,
        payload,
        token_cost=50,
        description="多 AI 团队讨论",
    )

    assert run.billing_transaction_id is not None
    assert db.get(User, user.id).ai_token_balance == 50
    with pytest.raises(HTTPException) as duplicate:
        create_agent_run(db, request(), user, coordinator, None, payload, token_cost=50)
    assert duplicate.value.status_code == 409


@pytest.mark.asyncio
async def test_discussion_requires_agent_permission(db: Session) -> None:
    user = User(
        email="discussion-denied@example.com",
        name="Denied",
        password_hash="hash",
        role=UserRole.member,
        permissions="",
        ai_token_balance=100,
    )
    db.add(user)
    db.commit()

    with pytest.raises(HTTPException) as denied:
        await discussion_stream(
            DiscussionRequest(message="不应执行", request_id="discussion-denied-001"),
            request(),
            user,
            db,
        )
    assert denied.value.status_code == 403
