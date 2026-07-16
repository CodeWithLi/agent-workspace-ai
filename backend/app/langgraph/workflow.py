import json
import logging
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.llm import get_llm
from app.agent.concurrency import acquire_agent_slot
from app.models import Agent, AgentRole, Project, Report, Task, WorkflowRun, WorkflowStatus
from app.tools.project_tools import architecture_generate, requirement_create, task_create, testcase_create


logger = logging.getLogger(__name__)


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


class WorkspaceGraphState(ProjectState, total=False):
    current_node: str
    pause_before_report: bool
    human_feedback: str


STATE_FIELDS = set(ProjectState.__optional_keys__)


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


def append_message(state: WorkspaceGraphState, role: str, content: str) -> list[dict[str, str]]:
    return [*state.get("messages", []), {"role": role, "content": content}]


def without_analysis(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "analysis"}


def build_workspace_graph(db: Session, workflow: WorkflowRun):
    async def invoke_agent(role: AgentRole, fallback_prompt: str, content: str) -> str:
        agent = db.scalar(select(Agent).where(Agent.role == role))
        if not agent:
            return await get_llm().chat(fallback_prompt, content)
        lease = await acquire_agent_slot(agent.id, agent.concurrency_limit)
        try:
            return await get_llm().chat(agent.system_prompt, content, agent.model)
        finally:
            await lease.release()

    async def dispatch_node(_: WorkspaceGraphState) -> dict[str, Any]:
        return {}

    async def requirement_node(state: WorkspaceGraphState) -> dict[str, Any]:
        requirements = requirement_create(state["user_input"])
        requirements["analysis"] = await invoke_agent(
            AgentRole.product_manager,
            "你是需求分析 Agent。识别目标、约束、缺失信息和验收标准。",
            state["user_input"],
        )
        return {
            "requirements": requirements,
            "messages": append_message(state, "requirement_agent", json.dumps(requirements, ensure_ascii=False)),
            "current_node": "product",
        }

    async def product_node(state: WorkspaceGraphState) -> dict[str, Any]:
        content = await invoke_agent(
            AgentRole.product_manager,
            "你是AI产品经理，生成完整PRD。",
            json.dumps(without_analysis(state["requirements"]), ensure_ascii=False),
        )
        return {
            "documents": [*state.get("documents", []), {"type": "PRD", "content": content}],
            "messages": append_message(state, "product_agent", content),
            "current_node": "architect",
        }

    async def architect_node(state: WorkspaceGraphState) -> dict[str, Any]:
        architecture = architecture_generate(state["user_input"])
        content = await invoke_agent(
            AgentRole.architect,
            "你是AI架构师，生成系统设计。",
            json.dumps(
                {"requirements": without_analysis(state["requirements"]), "architecture": architecture},
                ensure_ascii=False,
            ),
        )
        return {
            "architecture": architecture,
            "documents": [*state.get("documents", []), {"type": "SYSTEM_DESIGN", "content": content}],
            "messages": append_message(state, "architect_agent", content),
            "current_node": "project_manager",
        }

    async def project_manager_node(state: WorkspaceGraphState) -> dict[str, Any]:
        titles = ["PRD评审", "架构设计评审", "后端接口开发", "前端页面开发", "RAG联调", "测试验收"]
        tasks = [{"title": title, "priority": "HIGH" if index < 2 else "MEDIUM"} for index, title in enumerate(titles)]
        plan = await invoke_agent(
            AgentRole.project_manager,
            "你是AI项目经理。根据需求和架构生成里程碑、依赖关系、风险与资源计划。",
            json.dumps(
                {
                    "requirements": without_analysis(state["requirements"]),
                    "architecture": state["architecture"],
                    "tasks": tasks,
                },
                ensure_ascii=False,
            ),
        )
        task_create(db, workflow.project_id, titles)
        return {
            "tasks": tasks,
            "documents": [*state.get("documents", []), {"type": "PROJECT_PLAN", "content": plan}],
            "messages": append_message(state, "project_manager_agent", plan),
            "current_node": "tester",
        }

    async def tester_node(state: WorkspaceGraphState) -> dict[str, Any]:
        tests = testcase_create(state["user_input"])
        tests["analysis"] = await invoke_agent(
            AgentRole.test_engineer,
            "你是AI测试工程师。根据需求、架构和任务生成测试策略、边界场景和验收门禁。",
            json.dumps(
                {
                    "requirements": without_analysis(state["requirements"]),
                    "architecture": state["architecture"],
                    "tasks": state["tasks"],
                },
                ensure_ascii=False,
            ),
        )
        return {
            "tests": tests,
            "documents": [
                *state.get("documents", []),
                {"type": "TEST_PLAN", "content": tests["analysis"]},
            ],
            "messages": append_message(state, "tester_agent", json.dumps(tests, ensure_ascii=False)),
            "current_node": "report",
        }

    async def report_node(state: WorkspaceGraphState) -> dict[str, Any]:
        feedback = f"\n人工确认意见：{state['human_feedback']}" if state.get("human_feedback") else ""
        report = await invoke_agent(
            AgentRole.operations_analyst,
            "你是项目报告生成器。请生成最终项目报告，包含需求、架构、任务、测试、风险。",
            json.dumps(
                {
                    "project": state["project"],
                    "requirements": without_analysis(state["requirements"]),
                    "architecture": state["architecture"],
                    "tasks": state["tasks"],
                    "tests": without_analysis(state["tests"]),
                },
                ensure_ascii=False,
            )
            + feedback,
        )
        project = db.get(Project, workflow.project_id)
        if project:
            db.add(
                Report(
                    project_id=project.id,
                    user_id=workflow.user_id,
                    report_type="workflow",
                    title=f"{project.name} 工作流报告",
                    content=report,
                )
            )
        return {
            "report": report,
            "documents": [*state.get("documents", []), {"type": "FINAL_REPORT", "content": report}],
            "messages": append_message(state, "report_generator", report),
            "current_node": "completed",
        }

    def dispatch_route(state: WorkspaceGraphState) -> str:
        return state.get("current_node", "requirement")

    def after_tester(state: WorkspaceGraphState) -> Literal["pause", "report"]:
        return "pause" if state.get("pause_before_report", True) else "report"

    builder = StateGraph(WorkspaceGraphState)
    builder.add_node("dispatch", dispatch_node)
    builder.add_node("requirement", requirement_node)
    builder.add_node("product", product_node)
    builder.add_node("architect", architect_node)
    builder.add_node("project_manager", project_manager_node)
    builder.add_node("tester", tester_node)
    builder.add_node("report", report_node)
    builder.add_edge(START, "dispatch")
    builder.add_conditional_edges(
        "dispatch",
        dispatch_route,
        {
            "requirement": "requirement",
            "product": "product",
            "architect": "architect",
            "project_manager": "project_manager",
            "tester": "tester",
            "report": "report",
            "completed": END,
        },
    )
    builder.add_edge("requirement", "product")
    builder.add_edge("product", "architect")
    builder.add_edge("architect", "project_manager")
    builder.add_edge("project_manager", "tester")
    builder.add_conditional_edges("tester", after_tester, {"pause": END, "report": "report"})
    builder.add_edge("report", END)
    return builder.compile()


