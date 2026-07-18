import asyncio
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
from app.agent.orchestration import (
    AgentHandoff,
    MultiAgentExecutionPlan,
    build_execution_waves,
    build_task_blueprints,
    evaluate_handoffs,
    expand_revision_roles,
    merge_reviewer_decision,
    parse_execution_plan,
)
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


class WorkflowPauseRequested(RuntimeError):
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
    execution_plan: dict[str, Any]
    plan_version: int
    plan_revisions: list[dict[str, Any]]
    require_plan_approval: bool
    plan_approved: bool
    plan_revision_count: int
    plan_revision_feedback: str
    specialist_handoffs: list[dict[str, Any]]
    quality_gate: dict[str, Any]
    revision_round: int
    revision_feedback: str
    manual_revision_count: int
    interventions: list[dict[str, Any]]


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
    require_plan_approval: bool = False,
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
        "execution_plan": {},
        "plan_version": 0,
        "plan_revisions": [],
        "require_plan_approval": require_plan_approval,
        "plan_approved": not require_plan_approval,
        "plan_revision_count": 0,
        "plan_revision_feedback": "",
        "specialist_handoffs": [],
        "quality_gate": {},
        "revision_round": 0,
        "revision_feedback": "",
        "manual_revision_count": 0,
        "interventions": [],
    }


def append_message(state: WorkspaceGraphState, role: str, content: str) -> list[dict[str, str]]:
    return [*state.get("messages", []), {"role": role, "content": content}]


def select_execution_plan_version(
    state: dict[str, Any],
    requested_version: int | None = None,
) -> tuple[dict[str, Any], int]:
    if requested_version is not None and requested_version < 1:
        raise ValueError("Execution plan version must be at least 1")
    revisions = state.get("plan_revisions")
    revisions = revisions if isinstance(revisions, list) else []
    stored_versions = [
        int(item["version"])
        for item in revisions
        if isinstance(item, dict) and isinstance(item.get("version"), int)
    ]
    current_version = int(state.get("plan_version") or (max(stored_versions, default=0) or 1))
    selected_version = requested_version or current_version
    candidate = state.get("execution_plan") if selected_version == current_version else None
    if candidate is None:
        candidate = next(
            (
                item.get("plan")
                for item in revisions
                if isinstance(item, dict) and item.get("version") == selected_version
            ),
            None,
        )
    if not isinstance(candidate, dict):
        raise ValueError(f"Execution plan version {selected_version} was not found")
    plan = MultiAgentExecutionPlan.model_validate(candidate)
    return plan.model_dump(mode="json"), selected_version


def without_analysis(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "analysis"}


def agent_context(state: WorkspaceGraphState, payload: dict[str, Any]) -> dict[str, Any]:
    interventions = state.get("interventions", [])
    if not isinstance(interventions, list):
        interventions = []
    safe_interventions = [item for item in interventions if isinstance(item, dict)][-10:]
    return {**payload, "operator_interventions": safe_interventions}


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
    if locked.pause_requested_at is not None:
        raise WorkflowPauseRequested("Workflow pause requested")
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
    if locked.pause_requested_at is not None and locked.current_node != "completed":
        raise WorkflowPauseRequested("Workflow paused after committing a node checkpoint")
    return output


