from datetime import datetime, timedelta, timezone
import json

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
from app.api.routes.workflow import cancel_workflow, continue_workflow, retry_workflow, run_workflow
from app.core.database import get_db
from app.core.llm import get_llm
from app.core.security import hash_password
from app.models import Agent, AgentRole, AgentRun, Project, RechargeOrder, TokenTransaction, User, UserRole, WorkflowEvent, WorkflowRun, WorkflowStatus
from app.schemas import ChatRequest, RechargeRequest, WorkflowContinueRequest, WorkflowRequest, WorkflowRetryRequest
from app.services.agent_runs import fail_agent_run
from app.services import agent_run_reaper as reaper_module
from app.services.billing import InsufficientTokensError, apply_token_change, refund_consumption
from app.services.workflows import process_workflow


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
        return (
            "# Agent output\n\n"
            "明确范围、关键决策、依赖关系、边界场景、风险缓解和后续负责人。"
            "给出可观测的验收证据、灰度发布步骤、失败信号、回滚条件与复现步骤。"
        )

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
    assert response.status == WorkflowStatus.queued
    assert db.get(User, user.id).ai_token_balance == 900
    assert db.scalar(select(func.count(TokenTransaction.id)).where(TokenTransaction.transaction_type == "CONSUME")) == 1
    assert len(prompts) == 0

    await process_workflow(db, response.workflow_id)
    db.expire_all()
    workflow = db.get(WorkflowRun, response.workflow_id)
    assert workflow.status == WorkflowStatus.paused
    state = json.loads(workflow.state_json)
    assert {item["type"] for item in state["documents"]} >= {
        "PRD",
        "SYSTEM_DESIGN",
        "PROJECT_PLAN",
        "TEST_PLAN",
    }
    assert len(prompts) == 9
    assert db.scalar(
        select(func.count(WorkflowEvent.id)).where(
            WorkflowEvent.workflow_id == response.workflow_id,
            WorkflowEvent.event_type == "NODE_COMPLETED",
        )
    ) == 8

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
    assert completed.status == WorkflowStatus.queued
    await process_workflow(db, response.workflow_id)
    db.expire_all()
    assert db.get(WorkflowRun, response.workflow_id).status == WorkflowStatus.completed
    assert len(prompts) == 10


