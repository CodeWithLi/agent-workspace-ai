import json
from typing import Any, TypedDict

from sqlalchemy.orm import Session

from app.core.llm import get_llm
from app.models import Project, Report, Task, WorkflowRun, WorkflowStatus
from app.tools.project_tools import architecture_generate, requirement_create, testcase_create


class ProjectState(TypedDict, total=False):
    user_input: str
    project: dict[str, Any]
    requirements: dict[str, Any]
    architecture: dict[str, Any]
    tasks: list[dict[str, Any]]
    tests: dict[str, Any]
    documents: list[dict[str, Any]]
    messages: list[dict[str, str]]
    report: str


def _append(state: ProjectState, role: str, content: str) -> ProjectState:
    state.setdefault("messages", []).append({"role": role, "content": content})
    return state


def initial_state(project: Project, user_input: str) -> ProjectState:
    return {
        "user_input": user_input,
        "project": {"id": project.id, "name": project.name, "description": project.description},
        "requirements": {},
        "architecture": {},
        "tasks": [],
        "tests": {},
        "documents": [],
        "messages": [],
        "report": "",
    }


async def run_workspace_graph(
    db: Session,
    project: Project,
    user_id: int,
    user_input: str,
    pause_before_report: bool = True,
) -> WorkflowRun:
    workflow = WorkflowRun(
        project_id=project.id,
        user_id=user_id,
        status=WorkflowStatus.running,
        current_node="requirement",
        state_json=json.dumps(initial_state(project, user_input), ensure_ascii=False),
    )
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return await execute_until_pause_or_done(db, workflow, pause_before_report=pause_before_report)


async def continue_workspace_graph(db: Session, workflow: WorkflowRun, human_feedback: str = "") -> WorkflowRun:
    workflow.human_feedback = human_feedback
    workflow.status = WorkflowStatus.running
    db.commit()
    return await execute_until_pause_or_done(db, workflow, pause_before_report=False)


async def execute_until_pause_or_done(
    db: Session,
    workflow: WorkflowRun,
    pause_before_report: bool,
) -> WorkflowRun:
    state: ProjectState = json.loads(workflow.state_json)
    project = db.get(Project, workflow.project_id)

    if workflow.current_node == "requirement":
        state["requirements"] = requirement_create(state["user_input"])
        _append(state, "requirement_agent", json.dumps(state["requirements"], ensure_ascii=False))
        workflow.current_node = "product"

    if workflow.current_node == "product":
        content = await get_llm().chat("你是AI产品经理，生成完整PRD。", json.dumps(state["requirements"], ensure_ascii=False))
        state["documents"].append({"type": "PRD", "content": content})
        _append(state, "product_agent", content)
        workflow.current_node = "architect"

    if workflow.current_node == "architect":
        state["architecture"] = architecture_generate(state["user_input"])
        content = await get_llm().chat("你是AI架构师，生成系统设计。", json.dumps(state["architecture"], ensure_ascii=False))
        state["documents"].append({"type": "SYSTEM_DESIGN", "content": content})
        _append(state, "architect_agent", content)
        workflow.current_node = "project_manager"

    if workflow.current_node == "project_manager":
        task_titles = ["PRD评审", "架构设计评审", "后端接口开发", "前端页面开发", "RAG联调", "测试验收"]
        state["tasks"] = [{"title": title, "priority": "HIGH" if index < 2 else "MEDIUM"} for index, title in enumerate(task_titles)]
        for item in state["tasks"]:
            db.add(Task(project_id=workflow.project_id, title=item["title"], priority=item["priority"]))
        _append(state, "project_manager_agent", json.dumps(state["tasks"], ensure_ascii=False))
        workflow.current_node = "tester"

    if workflow.current_node == "tester":
        state["tests"] = testcase_create(state["user_input"])
        _append(state, "tester_agent", json.dumps(state["tests"], ensure_ascii=False))
        workflow.current_node = "report"
        if pause_before_report:
            workflow.status = WorkflowStatus.paused
            workflow.state_json = json.dumps(state, ensure_ascii=False)
            db.commit()
            db.refresh(workflow)
            return workflow

    if workflow.current_node == "report":
        feedback = f"\n人工确认意见：{workflow.human_feedback}" if workflow.human_feedback else ""
        report = await get_llm().chat(
            "你是项目报告生成器。请生成最终项目报告，包含需求、架构、任务、测试、风险。",
            json.dumps(state, ensure_ascii=False) + feedback,
        )
        state["report"] = report
        state["documents"].append({"type": "FINAL_REPORT", "content": report})
        _append(state, "report_generator", report)
        if project:
            db.add(Report(project_id=project.id, user_id=workflow.user_id, report_type="workflow", title=f"{project.name} 工作流报告", content=report))
        workflow.current_node = "completed"
        workflow.status = WorkflowStatus.completed

    workflow.state_json = json.dumps(state, ensure_ascii=False)
    db.commit()
    db.refresh(workflow)
    return workflow
