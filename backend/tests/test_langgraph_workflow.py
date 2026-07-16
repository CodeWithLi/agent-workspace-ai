import json

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.llm import get_llm
from app.langgraph.workflow import build_workspace_graph, continue_workspace_graph, run_workspace_graph
from app.models import Project, Report, Task, User, UserRole, WorkflowRun, WorkflowStatus


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

    workflow = await continue_workspace_graph(db, workflow, "同意，补充风险说明")
    assert workflow.status == WorkflowStatus.completed
    assert workflow.current_node == "completed"
    assert json.loads(workflow.state_json)["report"].startswith("# 最终报告")
    assert db.scalar(select(func.count(Task.id)).where(Task.project_id == project.id)) == 6
    assert db.scalar(select(func.count(Report.id)).where(Report.project_id == project.id)) == 1

    with pytest.raises(ValueError):
        await continue_workspace_graph(db, workflow, "重复继续")