def build_workspace_graph(db: Session, workflow: WorkflowRun):
    expected_lease_token = workflow.lease_token
    persisted_state = json.loads(workflow.state_json or "{}")
    agent_snapshot = persisted_state.get("agent_snapshot", {})

    async def invoke_agent(
        role: AgentRole,
        fallback_prompt: str,
        content: str,
        *,
        isolated_usage: bool = False,
    ) -> str:
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
            usage_context = dict(
                user_id=workflow.user_id,
                project_id=workflow.project_id,
                agent_id=agent_id,
                workflow_id=workflow.id,
            )
            if not isolated_usage:
                usage_context["db"] = db
            with bind_llm_usage(**usage_context):
                agent_prompt = frozen.get("system_prompt") or agent.system_prompt
                return await get_llm().chat(
                    f"{agent_prompt}\n\n{fallback_prompt}",
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
            json.dumps(
                agent_context(state, {"user_input": state["user_input"]}),
                ensure_ascii=False,
            ),
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
            json.dumps(
                agent_context(state, {"requirements": without_analysis(state["requirements"])}),
                ensure_ascii=False,
            ),
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
                agent_context(state, {
                    "requirements": without_analysis(state["requirements"]),
                    "product_prd": document_content(state, "PRD"),
                    "architecture_baseline": architecture,
                }),
                ensure_ascii=False,
            ),
        )
        return complete_node(db, workflow, "architect", state, {
            "architecture": architecture,
            "documents": [*state.get("documents", []), {"type": "SYSTEM_DESIGN", "content": content}],
            "messages": append_message(state, "architect_agent", content),
            "current_node": "planning",
        }, expected_lease_token)

    async def planning_node(state: WorkspaceGraphState) -> dict[str, Any]:
        begin_node(db, workflow, "planning", expected_lease_token)
        revision_feedback = state.get("plan_revision_feedback", "").strip()
        planner_output = await invoke_agent(
            AgentRole.project_manager,
            (
                "你是多 Agent 动态编排器。根据项目目标选择 2 到 4 个专业分支，只输出 JSON。"
                "字段必须为 objective、rationale、assignments、success_criteria；每个 assignment 包含 "
                "role、objective、deliverable、depends_on。depends_on 是同一计划内前置角色数组，无依赖时为空数组。"
                "role 仅允许 test_engineer、operations_analyst、"
                "knowledge_admin、notification_secretary。"
                "依赖必须无环；同一波的无依赖角色并行执行，后续角色消费直接上游 Handoff。"
                "存在人工重新规划意见时，必须逐项回应并实质修订原计划。"
            ),
            json.dumps(
                agent_context(state, {
                    "user_input": state["user_input"],
                    "requirements": without_analysis(state["requirements"]),
                    "architecture": state["architecture"],
                    "product_prd": document_content(state, "PRD"),
                    "system_design": document_content(state, "SYSTEM_DESIGN"),
                    "prior_execution_plan": state.get("execution_plan") or None,
                    "plan_revision": {
                        "round": int(state.get("plan_revision_count", 0)),
                        "human_feedback": revision_feedback,
                    } if revision_feedback else None,
                }),
                ensure_ascii=False,
            ),
        )
        plan = parse_execution_plan(planner_output, state["user_input"])
        approval_required = bool(state.get("require_plan_approval", False))
        revisions = state.get("plan_revisions")
        revisions = revisions if isinstance(revisions, list) else []
        plan_version = max(
            (
                int(item.get("version", 0))
                for item in revisions
                if isinstance(item, dict)
            ),
            default=0,
        ) + 1
        plan_snapshot = plan.model_dump(mode="json")
        execution_waves = build_execution_waves(plan)
        plan_revisions = [
            *revisions,
            {
                "version": plan_version,
                "plan": plan_snapshot,
                "feedback": revision_feedback,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        ]
        record_workflow_event(
            db,
            workflow,
            "PLAN_CREATED",
            "Dynamic multi-agent execution plan created",
            node="planning",
            payload={
                "roles": [assignment.role for assignment in plan.assignments],
                "success_criteria_count": len(plan.success_criteria),
                "revision_count": int(state.get("plan_revision_count", 0)),
                "approval_required": approval_required,
                "plan_version": plan_version,
                "wave_count": len(execution_waves),
                "dependency_count": sum(len(assignment.depends_on) for assignment in plan.assignments),
            },
        )
        return complete_node(db, workflow, "planning", state, {
            "execution_plan": plan_snapshot,
            "plan_version": plan_version,
            "plan_revisions": plan_revisions,
            "messages": append_message(
                state,
                "planning_agent",
                plan.model_dump_json(),
            ),
            "plan_approved": not approval_required,
            "current_node": "plan_review" if approval_required else "specialists",
        }, expected_lease_token)

    async def specialists_node(state: WorkspaceGraphState) -> dict[str, Any]:
        if state.get("require_plan_approval") and not state.get("plan_approved"):
            raise RuntimeError("Execution plan must be approved before specialist branches start")
        begin_node(db, workflow, "specialists", expected_lease_token)
        plan = MultiAgentExecutionPlan.model_validate(state["execution_plan"])
        execution_waves = build_execution_waves(plan)
        previous_handoffs = {
            handoff.role: handoff
            for handoff in (
                AgentHandoff.model_validate(item)
                for item in state.get("specialist_handoffs", [])
            )
        }
        quality_gate = state.get("quality_gate", {})
        requested_roles = set(quality_gate.get("revision_roles") or [])
        execution_roles = (
            expand_revision_roles(plan, requested_roles)
            if requested_roles
            else {assignment.role for assignment in plan.assignments}
        )
        revision_round = int(state.get("revision_round", 0))
        revision_feedback = state.get("revision_feedback", "")
        working_handoffs = dict(previous_handoffs)
        completed_waves: list[tuple[int, list[AgentHandoff]]] = []

        async def run_assignment(assignment) -> AgentHandoff:
            previous = previous_handoffs.get(assignment.role)
            missing_dependencies = [role for role in assignment.depends_on if role not in working_handoffs]
            if missing_dependencies:
                raise RuntimeError(
                    f"Missing upstream handoffs for {assignment.role}: {', '.join(missing_dependencies)}"
                )
            upstream_handoffs = [
                {
                    "role": working_handoffs[role].role,
                    "deliverable": working_handoffs[role].deliverable,
                    "content": working_handoffs[role].content[:12000],
                    "revision_round": working_handoffs[role].revision_round,
                }
                for role in assignment.depends_on
            ]
            content = await invoke_agent(
                AgentRole(assignment.role),
                (
                    "你是专业交接 Agent。围绕分配目标输出可供其他 Agent 直接使用的专业 Handoff。"
                    "必须包含范围判断、关键决策、风险、边界场景、验收证据和下一步负责人。"
                ),
                json.dumps(
                    agent_context(state, {
                        "workflow_objective": plan.objective,
                        "assignment": assignment.model_dump(mode="json"),
                        "success_criteria": plan.success_criteria,
                        "requirements": without_analysis(state["requirements"]),
                        "architecture": state["architecture"],
                        "upstream_handoffs": upstream_handoffs,
                        "revision_feedback": revision_feedback,
                        "previous_handoff": previous.content if previous else "",
                    }),
                    ensure_ascii=False,
                ),
                isolated_usage=True,
            )
            return AgentHandoff(
                role=assignment.role,
                objective=assignment.objective,
                deliverable=assignment.deliverable,
                content=content,
                revision_round=revision_round,
            )

        for wave_number, wave in enumerate(execution_waves, start=1):
            assignments = [assignment for assignment in wave if assignment.role in execution_roles]
            if not assignments:
                continue
            roles = [assignment.role for assignment in assignments]
            record_workflow_event(
                db,
                workflow,
                "WAVE_STARTED",
                f"Started specialist execution wave {wave_number}",
                node="specialists",
                payload={
                    "wave": wave_number,
                    "roles": roles,
                    "branch_count": len(assignments),
                    "dependency_count": sum(len(assignment.depends_on) for assignment in assignments),
                    "revision_round": revision_round,
                },
            )
            for assignment in assignments:
                record_workflow_event(
                    db,
                    workflow,
                    "BRANCH_STARTED",
                    f"Started specialist branch {assignment.role}",
                    node="specialists",
                    payload={
                        "role": assignment.role,
                        "deliverable": assignment.deliverable,
                        "depends_on": assignment.depends_on,
                        "dependency_count": len(assignment.depends_on),
                        "wave": wave_number,
                        "revision_round": revision_round,
                    },
                )
            db.commit()
            wave_handoffs = await asyncio.gather(*(run_assignment(assignment) for assignment in assignments))
            completed_waves.append((wave_number, wave_handoffs))
            working_handoffs.update({handoff.role: handoff for handoff in wave_handoffs})

        merged_handoffs = [
            working_handoffs[assignment.role]
            for assignment in plan.assignments
        ]
        messages = list(state.get("messages", []))
        assignments_by_role = {assignment.role: assignment for assignment in plan.assignments}
        for wave_number, wave_handoffs in completed_waves:
            for handoff in wave_handoffs:
                assignment = assignments_by_role[handoff.role]
                messages.append({"role": f"specialist_{handoff.role}", "content": handoff.content})
                record_workflow_event(
                    db,
                    workflow,
                    "BRANCH_COMPLETED",
                    f"Completed specialist branch {handoff.role}",
                    node="specialists",
                    payload={
                        "role": handoff.role,
                        "deliverable": handoff.deliverable,
                        "depends_on": assignment.depends_on,
                        "dependency_count": len(assignment.depends_on),
                        "wave": wave_number,
                        "revision_round": handoff.revision_round,
                        "output_chars": len(handoff.content),
                    },
                )
            record_workflow_event(
                db,
                workflow,
                "WAVE_COMPLETED",
                f"Completed specialist execution wave {wave_number}",
                node="specialists",
                payload={
                    "wave": wave_number,
                    "roles": [handoff.role for handoff in wave_handoffs],
                    "branch_count": len(wave_handoffs),
                    "revision_round": revision_round,
                },
            )
        return complete_node(db, workflow, "specialists", state, {
            "specialist_handoffs": [handoff.model_dump(mode="json") for handoff in merged_handoffs],
            "messages": messages,
            "revision_feedback": "",
            "current_node": "quality_gate",
        }, expected_lease_token)

    async def quality_gate_node(state: WorkspaceGraphState) -> dict[str, Any]:
        begin_node(db, workflow, "quality_gate", expected_lease_token)
        plan = MultiAgentExecutionPlan.model_validate(state["execution_plan"])
        handoffs = [AgentHandoff.model_validate(item) for item in state.get("specialist_handoffs", [])]
        deterministic = evaluate_handoffs(plan, handoffs)
        reviewer_output = await invoke_agent(
            AgentRole.test_engineer,
            (
                "你是交接质量评审 Agent。只输出 JSON，字段为 passed、score、issues、"
                "revision_roles、summary。检查可追溯性、冲突、边界场景、验收证据和发布风险。"
            ),
            json.dumps(
                agent_context(state, {
                    "execution_plan": plan.model_dump(mode="json"),
                    "handoffs": [handoff.model_dump(mode="json") for handoff in handoffs],
                    "deterministic_gate": deterministic.model_dump(mode="json"),
                }),
                ensure_ascii=False,
            ),
        )
        decision = merge_reviewer_decision(deterministic, reviewer_output, plan)
        revision_round = int(state.get("revision_round", 0))
        if decision.passed:
            next_node = "project_manager"
            event_type = "QUALITY_GATE_PASSED"
            event_message = "Specialist handoffs passed the quality gate"
        elif revision_round < 1:
            next_node = "specialists"
            event_type = "REVISION_REQUESTED"
            event_message = "Quality gate requested a bounded automatic revision"
            revision_round += 1
        else:
            next_node = "quality_review"
            event_type = "QUALITY_GATE_FAILED"
            event_message = "Quality gate requires human revision direction"
        record_workflow_event(
            db,
            workflow,
            event_type,
            event_message,
            node="quality_gate",
            payload={
                "score": decision.score,
                "issues": decision.issues,
                "revision_roles": decision.revision_roles,
                "revision_round": revision_round,
                "next_node": next_node,
            },
        )
        feedback = "\n".join([decision.summary, *decision.issues])
        return complete_node(db, workflow, "quality_gate", state, {
            "quality_gate": decision.model_dump(mode="json"),
            "revision_round": revision_round,
            "revision_feedback": feedback,
            "messages": append_message(state, "quality_gate_agent", reviewer_output),
            "current_node": next_node,
        }, expected_lease_token)

    async def project_manager_node(state: WorkspaceGraphState) -> dict[str, Any]:
        begin_node(db, workflow, "project_manager", expected_lease_token)
        execution_plan = MultiAgentExecutionPlan.model_validate(state["execution_plan"])
        tasks = build_task_blueprints(execution_plan)
        titles = [task["title"] for task in tasks]
        plan = await invoke_agent(
            AgentRole.project_manager,
            "你是AI项目经理。根据需求和架构生成里程碑、依赖关系、风险与资源计划。",
            json.dumps(
                agent_context(state, {
                    "requirements": without_analysis(state["requirements"]),
                    "architecture": state["architecture"],
                    "product_prd": document_content(state, "PRD"),
                    "system_design": document_content(state, "SYSTEM_DESIGN"),
                    "tasks": tasks,
                    "execution_plan": state["execution_plan"],
                    "specialist_handoffs": state.get("specialist_handoffs", []),
                    "quality_gate": state.get("quality_gate", {}),
                }),
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
                agent_context(state, {
                    "requirements": without_analysis(state["requirements"]),
                    "architecture": state["architecture"],
                    "tasks": state["tasks"],
                    "product_prd": document_content(state, "PRD"),
                    "system_design": document_content(state, "SYSTEM_DESIGN"),
                    "project_plan": document_content(state, "PROJECT_PLAN"),
                    "execution_plan": state.get("execution_plan", {}),
                    "specialist_handoffs": state.get("specialist_handoffs", []),
                    "quality_gate": state.get("quality_gate", {}),
                }),
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
                agent_context(state, {
                    "project": state["project"],
                    "requirements": without_analysis(state["requirements"]),
                    "architecture": state["architecture"],
                    "tasks": state["tasks"],
                    "tests": without_analysis(state["tests"]),
                    "execution_plan": state.get("execution_plan", {}),
                    "specialist_handoffs": state.get("specialist_handoffs", []),
                    "quality_gate": state.get("quality_gate", {}),
                    "artifacts": {
                        document_type: document_content(state, document_type, limit=8000)
                        for document_type in ("PRD", "SYSTEM_DESIGN", "PROJECT_PLAN", "TEST_PLAN")
                    },
                }),
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

    def after_planning(state: WorkspaceGraphState) -> Literal["continue", "pause"]:
        return "continue" if state.get("current_node") == "specialists" else "pause"

    def after_quality_gate(state: WorkspaceGraphState) -> Literal["revise", "continue", "pause"]:
        current_node = state.get("current_node")
        if current_node == "specialists":
            return "revise"
        if current_node == "project_manager":
            return "continue"
        return "pause"

    builder = StateGraph(WorkspaceGraphState)
    builder.add_node("dispatch", dispatch_node)
    builder.add_node("requirement", requirement_node)
    builder.add_node("product", product_node)
    builder.add_node("architect", architect_node)
    builder.add_node("planning", planning_node)
    builder.add_node("specialists", specialists_node)
    builder.add_node("quality_gate", quality_gate_node)
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
            "planning": "planning",
            "plan_review": END,
            "specialists": "specialists",
            "quality_gate": "quality_gate",
            "project_manager": "project_manager",
            "tester": "tester",
            "report": "report",
            "completed": END,
        },
    )
    builder.add_edge("requirement", "product")
    builder.add_edge("product", "architect")
    builder.add_edge("architect", "planning")
    builder.add_conditional_edges(
        "planning",
        after_planning,
        {"continue": "specialists", "pause": END},
    )
    builder.add_edge("specialists", "quality_gate")
    builder.add_conditional_edges(
        "quality_gate",
        after_quality_gate,
        {"revise": "specialists", "continue": "project_manager", "pause": END},
    )
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
    require_plan_approval: bool = False,
    request_id: str | None = None,
) -> WorkflowRun:
    workflow = WorkflowRun(
        project_id=project.id,
        user_id=user_id,
        status=WorkflowStatus.running,
        current_node="requirement",
        state_json=json.dumps(
            initial_state(
                project,
                user_input,
                snapshot_agent_configs(db),
                require_plan_approval=require_plan_approval,
            ),
            ensure_ascii=False,
        ),
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


async def continue_workspace_graph(
    db: Session,
    workflow: WorkflowRun,
    human_feedback: str = "",
    decision: Literal["APPROVE", "REVISE"] | None = None,
    plan_version: int | None = None,
) -> WorkflowRun:
    if workflow.status != WorkflowStatus.paused or workflow.current_node not in {
        "plan_review",
        "quality_review",
        "report",
    }:
        raise ValueError("Workflow is not waiting for human confirmation")
    gate = workflow.current_node
    persisted = json.loads(workflow.state_json or "{}")
    pause_before_report = workflow.pause_before_report
    reviewed_plan_version: int | None = None
    if gate == "plan_review":
        selected_plan, selected_version = select_execution_plan_version(persisted, plan_version)
        reviewed_plan_version = selected_version
        persisted["execution_plan"] = selected_plan
        persisted["plan_version"] = selected_version
        if decision == "APPROVE":
            persisted["plan_approved"] = True
            workflow.current_node = "specialists"
            record_workflow_event(
                db,
                workflow,
                "PLAN_APPROVED",
                "Execution plan approved for specialist dispatch",
                node="plan_review",
                payload={
                    "branch_count": len(persisted.get("execution_plan", {}).get("assignments", [])),
                    "revision_count": int(persisted.get("plan_revision_count", 0)),
                    "plan_version": selected_version,
                },
            )
        elif decision == "REVISE":
            feedback = human_feedback.strip()
            if not feedback:
                raise ValueError("Revision instruction is required for plan review")
            persisted["plan_approved"] = False
            persisted["plan_revision_feedback"] = feedback
            persisted["plan_revision_count"] = int(persisted.get("plan_revision_count", 0)) + 1
            workflow.current_node = "planning"
            record_workflow_event(
                db,
                workflow,
                "PLAN_REVISION_REQUESTED",
                "Execution plan revision requested",
                node="plan_review",
                payload={
                    "instruction_chars": len(feedback),
                    "revision_count": persisted["plan_revision_count"],
                    "source_plan_version": selected_version,
                },
            )
        else:
            raise ValueError("Plan review decision must be APPROVE or REVISE")
        workflow.state_json = json.dumps(persisted, ensure_ascii=False)
    elif gate == "quality_review":
        persisted["revision_feedback"] = human_feedback.strip() or "请根据质量门禁问题补充证据并修订专业交接。"
        persisted["manual_revision_count"] = int(persisted.get("manual_revision_count", 0)) + 1
        workflow.state_json = json.dumps(persisted, ensure_ascii=False)
        workflow.current_node = "specialists"
        pause_before_report = True
    else:
        pause_before_report = False
    if gate != "plan_review":
        workflow.human_feedback = human_feedback
    workflow.status = WorkflowStatus.running
    workflow.lease_token = str(uuid4())
    workflow.pause_before_report = pause_before_report
    workflow.attempt_count += 1
    workflow.started_at = workflow.started_at or datetime.now(timezone.utc)
    record_workflow_event(
        db,
        workflow,
        "CONTINUED",
        "Workflow continued after human review",
        payload={"approval_gate": gate, "plan_version": reviewed_plan_version},
    )
    db.commit()
    return await execute_workspace_graph(db, workflow, pause_before_report=pause_before_report)


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
        if workflow.pause_requested_at is not None:
            record_workflow_event(
                db,
                workflow,
                "PAUSE_SKIPPED",
                "Workflow reached completion before the pause could be applied",
                payload={"reason_chars": len(workflow.pause_reason)},
            )
            workflow.pause_requested_at = None
            workflow.pause_requested_by_user_id = None
            workflow.pause_reason = ""
        workflow.status = WorkflowStatus.completed
        workflow.finished_at = datetime.now(timezone.utc)
        record_workflow_event(db, workflow, "COMPLETED", "Workflow completed")
    elif workflow.current_node == "plan_review":
        workflow.status = WorkflowStatus.paused
        plan = result.get("execution_plan", {})
        record_workflow_event(
            db,
            workflow,
            "PAUSED",
            "Workflow is waiting for execution plan approval",
            payload={
                "approval_gate": "plan_review",
                "branch_count": len(plan.get("assignments", [])),
                "revision_count": int(result.get("plan_revision_count", 0)),
            },
        )
    elif workflow.current_node == "quality_review":
        workflow.status = WorkflowStatus.paused
        record_workflow_event(
            db,
            workflow,
            "PAUSED",
            "Workflow is waiting for quality revision direction",
            payload={"approval_gate": "quality_review"},
        )
    elif workflow.current_node == "report" and pause_before_report:
        workflow.status = WorkflowStatus.paused
        record_workflow_event(
            db,
            workflow,
            "PAUSED",
            "Workflow is waiting for final report approval",
            payload={"approval_gate": "report"},
        )
    else:
        raise RuntimeError(f"Workflow stopped in unexpected node: {workflow.current_node}")
    db.commit()
    db.refresh(workflow)
    return workflow
