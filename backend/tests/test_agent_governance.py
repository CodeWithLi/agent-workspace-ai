import json

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.agent.service import ensure_default_agents, regenerate_assistant_message
from app.api.routes.agents import (
    create_agent_version,
    publish_agent_version,
    rollback_agent_version,
    submit_message_feedback,
    update_agent,
)
from app.core.llm import LLMGateway
from app.core.llm_usage import bind_llm_usage, calculate_cost_micros
from app.evaluation import score_answer
from app.main import app
from app.models import Agent, AgentPromptVersion, AuditLog, Conversation, LLMUsage, Message, MessageFeedback, User, UserRole
from app.schemas import AgentUpdate, AgentVersionCreate, MessageFeedbackRequest


def admin_user(db: Session) -> User:
    user = User(email="governance@example.com", name="Governance", password_hash="hash", role=UserRole.admin)
    db.add(user)
    db.flush()
    return user


def request():
    from starlette.requests import Request

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/agents",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 1234),
        }
    )


def test_direct_agent_activation_paths_require_evaluation(db: Session) -> None:
    ensure_default_agents(db)
    admin = admin_user(db)
    agent = db.scalar(select(Agent).order_by(Agent.id))
    assert agent.current_version == 1
    assert db.scalar(select(func.count(AgentPromptVersion.id)).where(AgentPromptVersion.agent_id == agent.id)) == 1

    payload = AgentUpdate(
        description=agent.description,
        system_prompt="Published prompt v2",
        model=agent.model,
        memory_enable=agent.memory_enable,
        knowledge_access=agent.knowledge_access,
        human_approval_required=agent.human_approval_required,
        concurrency_limit=agent.concurrency_limit,
    )
    with pytest.raises(HTTPException) as update_error:
        update_agent(agent.id, payload, request(), db, admin)
    assert update_error.value.status_code == 409
    assert "evaluation" in str(update_error.value.detail).lower()
    assert db.get(Agent, agent.id).current_version == 1

    draft = create_agent_version(
        agent.id,
        AgentVersionCreate(
            description=agent.description,
            system_prompt="Draft prompt v2",
            model=agent.model,
            memory_enable=True,
            knowledge_access=True,
            human_approval_required=False,
            concurrency_limit=3,
            release_note="quality candidate",
        ),
        request(),
        admin,
        db,
    )
    assert draft.version == 2
    assert draft.status == "DRAFT"
    with pytest.raises(HTTPException) as publish_error:
        publish_agent_version(agent.id, draft.id, request(), admin, db)
    assert publish_error.value.status_code == 409
    assert "evaluation" in str(publish_error.value.detail).lower()

    with pytest.raises(HTTPException) as rollback_error:
        rollback_agent_version(agent.id, 1, request(), admin, db)
    assert rollback_error.value.status_code == 409
    assert "evaluation" in str(rollback_error.value.detail).lower()
    db.expire_all()
    assert db.get(Agent, agent.id).current_version == 1
    assert db.get(Agent, agent.id).system_prompt != "Draft prompt v2"
    assert db.get(AgentPromptVersion, draft.id).status == "DRAFT"
    assert db.scalar(select(func.count(AgentPromptVersion.id)).where(AgentPromptVersion.agent_id == agent.id)) == 2
    for action in (
        "agent.direct_update_blocked",
        "agent.direct_publish_blocked",
        "agent.direct_rollback_blocked",
    ):
        assert db.scalar(select(func.count(AuditLog.id)).where(AuditLog.action == action)) == 1


def test_direct_agent_activation_routes_are_deprecated() -> None:
    operations = app.openapi()["paths"]
    assert operations["/api/v1/agents/{agent_id}"]["patch"]["deprecated"] is True
    assert operations["/api/v1/agents/{agent_id}/versions/{version_id}/publish"]["post"]["deprecated"] is True
    assert operations["/api/v1/agents/{agent_id}/versions/{target_version}/rollback"]["post"]["deprecated"] is True


def test_message_feedback_is_upserted(db: Session) -> None:
    ensure_default_agents(db)
    user = admin_user(db)
    agent = db.scalar(select(Agent).order_by(Agent.id))
    conversation = Conversation(title="Feedback", agent_id=agent.id, user_id=user.id)
    db.add(conversation)
    db.flush()
    message = Message(conversation_id=conversation.id, role="assistant", content="answer")
    db.add(message)
    db.commit()

    first = submit_message_feedback(
        message.id,
        MessageFeedbackRequest(rating=1, comment="helpful"),
        request(),
        user,
        db,
    )
    second = submit_message_feedback(
        message.id,
        MessageFeedbackRequest(rating=-1, comment="needs citations"),
        request(),
        user,
        db,
    )
    assert first.id == second.id
    assert second.rating == -1
    assert db.scalar(select(func.count(MessageFeedback.id))) == 1


@pytest.mark.asyncio
async def test_regeneration_keeps_original_and_links_variant(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    ensure_default_agents(db)
    user = admin_user(db)
    agent = db.scalar(select(Agent).order_by(Agent.id))
    conversation = Conversation(title="Regenerate", agent_id=agent.id, user_id=user.id)
    db.add(conversation)
    db.flush()
    prompt = Message(conversation_id=conversation.id, role="user", content="Give a cited answer")
    db.add(prompt)
    db.flush()
    original = Message(
        conversation_id=conversation.id,
        role="assistant",
        content="original",
        parent_message_id=prompt.id,
    )
    db.add(original)
    db.commit()

    async def fake_chat(*_args, **_kwargs):
        return "regenerated"

    monkeypatch.setattr("app.agent.service.get_llm", lambda: type("Gateway", (), {"chat": fake_chat})())
    variant = await regenerate_assistant_message(db, user, original)
    assert variant.content == "regenerated"
    assert variant.parent_message_id == prompt.id
    assert variant.regenerated_from_id == original.id
    assert db.get(Message, original.id).content == "original"


def test_usage_cost_and_evaluation_scoring_are_deterministic() -> None:
    assert calculate_cost_micros(1000, 500, input_rate=2.0, output_rate=6.0) == 5000
    score, details = score_answer("Uses PostgreSQL with daily backup and restore drills", ["PostgreSQL", "backup", "restore"])
    assert score == 1.0
    assert json.loads(details)["matched"] == ["PostgreSQL", "backup", "restore"]


@pytest.mark.asyncio
async def test_provider_usage_is_persisted_from_response(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = admin_user(db)
    db.commit()

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{"message": {"content": "provider answer"}}],
                "usage": {"prompt_tokens": 123, "completion_tokens": 45, "total_tokens": 168},
            }

    class Client:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return Response()

    gateway = LLMGateway()
    monkeypatch.setattr(gateway.settings, "llm_api_key", "provider-key")
    monkeypatch.setattr("app.core.llm.httpx.AsyncClient", Client)
    monkeypatch.setattr("app.core.llm_usage.SessionLocal", sessionmaker(bind=db.get_bind()))
    with bind_llm_usage(user_id=user.id):
        assert await gateway.chat("system", "prompt") == "provider answer"
    usage = db.scalar(select(LLMUsage))
    assert usage.input_tokens == 123
    assert usage.output_tokens == 45
    assert usage.usage_source == "provider"
