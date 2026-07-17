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
    assert len(paused_state["messages"]) == 5
    assert "pause_before_report" not in paused_state
    assert db.scalar(select(func.count(Task.id)).where(Task.project_id == project.id)) == 6
    assert db.scalar(select(func.count(WorkflowEvent.id)).where(WorkflowEvent.workflow_id == workflow.id)) >= 12

    workflow = await continue_workspace_graph(db, workflow, "同意，补充风险说明")
    assert workflow.status == WorkflowStatus.completed
    assert workflow.current_node == "completed"
    assert json.loads(workflow.state_json)["report"].startswith("# 最终报告")
    assert db.scalar(select(func.count(Task.id)).where(Task.project_id == project.id)) == 6
    assert db.scalar(select(func.count(Report.id)).where(Report.project_id == project.id)) == 1

    with pytest.raises(ValueError):
        await continue_workspace_graph(db, workflow, "重复继续")


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

    architect_call = next(call for call in calls if call[0] == frozen_architect_prompt)
    assert "PRODUCT-ARTIFACT" in architect_call[1]
    assert all(system_prompt != "MUTATED AFTER WORKFLOW CREATION" for system_prompt, _prompt in calls)
