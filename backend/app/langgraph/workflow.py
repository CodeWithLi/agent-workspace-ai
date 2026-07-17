import json
import logging
from datetime import datetime, timezone
from typing import Any, Literal, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.llm import get_llm
from app.core.llm_usage import bind_llm_usage
from app.agent.concurrency import acquire_agent_slot
from app.models import Agent, AgentRole, Project, WorkflowEvent, WorkflowRun, WorkflowStatus
from app.services.workflow_saga import (
    WorkflowLeaseLost,
    execute_report_creation,
    execute_task_creation,
)
from app.tools.project_tools import architecture_generate, requirement_create, testcase_create


logger = logging.getLogger(__name__)


class WorkflowCancelled(RuntimeError):
    pass


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
    agent_snapshot: dict[str, dict[str, Any]]


class WorkspaceGraphState(ProjectState, total=False):
    current_node: str
    pause_before_report: bool
    human_feedback: str


STATE_FIELDS = set(ProjectState.__optional_keys__)


def snapshot_agent_configs(db: Session) -> dict[str, dict[str, Any]]:
    return {
        agent.role.value: {
            "agent_id": agent.id,
            "name": agent.name,
            "system_prompt": agent.system_prompt,
            "model": agent.model,
            "concurrency_limit": agent.concurrency_limit,
            "prompt_version": agent.current_version,
        }
        for agent in db.scalars(select(Agent))
    }


def initial_state(
    project: Project,
    user_input: str,
    agent_snapshot: dict[str, dict[str, Any]] | None = None,
) -> ProjectState:
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
        "agent_snapshot": agent_snapshot or {},
    }


def append_message(state: WorkspaceGraphState, role: str, content: str) -> list[dict[str, str]]:
    return [*state.get("messages", []), {"role": role, "content": content}]


def without_analysis(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "analysis"}


def document_content(state: WorkspaceGraphState, document_type: str, limit: int = 12000) -> str:
    for document in reversed(state.get("documents", [])):
        if document.get("type") == document_type and isinstance(document.get("content"), str):
            return document["content"][:limit]
    return ""


def record_workflow_event(
    db: Session,
    workflow: WorkflowRun,
    event_type: str,
    message: str,
    *,
    node: str | None = None,
    payload: dict[str, Any] | None = None,
) -> WorkflowEvent:
    event = WorkflowEvent(
        workflow_id=workflow.id,
        node=node if node is not None else workflow.current_node,
        event_type=event_type,
        message=message,
        payload_json=json.dumps(payload or {}, ensure_ascii=False),
    )
    db.add(event)
    return event


def lock_workflow_lease(
    db: Session,
    workflow: WorkflowRun,
    expected_lease_token: str | None,
) -> WorkflowRun:
    locked = db.scalar(
        select(WorkflowRun).where(WorkflowRun.id == workflow.id).with_for_update()
    )
    if not locked:
        raise LookupError("Workflow not found")
    if expected_lease_token is not None and locked.lease_token != expected_lease_token:
        raise WorkflowLeaseLost("Workflow lease ownership changed")
    return locked


def begin_node(
    db: Session,
    workflow: WorkflowRun,
    node: str,
    expected_lease_token: str | None = None,
) -> None:
    locked = lock_workflow_lease(db, workflow, expected_lease_token)
    if locked.status == WorkflowStatus.cancelling:
        raise WorkflowCancelled("Workflow cancellation requested")
    locked.current_node = node
    locked.locked_at = datetime.now(timezone.utc)
    record_workflow_event(db, locked, "NODE_STARTED", f"Started {node}", node=node)
    db.commit()


def complete_node(
    db: Session,
    workflow: WorkflowRun,
    node: str,
    state: WorkspaceGraphState,
    output: dict[str, Any],
    expected_lease_token: str | None = None,
) -> dict[str, Any]:
    locked = lock_workflow_lease(db, workflow, expected_lease_token)
    if locked.status == WorkflowStatus.cancelling:
        raise WorkflowCancelled("Workflow cancellation requested")
    persisted = {key: value for key, value in {**state, **output}.items() if key in STATE_FIELDS}
    locked.current_node = str(output.get("current_node", node))
    locked.state_json = json.dumps(persisted, ensure_ascii=False)
    locked.locked_at = datetime.now(timezone.utc)
    record_workflow_event(
        db,
        locked,
        "NODE_COMPLETED",
        f"Completed {node}",
        node=node,
        payload={"next_node": workflow.current_node},
    )
    db.commit()
    return output


