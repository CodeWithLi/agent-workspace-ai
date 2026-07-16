import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from app.agent.service import (
    ConversationAccessError,
    get_owned_conversation,
    infer_tool_calls,
    ensure_default_agents,
    stream_chat_events,
)
from app.agent import service as agent_service
from app.models import Agent, AgentRole, AgentRun, Conversation, Project, Task, User, UserRole


def create_user(db: Session, email: str = "owner@example.com") -> User:
    user = User(
        email=email,
        name="Owner",
        password_hash="hash",
        role=UserRole.member,
        permissions="agents:read,projects:write,knowledge:write",
    )
    db.add(user)
    db.flush()
    return user


@pytest.mark.asyncio
async def test_disabled_tools_never_fall_back_to_agent_declaration(db: Session) -> None:
    ensure_default_agents(db)
    user = create_user(db)
    agent = db.scalar(select(Agent).where(Agent.role == AgentRole.product_manager))
    assert agent is not None
    for tool in agent.tool_links:
        tool.enabled = False
    db.flush()

    calls = await infer_tool_calls(db, user, agent, None, "请生成 PRD 并创建需求")
    assert calls == []


@pytest.mark.asyncio
async def test_write_tool_requires_intent_and_is_idempotent(db: Session) -> None:
    ensure_default_agents(db)
    user = create_user(db)
    project = Project(name="Test", description="", owner_id=user.id)
    db.add(project)
    db.flush()
    agent = db.scalar(select(Agent).where(Agent.role == AgentRole.project_manager))
    assert agent is not None
    agent.human_approval_required = False

    read_only_calls = await infer_tool_calls(db, user, agent, project, "这个项目现在是什么情况")
    assert [call["name"] for call in read_only_calls] == ["context_search"]
    assert db.scalar(select(func.count(Task.id))) == 0

    first = await infer_tool_calls(db, user, agent, project, "请完成任务拆解并创建任务")
    second = await infer_tool_calls(db, user, agent, project, "请完成任务拆解并创建任务")
    assert [call["name"] for call in first] == ["context_search", "task_create"]
    assert [call["name"] for call in second] == ["context_search", "task_create"]
    assert second[1]["output"] == []
    assert db.scalar(select(func.count(Task.id))) == 5


def test_conversation_isolation(db: Session) -> None:
    ensure_default_agents(db)
    owner = create_user(db)
    intruder = create_user(db, "intruder@example.com")
    agent = db.scalar(select(Agent).where(Agent.role == AgentRole.architect))
    assert agent is not None
    conversation = Conversation(title="Private", agent_id=agent.id, user_id=owner.id)
    db.add(conversation)
    db.commit()

    assert get_owned_conversation(db, owner.id, conversation.id).id == conversation.id
    with pytest.raises(ConversationAccessError):
        get_owned_conversation(db, intruder.id, conversation.id)


@pytest.mark.asyncio
async def test_stream_owns_database_session(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    ensure_default_agents(db)
    user = create_user(db, "stream@example.com")
    project = Project(name="Stream", description="", owner_id=user.id)
    db.add(project)
    db.flush()
    agent = db.scalar(select(Agent).where(Agent.role == AgentRole.test_engineer))
    assert agent is not None
    db.commit()

    class FakeLLM:
        async def stream(self, system_prompt: str, prompt: str, model: str):
            yield "streamed answer"

    monkeypatch.setattr(agent_service, "SessionLocal", sessionmaker(bind=db.get_bind()))
    monkeypatch.setattr(agent_service, "get_llm", lambda: FakeLLM())

    run = AgentRun(request_id="stream-request", user_id=user.id, project_id=project.id, agent_id=agent.id)
    db.add(run)
    db.commit()

    class FakeLease:
        released = False

        async def release(self):
            self.released = True

    lease = FakeLease()

    events = [
        event
        async for event in stream_chat_events(
            user.id,
            agent.id,
            "生成测试方案",
            project.id,
            None,
            "explicit",
            run.id,
            None,
            lease,
        )
    ]
    assert any("event: token" in event and "streamed answer" in event for event in events)
    assert any("event: done" in event for event in events)
    db.expire_all()
    assert db.scalar(select(func.count(Conversation.id))) == 1
    assert db.get(AgentRun, run.id).status == "COMPLETED"
    assert lease.released is True
