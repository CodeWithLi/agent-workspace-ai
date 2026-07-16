from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request

from app import admin as admin_module
from app.agent import concurrency
from app.agent.service import ensure_default_agents
from app.api.routes.agents import create_agent_run
from app.api.routes.billing import fake_recharge
from app.api.routes.workflow import continue_workflow, run_workflow
from app.core.database import get_db
from app.core.llm import get_llm
from app.core.security import hash_password
from app.models import Agent, AgentRole, AgentRun, Project, RechargeOrder, TokenTransaction, User, UserRole, WorkflowRun, WorkflowStatus
from app.schemas import ChatRequest, RechargeRequest, WorkflowContinueRequest, WorkflowRequest
from app.services.agent_runs import fail_agent_run
from app.services import agent_run_reaper as reaper_module
from app.services.billing import InsufficientTokensError, apply_token_change, refund_consumption


def http_request(path: str = "/") -> Request:
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


def test_token_debit_is_idempotent_and_refundable(db: Session) -> None:
    user = User(email="billing@example.com", name="Billing", password_hash="hash", ai_token_balance=100)
    db.add(user)
    db.commit()

    debit = apply_token_change(
        db,
        user.id,
        -70,
        "CONSUME",
        idempotency_key="agent:billing:one",
        reference_type="agent_run",
        reference_id="one",
    )
    db.commit()
    assert db.get(User, user.id).ai_token_balance == 30

    repeated = apply_token_change(
        db,
        user.id,
        -70,
        "CONSUME",
        idempotency_key="agent:billing:one",
        reference_type="agent_run",
        reference_id="one",
    )
    db.commit()
    assert repeated.id == debit.id
    assert db.get(User, user.id).ai_token_balance == 30

    with pytest.raises(InsufficientTokensError):
        apply_token_change(db, user.id, -31, "CONSUME", idempotency_key="agent:billing:two")
    assert db.get(User, user.id).ai_token_balance == 30

    refund = refund_consumption(db, debit.id, "failed")
    db.commit()
    assert refund.amount == 70
    assert db.get(User, user.id).ai_token_balance == 100
    assert db.scalar(select(func.count(TokenTransaction.id))) == 2


def test_fake_recharge_and_agent_run_charge_are_idempotent(db: Session) -> None:
    ensure_default_agents(db)
    user = User(
        email="recharge@example.com",
        name="Recharge",
        password_hash="hash",
        role=UserRole.member,
        permissions="agents:read,projects:write",
        ai_token_balance=100,
    )
    db.add(user)
    db.flush()
    project = Project(name="Billing Project", owner_id=user.id)
    db.add(project)
    db.commit()

    order = fake_recharge(
        RechargeRequest(amount_yuan=10, request_id="recharge-request-001"),
        http_request("/api/v1/billing/recharge"),
        user,
        db,
    )
    repeated_order = fake_recharge(
        RechargeRequest(amount_yuan=10, request_id="recharge-request-001"),
        http_request("/api/v1/billing/recharge"),
        user,
        db,
    )
    assert repeated_order.id == order.id
    assert db.get(User, user.id).ai_token_balance == 1100
    assert db.scalar(select(func.count(RechargeOrder.id))) == 1

    agent = db.scalar(select(Agent).where(Agent.role == AgentRole.project_manager))
    payload = ChatRequest(
        agent_id=agent.id,
        project_id=project.id,
        message="分析项目",
        request_id="agent-request-001",
    )
    run = create_agent_run(db, http_request("/api/v1/agents/chat"), user, agent, project, payload)
    assert db.get(User, user.id).ai_token_balance == 1090
    with pytest.raises(HTTPException) as duplicate:
        create_agent_run(db, http_request("/api/v1/agents/chat"), user, agent, project, payload)
    assert duplicate.value.status_code == 409

    fail_agent_run(db, run.id, run.billing_transaction_id, "model failed")
    fail_agent_run(db, run.id, run.billing_transaction_id, "duplicate failure callback")
    assert db.get(User, user.id).ai_token_balance == 1100
    assert db.get(AgentRun, run.id).status == "FAILED"