async def run_workspace_graph(
    db: Session,
    project: Project,
    user_id: int,
    user_input: str,
    pause_before_report: bool = True,
    request_id: str | None = None,
) -> WorkflowRun:
    workflow = WorkflowRun(
        project_id=project.id,
        user_id=user_id,
        status=WorkflowStatus.running,
        current_node="requirement",
        state_json=json.dumps(initial_state(project, user_input), ensure_ascii=False),
        request_id=request_id,
    )
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return await execute_workspace_graph(db, workflow, pause_before_report)


async def continue_workspace_graph(db: Session, workflow: WorkflowRun, human_feedback: str = "") -> WorkflowRun:
    if workflow.status != WorkflowStatus.paused or workflow.current_node != "report":
        raise ValueError("Workflow is not waiting for human confirmation")
    workflow.human_feedback = human_feedback
    workflow.status = WorkflowStatus.running
    db.commit()
    return await execute_workspace_graph(db, workflow, pause_before_report=False)


async def execute_workspace_graph(db: Session, workflow: WorkflowRun, pause_before_report: bool) -> WorkflowRun:
    persisted: ProjectState = json.loads(workflow.state_json)
    graph_state: WorkspaceGraphState = {
        **persisted,
        "current_node": workflow.current_node,
        "pause_before_report": pause_before_report,
        "human_feedback": workflow.human_feedback,
    }
    try:
        result: WorkspaceGraphState = await build_workspace_graph(db, workflow).ainvoke(graph_state)
        workflow.current_node = result.get("current_node", workflow.current_node)
        workflow.state_json = json.dumps({key: value for key, value in result.items() if key in STATE_FIELDS}, ensure_ascii=False)
        if workflow.current_node == "completed":
            workflow.status = WorkflowStatus.completed
        elif workflow.current_node == "report" and pause_before_report:
            workflow.status = WorkflowStatus.paused
        else:
            workflow.status = WorkflowStatus.failed
        db.commit()
        db.refresh(workflow)
        return workflow
    except Exception:
        db.rollback()
        workflow = db.get(WorkflowRun, workflow.id)
        if workflow:
            workflow.status = WorkflowStatus.failed
            db.commit()
        logger.exception("Workspace StateGraph execution failed for workflow %s", workflow.id if workflow else "unknown")
        raise