def build_workspace_graph(db: Session, workflow: WorkflowRun):
    expected_lease_token = workflow.lease_token
    persisted_state = json.loads(workflow.state_json or "{}")
    agent_snapshot = persisted_state.get("agent_snapshot", {})

    async def invoke_agent(role: AgentRole, fallback_prompt: str, content: str) -> str:
        frozen = agent_snapshot.get(role.value, {})
        agent = db.get(Agent, frozen.get("agent_id")) if frozen.get("agent_id") else None
        if not agent and not frozen:
            agent = db.scalar(select(Agent).where(Agent.role == role))
        if not agent and not frozen:
            return await get_llm().chat(fallback_prompt, content)
        agent_id = agent.id if agent else None
        concurrency_limit = int(frozen.get("concurrency_limit") or agent.concurrency_limit)
        lease = await acquire_agent_slot(agent_id, concurrency_limit) if agent_id else None
        try:
            with bind_llm_usage(
                db=db,
                user_id=workflow.user_id,
                project_id=workflow.project_id,
                agent_id=agent_id,
                workflow_id=workflow.id,
            ):
                return await get_llm().chat(
                    frozen.get("system_prompt") or agent.system_prompt,
                    content,
                    frozen.get("model") or agent.model,
                )
        finally:
            if lease:
                await lease.release()

    async def dispatch_node(_: WorkspaceGraphState) -> dict[str, Any]:
        return {}

    async def requirement_node(state: WorkspaceGraphState) -> dict[str, Any]:
        begin_node(db, workflow, "requirement", expected_lease_token)
        requirements = requirement_create(state["user_input"])
        requirements["analysis"] = await invoke_agent(
            AgentRole.product_manager,
            "你是需求分析 Agent。识别目标、约束、缺失信息和验收标准。",
            state["user_input"],
        )
        return complete_node(db, workflow, "requirement", state, {
            "requirements": requirements,
            "messages": append_message(state, "requirement_agent", json.dumps(requirements, ensure_ascii=False)),
            "current_node": "product",
        }, expected_lease_token)

    async def product_node(state: WorkspaceGraphState) -> dict[str, Any]:
        begin_node(db, workflow, "product", expected_lease_token)
        content = await invoke_agent(
            AgentRole.product_manager,
            "你是AI产品经理，生成完整PRD。",
            json.dumps(without_analysis(state["requirements"]), ensure_ascii=False),
        )
        return complete_node(db, workflow, "product", state, {
            "documents": [*state.get("documents", []), {"type": "PRD", "content": content}],
            "messages": append_message(state, "product_agent", content),
            "current_node": "architect",
        }, expected_lease_token)

    async def architect_node(state: WorkspaceGraphState) -> dict[str, Any]:
        begin_node(db, workflow, "architect", expected_lease_token)
        architecture = architecture_generate(state["user_input"])
        content = await invoke_agent(
            AgentRole.architect,
            "你是AI架构师，生成系统设计。",
            json.dumps(
                {
                    "requirements": without_analysis(state["requirements"]),
                    "product_prd": document_content(state, "PRD"),
                    "architecture_baseline": architecture,
                },
                ensure_ascii=False,
            ),
        )
        return complete_node(db, workflow, "architect", state, {
            "architecture": architecture,
            "documents": [*state.get("documents", []), {"type": "SYSTEM_DESIGN", "content": content}],
            "messages": append_message(state, "architect_agent", content),
            "current_node": "project_manager",
        }, expected_lease_token)

    async def project_manager_node(state: WorkspaceGraphState) -> dict[str, Any]:
        begin_node(db, workflow, "project_manager", expected_lease_token)
        titles = ["PRD评审", "架构设计评审", "后端接口开发", "前端页面开发", "RAG联调", "测试验收"]
        tasks = [{"title": title, "priority": "HIGH" if index < 2 else "MEDIUM"} for index, title in enumerate(titles)]
        plan = await invoke_agent(
            AgentRole.project_manager,
            "你是AI项目经理。根据需求和架构生成里程碑、依赖关系、风险与资源计划。",
            json.dumps(
                {
                    "requirements": without_analysis(state["requirements"]),
                    "architecture": state["architecture"],
                    "product_prd": document_content(state, "PRD"),
                    "system_design": document_content(state, "SYSTEM_DESIGN"),
                    "tasks": tasks,
                },
                ensure_ascii=False,
            ),
        )
        execute_task_creation(
            db,
            workflow,
            titles,
            expected_lease_token=expected_lease_token,
        )
        return complete_node(db, workflow, "project_manager", state, {
            "tasks": tasks,
            "documents": [*state.get("documents", []), {"type": "PROJECT_PLAN", "content": plan}],
            "messages": append_message(state, "project_manager_agent", plan),
            "current_node": "tester",
        }, expected_lease_token)

    async def tester_node(state: WorkspaceGraphState) -> dict[str, Any]:
        begin_node(db, workflow, "tester", expected_lease_token)
        tests = testcase_create(state["user_input"])
        tests["analysis"] = await invoke_agent(
            AgentRole.test_engineer,
            "你是AI测试工程师。根据需求、架构和任务生成测试策略、边界场景和验收门禁。",
            json.dumps(
                {
                    "requirements": without_analysis(state["requirements"]),
                    "architecture": state["architecture"],
                    "tasks": state["tasks"],
                    "product_prd": document_content(state, "PRD"),
                    "system_design": document_content(state, "SYSTEM_DESIGN"),
                    "project_plan": document_content(state, "PROJECT_PLAN"),
                },
                ensure_ascii=False,
            ),
        )
        return complete_node(db, workflow, "tester", state, {
            "tests": tests,
            "documents": [
                *state.get("documents", []),
                {"type": "TEST_PLAN", "content": tests["analysis"]},
            ],
            "messages": append_message(state, "tester_agent", json.dumps(tests, ensure_ascii=False)),
            "current_node": "report",
        }, expected_lease_token)

    async def report_node(state: WorkspaceGraphState) -> dict[str, Any]:
        begin_node(db, workflow, "report", expected_lease_token)
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
                    "artifacts": {
                        document_type: document_content(state, document_type, limit=8000)
                        for document_type in ("PRD", "SYSTEM_DESIGN", "PROJECT_PLAN", "TEST_PLAN")
                    },
                },
                ensure_ascii=False,
            )
            + feedback,
        )
        project = db.get(Project, workflow.project_id)
        if project:
            execute_report_creation(
                db,
                workflow,
                title=f"{project.name} 工作流报告",
                content=report,
                expected_lease_token=expected_lease_token,
            )
        return complete_node(db, workflow, "report", state, {
            "report": report,
            "documents": [*state.get("documents", []), {"type": "FINAL_REPORT", "content": report}],
            "messages": append_message(state, "report_generator", report),
            "current_node": "completed",
        }, expected_lease_token)

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
        state_json=json.dumps(initial_state(project, user_input, snapshot_agent_configs(db)), ensure_ascii=False),
        request_id=request_id,
        pause_before_report=pause_before_report,
        attempt_count=1,
        lease_token=str(uuid4()),
        started_at=datetime.now(timezone.utc),
    )
    db.add(workflow)
    db.flush()
    record_workflow_event(db, workflow, "STARTED", "Workflow started")
    db.commit()
    db.refresh(workflow)
    return await execute_workspace_graph(db, workflow, pause_before_report)


