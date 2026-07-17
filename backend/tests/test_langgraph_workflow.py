import asyncio
import json

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.llm import get_llm
from app.agent.service import ensure_default_agents
from app.langgraph.workflow import (
    build_workspace_graph,
    execute_workspace_graph,
    initial_state,
    continue_workspace_graph,
    run_workspace_graph,
    snapshot_agent_configs,
)
from app.models import Agent, AgentRole, Project, Report, Task, User, UserRole, WorkflowEvent, WorkflowRun, WorkflowStatus


@pytest.mark.asyncio
async def test_state_graph_pauses_resumes_and_keeps_tasks_idempotent(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = User(email="workflow@example.com", name="Workflow", password_hash="hash", role=UserRole.member)
    db.add(user)
    db.flush()
    project = Project(name="Graph Project", description="StateGraph verification", owner_id=user.id)
    db.add(project)
    db.commit()

    async def fake_chat(system_prompt: str, _user_prompt: str, *_args) -> str:
        if "报告生成器" in system_prompt:
            return "# 最终报告\n\n已确认。"
        return f"# {system_prompt.split('，')[0]} 输出"

    monkeypatch.setattr(get_llm(), "chat", fake_chat)
    placeholder = WorkflowRun(project_id=project.id, user_id=user.id)
    compiled = build_workspace_graph(db, placeholder)
    assert type(compiled).__name__ == "CompiledStateGraph"

    workflow = await run_workspace_graph(db, project, user.id, "构建 AI 项目平台", pause_before_report=True)
    assert workflow.status == WorkflowStatus.paused
    assert workflow.current_node == "report"
    paused_state = json.loads(workflow.state_json)
    assert len(paused_state["messages"]) >= 9
    assert "pause_before_report" not in paused_state
    assert len(paused_state["execution_plan"]["assignments"]) >= 2
    assert len(paused_state["specialist_handoffs"]) == len(paused_state["execution_plan"]["assignments"])
    assert paused_state["quality_gate"]["passed"] is True
    task_count = len(paused_state["tasks"])
    assert task_count >= 4
    assert db.scalar(select(func.count(Task.id)).where(Task.project_id == project.id)) == task_count
    assert db.scalar(select(func.count(WorkflowEvent.id)).where(WorkflowEvent.workflow_id == workflow.id)) >= 12

    workflow = await continue_workspace_graph(db, workflow, "同意，补充风险说明")
    assert workflow.status == WorkflowStatus.completed
    assert workflow.current_node == "completed"
    assert json.loads(workflow.state_json)["report"].startswith("# 最终报告")
    assert db.scalar(select(func.count(Task.id)).where(Task.project_id == project.id)) == task_count
    assert db.scalar(select(func.count(Report.id)).where(Report.project_id == project.id)) == 1

    with pytest.raises(ValueError):
        await continue_workspace_graph(db, workflow, "重复继续")


@pytest.mark.asyncio
async def test_quality_gate_bounds_automatic_revision_then_accepts_human_direction(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_default_agents(db)
    user = User(email="revision@example.com", name="Revision", password_hash="hash")
    db.add(user)
    db.flush()
    project = Project(name="Revision Project", description="Quality gate", owner_id=user.id)
    db.add(project)
    db.commit()
    review_calls = 0
    active_branches = 0
    max_parallel_branches = 0

    async def fake_chat(system_prompt: str, _user_prompt: str, *_args) -> str:
        nonlocal active_branches, max_parallel_branches, review_calls
        if "动态编排器" in system_prompt:
            return "invalid JSON uses the validated fallback plan"
        if "交接质量评审 Agent" in system_prompt:
            review_calls += 1
            passed = review_calls >= 3
            return json.dumps(
                {
                    "passed": passed,
                    "score": 95 if passed else 55,
                    "issues": [] if passed else ["缺少可复现验收证据"],
                    "revision_roles": [] if passed else ["test_engineer", "operations_analyst"],
                    "summary": "质量门禁通过" if passed else "需要补充证据后复审",
                },
                ensure_ascii=False,
            )
        if "专业交接 Agent" in system_prompt:
            active_branches += 1
            max_parallel_branches = max(max_parallel_branches, active_branches)
            try:
                await asyncio.sleep(0.01)
                return (
                    "明确范围、关键决策、依赖关系、边界场景与失败信号；提供监控指标、灰度策略、"
                    "回滚条件、可复现验收步骤、证据来源、后续负责人和完成时限。"
                    "所有结论均与用户目标和成功标准建立可追溯关系。"
                )
            finally:
                active_branches -= 1
        if "报告生成器" in system_prompt:
            return "# 最终报告\n\n质量门禁和人工修订均已完成。"
        return "输出包含明确目标、范围、依赖、风险、验收标准和可追溯证据。" * 4

    class FakeLease:
        async def release(self) -> None:
            return None

    async def fake_slot(*_args):
        return FakeLease()

    monkeypatch.setattr(get_llm(), "chat", fake_chat)
    monkeypatch.setattr("app.langgraph.workflow.acquire_agent_slot", fake_slot)

    workflow = await run_workspace_graph(
        db,
        project,
        user.id,
        "设计一个可验收的企业协作流程",
        pause_before_report=True,
    )
    failed_state = json.loads(workflow.state_json)
    assert workflow.status == WorkflowStatus.paused
    assert workflow.current_node == "quality_review"
    assert failed_state["revision_round"] == 1
    assert failed_state["quality_gate"]["passed"] is False
    assert db.scalar(select(func.count(Task.id)).where(Task.project_id == project.id)) == 0
    event_types = list(
        db.scalars(
            select(WorkflowEvent.event_type)
            .where(WorkflowEvent.workflow_id == workflow.id)
            .order_by(WorkflowEvent.id)
        )
    )
    assert event_types.count("REVISION_REQUESTED") == 1
    assert event_types.count("QUALITY_GATE_FAILED") == 1
    assert max_parallel_branches >= 2

    workflow = await continue_workspace_graph(db, workflow, "补充每个门禁的证据来源和负责人")
    revised_state = json.loads(workflow.state_json)
    assert workflow.status == WorkflowStatus.paused
    assert workflow.current_node == "report"
    assert revised_state["manual_revision_count"] == 1
    assert revised_state["quality_gate"]["passed"] is True
    assert db.scalar(select(func.count(Task.id)).where(Task.project_id == project.id)) == len(revised_state["tasks"])


@pytest.mark.asyncio
async def test_workflow_handoffs_real_artifacts_and_freezes_agent_configuration(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_default_agents(db)
    user = User(email="handoff@example.com", name="Handoff", password_hash="hash")
    db.add(user)
    db.flush()
    project = Project(name="Handoff Project", owner_id=user.id)
    db.add(project)
    db.flush()
    frozen = snapshot_agent_configs(db)
    frozen_architect_prompt = frozen[AgentRole.architect.value]["system_prompt"]
    architect = db.scalar(select(Agent).where(Agent.role == AgentRole.architect))
    architect.system_prompt = "MUTATED AFTER WORKFLOW CREATION"
    workflow = WorkflowRun(
        project_id=project.id,
        user_id=user.id,
        status=WorkflowStatus.running,
        current_node="requirement",
        state_json=json.dumps(initial_state(project, "Build handoffs", frozen), ensure_ascii=False),
        lease_token="handoff-lease",
    )
    db.add(workflow)
    db.commit()

    calls: list[tuple[str, str]] = []

    async def fake_chat(system_prompt: str, user_prompt: str, *_args) -> str:
        calls.append((system_prompt, user_prompt))
        if "产品经理" in system_prompt:
            return "PRODUCT-ARTIFACT"
        return "SPECIALIST-ARTIFACT"

    class FakeLease:
        async def release(self):
            return None

    async def fake_slot(*_args):
        return FakeLease()

    monkeypatch.setattr(get_llm(), "chat", fake_chat)
    monkeypatch.setattr("app.langgraph.workflow.acquire_agent_slot", fake_slot)

    await execute_workspace_graph(db, workflow, pause_before_report=True)

    architect_call = next(call for call in calls if call[0].startswith(frozen_architect_prompt))
    assert "PRODUCT-ARTIFACT" in architect_call[1]
    assert all(not system_prompt.startswith("MUTATED AFTER WORKFLOW CREATION") for system_prompt, _prompt in calls)