def test_stale_agent_run_is_failed_and_refunded(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    ensure_default_agents(db)
    user = User(email="stale@example.com", name="Stale", password_hash="hash", ai_token_balance=100)
    db.add(user)
    db.flush()
    agent = db.scalar(select(Agent).where(Agent.role == AgentRole.architect))
    debit = apply_token_change(
        db,
        user.id,
        -10,
        "CONSUME",
        idempotency_key="stale-debit",
        reference_type="agent_run",
        reference_id="stale-run",
    )
    run = AgentRun(
        request_id="stale-run",
        user_id=user.id,
        agent_id=agent.id,
        billing_transaction_id=debit.id,
        status="RUNNING",
        started_at=datetime.now(timezone.utc) - timedelta(minutes=30),
    )
    db.add(run)
    db.commit()
    monkeypatch.setattr(reaper_module, "SessionLocal", sessionmaker(bind=db.get_bind()))

    assert reaper_module.AgentRunReaper().recover_once() == 1
    db.expire_all()
    assert db.get(AgentRun, run.id).status == "FAILED"
    assert db.get(User, user.id).ai_token_balance == 100
    assert reaper_module.AgentRunReaper().recover_once() == 0


@pytest.mark.asyncio
async def test_local_agent_concurrency_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_redis(*_args):
        return None

    monkeypatch.setattr(concurrency, "_acquire_redis", no_redis)
    monkeypatch.setattr(concurrency.settings, "agent_concurrency_acquire_timeout", 0.02)
    lease = await concurrency.acquire_agent_slot(987654, 1)
    with pytest.raises(concurrency.AgentBusyError):
        await concurrency.acquire_agent_slot(987654, 1)
    await lease.release()
    second = await concurrency.acquire_agent_slot(987654, 1)
    await second.release()


@pytest.mark.asyncio
async def test_local_agent_concurrency_limit_applies_live_decrease(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_redis(*_args):
        return None

    monkeypatch.setattr(concurrency, "_acquire_redis", no_redis)
    monkeypatch.setattr(concurrency.settings, "agent_concurrency_acquire_timeout", 0.02)
    first = await concurrency.acquire_agent_slot(987655, 2)
    second = await concurrency.acquire_agent_slot(987655, 2)

    await first.release()
    with pytest.raises(concurrency.AgentBusyError):
        await concurrency.acquire_agent_slot(987655, 1)

    await second.release()
    after_decrease = await concurrency.acquire_agent_slot(987655, 1)
    await after_decrease.release()


@pytest.mark.asyncio
async def test_redis_agent_lease_can_be_renewed_and_released() -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.eval_args = None
            self.removed = None
            self.closed = False

        async def eval(self, *args):
            self.eval_args = args
            return 1

        async def zrem(self, key, token):
            self.removed = (key, token)

        async def aclose(self):
            self.closed = True

    client = FakeRedis()
    lease = concurrency.AgentLease(agent_id=42, token="lease-token", redis_client=client)

    assert await lease.renew() is True
    assert client.eval_args[2] == "agent:slots:42"
    assert client.eval_args[-1] == "lease-token"
    await lease.release()
    assert client.removed == ("agent:slots:42", "lease-token")
    assert client.closed is True


@pytest.mark.asyncio
async def test_multi_agent_workflow_charges_once_and_blocks_parallel_run(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    ensure_default_agents(db)
    user = User(
        email="multi-agent@example.com",
        name="Multi Agent",
        password_hash="hash",
        role=UserRole.member,
        permissions="agents:read,projects:write",
        ai_token_balance=1000,
    )
    db.add(user)
    db.flush()
    project = Project(name="Concurrent Graph", description="Verify all agents", owner_id=user.id)
    db.add(project)
    db.commit()

    prompts: list[str] = []

    async def fake_chat(system_prompt: str, _user_prompt: str, *_args) -> str:
        prompts.append(system_prompt)
        return "# Agent output"

    class FakeLease:
        async def release(self):
            return None

    async def fake_slot(*_args):
        return FakeLease()

    monkeypatch.setattr(get_llm(), "chat", fake_chat)
    monkeypatch.setattr("app.langgraph.workflow.acquire_agent_slot", fake_slot)

    payload = WorkflowRequest(
        project_id=project.id,
        user_input="构建企业协作平台",
        pause_before_report=True,
        request_id="workflow-request-001",
    )
    response = await run_workflow(payload, http_request("/api/v1/workflow/run"), user, db)
    assert response.status == WorkflowStatus.paused
    assert db.get(User, user.id).ai_token_balance == 900
    assert db.scalar(select(func.count(TokenTransaction.id)).where(TokenTransaction.transaction_type == "CONSUME")) == 1
    assert {item["type"] for item in response.state["documents"]} >= {
        "PRD",
        "SYSTEM_DESIGN",
        "PROJECT_PLAN",
        "TEST_PLAN",
    }
    assert len(prompts) == 5

    repeated = await run_workflow(payload, http_request("/api/v1/workflow/run"), user, db)
    assert repeated.workflow_id == response.workflow_id
    assert db.get(User, user.id).ai_token_balance == 900

    with pytest.raises(HTTPException) as active_error:
        await run_workflow(
            payload.model_copy(update={"request_id": "workflow-request-002"}),
            http_request("/api/v1/workflow/run"),
            user,
            db,
        )
    assert active_error.value.status_code == 409
    assert db.get(User, user.id).ai_token_balance == 900

    completed = await continue_workflow(
        WorkflowContinueRequest(workflow_id=response.workflow_id, human_feedback="批准"),
        http_request("/api/v1/workflow/continue"),
        user,
        db,
    )
    assert completed.status == WorkflowStatus.completed
    assert len(prompts) == 6


@pytest.mark.asyncio
async def test_failed_workflow_continuation_refunds_original_charge(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = User(
        email="workflow-refund@example.com",
        name="Workflow Refund",
        password_hash="hash",
        ai_token_balance=1000,
    )
    db.add(user)
    db.flush()
    project = Project(name="Refund Project", owner_id=user.id)
    db.add(project)
    db.flush()
    apply_token_change(
        db,
        user.id,
        -100,
        "CONSUME",
        idempotency_key="workflow-refund-debit",
        reference_type="workflow",
        reference_id="workflow-refund-request",
    )
    workflow = WorkflowRun(
        project_id=project.id,
        user_id=user.id,
        status=WorkflowStatus.paused,
        current_node="report",
        state_json="{}",
        request_id="workflow-refund-request",
    )
    db.add(workflow)
    db.commit()

    async def fail_continuation(*_args, **_kwargs):
        raise RuntimeError("report provider unavailable")

    monkeypatch.setattr("app.api.routes.workflow.continue_workspace_graph", fail_continuation)
    with pytest.raises(RuntimeError, match="report provider unavailable"):
        await continue_workflow(
            WorkflowContinueRequest(workflow_id=workflow.id, human_feedback="批准"),
            http_request("/api/v1/workflow/continue"),
            user,
            db,
        )

    db.expire_all()
    assert db.get(User, user.id).ai_token_balance == 1000
    assert db.scalar(
        select(func.count(TokenTransaction.id)).where(
            TokenTransaction.transaction_type == "REFUND",
            TokenTransaction.reference_id == "workflow-refund-request",
        )
    ) == 1


def test_python_admin_login_csrf_and_token_adjustment(db: Session) -> None:
    admin = User(
        email="python-admin@example.com",
        name="Python Admin",
        password_hash=hash_password("StrongPass123"),
        role=UserRole.admin,
        ai_token_balance=1000,
    )
    member = User(email="member-wallet@example.com", name="Member", password_hash="hash", ai_token_balance=100)
    db.add_all([admin, member])
    db.commit()

    app = FastAPI()
    app.include_router(admin_module.router)

    def override_db():
        with Session(db.get_bind()) as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        login = client.post(
            "/admin/login",
            data={"email": admin.email, "password": "StrongPass123"},
            follow_redirects=False,
        )
        assert login.status_code == 303
        assert admin_module.settings.admin_cookie_name in client.cookies
        csrf = client.cookies.get("agent_workspace_admin_csrf")
        assert csrf

        page = client.get("/admin")
        assert page.status_code == 200
        assert "Agent 运行策略" in page.text
        assert member.email in page.text

        rejected = client.post(
            f"/admin/users/{member.id}/tokens",
            data={"amount": 50, "reason": "test", "csrf_token": "wrong"},
            follow_redirects=False,
        )
        assert "error=" in rejected.headers["location"]

        adjusted = client.post(
            f"/admin/users/{member.id}/tokens",
            data={"amount": 50, "reason": "运营赠送", "csrf_token": csrf},
            follow_redirects=False,
        )
        assert adjusted.status_code == 303

    db.expire_all()
    assert db.get(User, member.id).ai_token_balance == 150