@pytest.mark.asyncio
async def test_failed_workflow_refunds_once_and_can_be_retried(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = User(
        email="workflow-refund@example.com",
        name="Workflow Refund",
        password_hash="hash",
        permissions="projects:write",
        ai_token_balance=1000,
    )
    db.add(user)
    db.flush()
    project = Project(name="Refund Project", owner_id=user.id)
    db.add(project)
    db.flush()
    debit = apply_token_change(
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
        billing_transaction_id=debit.id,
        pause_before_report=True,
        max_attempts=1,
    )
    db.add(workflow)
    db.commit()

    queued = await continue_workflow(
        WorkflowContinueRequest(workflow_id=workflow.id, human_feedback="批准"),
        http_request("/api/v1/workflow/continue"),
        user,
        db,
    )
    assert queued.status == WorkflowStatus.queued

    async def fail_execution(*_args, **_kwargs):
        raise RuntimeError("report provider unavailable")

    monkeypatch.setattr("app.services.workflows.execute_workspace_graph", fail_execution)
    await process_workflow(db, workflow.id)

    db.expire_all()
    assert db.get(User, user.id).ai_token_balance == 1000
    assert db.scalar(
        select(func.count(TokenTransaction.id)).where(
            TokenTransaction.transaction_type == "REFUND",
            TokenTransaction.reference_id == "workflow-refund-request",
        )
    ) == 1
    source = db.get(WorkflowRun, workflow.id)
    source_finished_at = source.finished_at
    source_billing_transaction_id = source.billing_transaction_id
    source_error = source.error

    retried = retry_workflow(
        workflow.id,
        WorkflowRetryRequest(request_id="workflow-retry-request"),
        http_request(f"/api/v1/workflow/{workflow.id}/retry"),
        user,
        db,
    )
    assert retried.status == WorkflowStatus.queued
    assert retried.workflow_id != source.id
    assert retried.parent_workflow_id == source.id
    assert retried.retry_from_node == source.current_node
    assert retried.retry_sequence == 1
    assert db.get(User, user.id).ai_token_balance == 900

    db.expire_all()
    persisted_source = db.get(WorkflowRun, source.id)
    child = db.get(WorkflowRun, retried.workflow_id)
    assert persisted_source.status == WorkflowStatus.failed
    assert persisted_source.finished_at == source_finished_at
    assert persisted_source.billing_transaction_id == source_billing_transaction_id
    assert persisted_source.error == source_error
    assert child.billing_transaction_id != source_billing_transaction_id

    repeated = retry_workflow(
        source.id,
        WorkflowRetryRequest(request_id="workflow-retry-request"),
        http_request(f"/api/v1/workflow/{source.id}/retry"),
        user,
        db,
    )
    assert repeated.workflow_id == child.id
    assert db.get(User, user.id).ai_token_balance == 900
    assert db.scalar(select(func.count(WorkflowRun.id))) == 2

    source_events = list(
        db.scalars(select(WorkflowEvent).where(WorkflowEvent.workflow_id == source.id))
    )
    child_events = list(
        db.scalars(select(WorkflowEvent).where(WorkflowEvent.workflow_id == child.id))
    )
    assert [event.event_type for event in source_events].count("RETRY_CREATED") == 1
    assert [event.event_type for event in child_events] == ["RETRY_QUEUED", "QUEUED"]

    with pytest.raises(HTTPException) as active_child:
        retry_workflow(
            source.id,
            WorkflowRetryRequest(request_id="workflow-retry-request-02"),
            http_request(f"/api/v1/workflow/{source.id}/retry"),
            user,
            db,
        )
    assert active_child.value.status_code == 409
    assert db.get(User, user.id).ai_token_balance == 900

    await process_workflow(db, child.id)
    db.expire_all()
    assert db.get(WorkflowRun, source.id).status == WorkflowStatus.failed
    assert db.get(WorkflowRun, child.id).status == WorkflowStatus.failed
    assert db.get(User, user.id).ai_token_balance == 1000
    assert db.scalar(
        select(func.count(TokenTransaction.id)).where(
            TokenTransaction.transaction_type == "REFUND",
            TokenTransaction.reference_id == "workflow-refund-request",
        )
    ) == 1
    assert db.scalar(
        select(func.count(TokenTransaction.id)).where(
            TokenTransaction.transaction_type == "REFUND",
            TokenTransaction.reference_id == "workflow-retry-request",
        )
    ) == 1


def test_workflow_retry_cleans_compensated_checkpoint_and_supports_descendants(db: Session) -> None:
    user = User(
        email="workflow-lineage@example.com",
        name="Workflow Lineage",
        password_hash="hash",
        permissions="projects:write",
        ai_token_balance=1000,
    )
    db.add(user)
    db.flush()
    project = Project(name="Lineage Project", owner_id=user.id)
    db.add(project)
    db.flush()
    source_state = {
        "requirements": {"summary": "preserved"},
        "architecture": {"style": "preserved"},
        "execution_plan": {"objective": "preserved"},
        "specialist_handoffs": [{"role": "test_engineer", "content": "preserved"}],
        "quality_gate": {"passed": True},
        "agent_snapshot": {"architect": {"model": "frozen-model"}},
        "tasks": [{"title": "stale task"}],
        "tests": {"analysis": "stale test plan"},
        "report": "stale final report",
        "documents": [
            {"type": "PRD", "content": "preserved PRD"},
            {"type": "SYSTEM_DESIGN", "content": "preserved design"},
            {"type": "PROJECT_PLAN", "content": "stale project plan"},
            {"type": "TEST_PLAN", "content": "stale test plan"},
            {"type": "FINAL_REPORT", "content": "stale report"},
        ],
        "messages": [
            {"role": "architect_agent", "content": "preserved"},
            {"role": "project_manager_agent", "content": "stale"},
            {"role": "tester_agent", "content": "stale"},
            {"role": "report_generator", "content": "stale"},
        ],
    }
    source = WorkflowRun(
        project_id=project.id,
        user_id=user.id,
        status=WorkflowStatus.failed,
        current_node="project_manager",
        state_json=json.dumps(source_state),
        human_feedback="preserve this feedback",
        request_id="lineage-source-request",
        retry_sequence=2,
        error="report failed after task compensation",
    )
    db.add(source)
    db.flush()
    db.add(
        WorkflowEvent(
            workflow_id=source.id,
            node="report",
            event_type="NODE_STARTED",
            message="Started report",
            payload_json="{}",
        )
    )
    db.commit()

    response = retry_workflow(
        source.id,
        WorkflowRetryRequest(request_id="lineage-child-request"),
        http_request(f"/api/v1/workflow/{source.id}/retry"),
        user,
        db,
    )
    child = db.get(WorkflowRun, response.workflow_id)
    child_state = json.loads(child.state_json)

    assert child.parent_workflow_id == source.id
    assert child.retry_from_node == "project_manager"
    assert child.retry_sequence == 3
    assert child.human_feedback == source.human_feedback
    assert child.attempt_count == 0
    assert child_state["requirements"] == source_state["requirements"]
    assert child_state["architecture"] == source_state["architecture"]
    assert child_state["execution_plan"] == source_state["execution_plan"]
    assert child_state["specialist_handoffs"] == source_state["specialist_handoffs"]
    assert child_state["quality_gate"] == source_state["quality_gate"]
    assert child_state["agent_snapshot"] == source_state["agent_snapshot"]
    assert child_state["tasks"] == []
    assert child_state["tests"] == {}
    assert child_state["report"] == ""
    assert [item["type"] for item in child_state["documents"]] == ["PRD", "SYSTEM_DESIGN"]
    assert [item["role"] for item in child_state["messages"]] == ["architect_agent"]
    assert json.loads(db.get(WorkflowRun, source.id).state_json) == source_state

    child.status = WorkflowStatus.failed
    child.error = "child failed"
    db.commit()
    grandchild_response = retry_workflow(
        child.id,
        WorkflowRetryRequest(request_id="lineage-grandchild-request"),
        http_request(f"/api/v1/workflow/{child.id}/retry"),
        user,
        db,
    )
    grandchild = db.get(WorkflowRun, grandchild_response.workflow_id)
    assert grandchild.parent_workflow_id == child.id
    assert grandchild.retry_from_node == child.current_node
    assert grandchild.retry_sequence == 4
    assert db.get(WorkflowRun, child.id).status == WorkflowStatus.failed


@pytest.mark.asyncio
async def test_queued_workflow_cancel_refunds_idempotently(db: Session) -> None:
    user = User(
        email="cancel@example.com",
        name="Cancel",
        password_hash="hash",
        permissions="projects:write",
        ai_token_balance=500,
    )
    db.add(user)
    db.flush()
    project = Project(name="Cancel Project", owner_id=user.id)
    db.add(project)
    db.commit()

    response = await run_workflow(
        WorkflowRequest(
            project_id=project.id,
            user_input="取消这个工作流",
            request_id="workflow-cancel-request",
        ),
        http_request("/api/v1/workflow/run"),
        user,
        db,
    )
    cancelled = cancel_workflow(
        response.workflow_id,
        http_request(f"/api/v1/workflow/{response.workflow_id}/cancel"),
        user,
        db,
    )
    assert cancelled.status == WorkflowStatus.cancelled
    assert db.get(User, user.id).ai_token_balance == 500
    repeated = cancel_workflow(
        response.workflow_id,
        http_request(f"/api/v1/workflow/{response.workflow_id}/cancel"),
        user,
        db,
    )
    assert repeated.status == WorkflowStatus.cancelled
    assert db.scalar(
        select(func.count(TokenTransaction.id)).where(
            TokenTransaction.transaction_type == "REFUND",
            TokenTransaction.reference_id == "workflow-cancel-request",
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