async def continue_workspace_graph(db: Session, workflow: WorkflowRun, human_feedback: str = "") -> WorkflowRun:
    if workflow.status != WorkflowStatus.paused or workflow.current_node != "report":
        raise ValueError("Workflow is not waiting for human confirmation")
    workflow.human_feedback = human_feedback
    workflow.status = WorkflowStatus.running
    workflow.lease_token = str(uuid4())
    workflow.pause_before_report = False
    workflow.attempt_count += 1
    workflow.started_at = workflow.started_at or datetime.now(timezone.utc)
    record_workflow_event(db, workflow, "CONTINUED", "Workflow continued after human review")
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
    result: WorkspaceGraphState = await build_workspace_graph(db, workflow).ainvoke(graph_state)
    db.refresh(workflow)
    if workflow.status == WorkflowStatus.cancelling:
        raise WorkflowCancelled("Workflow cancellation requested")
    workflow.current_node = result.get("current_node", workflow.current_node)
    workflow.state_json = json.dumps({key: value for key, value in result.items() if key in STATE_FIELDS}, ensure_ascii=False)
    workflow.locked_at = None
    workflow.lease_token = None
    if workflow.current_node == "completed":
        workflow.status = WorkflowStatus.completed
        workflow.finished_at = datetime.now(timezone.utc)
        record_workflow_event(db, workflow, "COMPLETED", "Workflow completed")
    elif workflow.current_node == "report" and pause_before_report:
        workflow.status = WorkflowStatus.paused
        record_workflow_event(db, workflow, "PAUSED", "Workflow is waiting for human review")
    else:
        raise RuntimeError(f"Workflow stopped in unexpected node: {workflow.current_node}")
    db.commit()
    db.refresh(workflow)
    return workflow
