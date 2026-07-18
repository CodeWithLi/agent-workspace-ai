import asyncio
import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.llm import LLMRetryableError, get_llm
from app.agent.service import ensure_default_agents
from app.langgraph.workflow import (
    WorkflowPauseRequested,
    build_workspace_graph,
    checkpoint_node,
    complete_node,
    execute_workspace_graph,
    initial_state,
    continue_workspace_graph,
    run_workspace_graph,
    snapshot_agent_configs,
)
from app.models import Agent, AgentRole, Project, Report, Task, User, UserRole, WorkflowEvent, WorkflowRun, WorkflowStatus
from app.services.workflows import process_workflow


def test_node_completion_persists_checkpoint_before_operator_pause(db: Session) -> None:
    user = User(email="boundary-pause@example.com", name="Boundary Pause", password_hash="hash")
    db.add(user)
    db.flush()
    project = Project(name="Boundary Pause Project", owner_id=user.id)
    db.add(project)
    db.flush()
    workflow = WorkflowRun(
        project_id=project.id,
        user_id=user.id,
        status=WorkflowStatus.running,
        current_node="requirement",
        state_json="{}",
        lease_token="boundary-pause-lease",
        pause_requested_at=datetime.now(timezone.utc),
        pause_reason="等待人工检查",
    )
    db.add(workflow)
    db.commit()

    with pytest.raises(WorkflowPauseRequested):
        complete_node(
            db,
            workflow,
            "requirement",
            {"requirements": {}, "messages": [], "interventions": []},
            {
                "requirements": {"summary": "checkpoint persisted"},
                "current_node": "product",
            },
            expected_lease_token="boundary-pause-lease",
        )

    db.expire_all()
    persisted = db.get(WorkflowRun, workflow.id)
    assert persisted.current_node == "product"
    assert json.loads(persisted.state_json)["requirements"] == {"summary": "checkpoint persisted"}
    assert db.scalar(
        select(func.count(WorkflowEvent.id)).where(
            WorkflowEvent.workflow_id == workflow.id,
            WorkflowEvent.event_type == "NODE_COMPLETED",
        )
    ) == 1


def test_specialist_checkpoint_persists_before_operator_pause(db: Session) -> None:
    user = User(email="wave-pause@example.com", name="Wave Pause", password_hash="hash")
    db.add(user)
    db.flush()
    project = Project(name="Wave Pause Project", owner_id=user.id)
    db.add(project)
    db.flush()
    workflow = WorkflowRun(
        project_id=project.id,
        user_id=user.id,
        status=WorkflowStatus.running,
        current_node="specialists",
        state_json="{}",
        lease_token="wave-pause-lease",
        pause_requested_at=datetime.now(timezone.utc),
        pause_reason="检查第一波交接",
    )
    db.add(workflow)
    db.commit()
    handoff = {
        "role": "knowledge_admin",
        "objective": "整理可追溯知识证据",
        "deliverable": "知识证据清单",
        "content": "已完成第一波知识证据整理。",
        "revision_round": 0,
    }
    record = WorkflowEvent(
        workflow_id=workflow.id,
        node="specialists",
        event_type="WAVE_COMPLETED",
        message="Completed specialist execution wave 1",
        payload_json=json.dumps({"wave": 1}),
    )
    db.add(record)

    with pytest.raises(WorkflowPauseRequested):
        checkpoint_node(
            db,
            workflow,
            "specialists",
            {"specialist_handoffs": [], "messages": [], "interventions": []},
            {
                "specialist_handoffs": [handoff],
                "messages": [{"role": "specialist_knowledge_admin", "content": handoff["content"]}],
            },
            expected_lease_token="wave-pause-lease",
        )

    db.expire_all()
    persisted = db.get(WorkflowRun, workflow.id)
    persisted_state = json.loads(persisted.state_json)
    assert persisted.current_node == "specialists"
    assert persisted_state["specialist_handoffs"] == [handoff]
    assert db.scalar(
        select(func.count(WorkflowEvent.id)).where(
            WorkflowEvent.workflow_id == workflow.id,
            WorkflowEvent.event_type == "WAVE_COMPLETED",
        )
    ) == 1


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
async def test_execution_plan_requires_approval_and_supports_replanning(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(email="plan-review@example.com", name="Plan Review", password_hash="hash")
    db.add(user)
    db.flush()
    project = Project(name="Governed Plan", description="Approve before dispatch", owner_id=user.id)
    db.add(project)
    db.commit()
    planner_prompts: list[str] = []

    async def fake_chat(system_prompt: str, user_prompt: str, *_args) -> str:
        if "动态编排器" in system_prompt:
            planner_prompts.append(user_prompt)
            revision = len(planner_prompts) > 1
            return json.dumps(
                {
                    "objective": "修订后的可审计交付计划" if revision else "首版交付计划",
                    "rationale": "根据人工意见强化安全验收" if revision else "质量和运营需要独立评审",
                    "assignments": [
                        {
                            "role": "test_engineer",
                            "objective": "验证核心路径、安全边界和验收证据",
                            "deliverable": "可复现验收清单",
                        },
                        {
                            "role": "operations_analyst",
                            "objective": "验证灰度、监控和故障回滚",
                            "deliverable": "发布与回滚手册",
                        },
                    ],
                    "success_criteria": [
                        "每个核心路径都有可复现证据",
                        "每个失败场景都有负责人和回滚条件",
                    ],
                },
                ensure_ascii=False,
            )
        if "专业交接 Agent" in system_prompt:
            return (
                "明确范围、关键决策、依赖关系、边界场景与失败信号；提供监控指标、灰度策略、"
                "回滚条件、可复现验收步骤、证据来源、后续负责人和完成时限，并逐项关联成功标准。"
                "同时记录测试数据、预期结果、实际结果、告警阈值、演练时间和审批责任人，确保审计可追溯。"
            )
        if "交接质量评审 Agent" in system_prompt:
            return json.dumps(
                {
                    "passed": True,
                    "score": 96,
                    "issues": [],
                    "revision_roles": [],
                    "summary": "专业交接达到发布门禁。",
                },
                ensure_ascii=False,
            )
        if "报告生成器" in system_prompt:
            return "# 最终报告\n\n执行计划已经人工批准。"
        return "输出包含明确目标、范围、依赖、风险、验收标准和可追溯证据。" * 4

    monkeypatch.setattr(get_llm(), "chat", fake_chat)

    workflow = await run_workspace_graph(
        db,
        project,
        user.id,
        "构建需要人工计划治理的多 Agent 项目",
        pause_before_report=True,
        require_plan_approval=True,
    )
    first_state = json.loads(workflow.state_json)
    assert workflow.status == WorkflowStatus.paused
    assert workflow.current_node == "plan_review"
    assert first_state["plan_approved"] is False
    assert first_state["plan_version"] == 1
    assert len(first_state["plan_revisions"]) == 1
    assert first_state["plan_revisions"][0]["plan"]["objective"] == "首版交付计划"
    assert first_state["plan_revision_count"] == 0
    assert first_state["specialist_handoffs"] == []
    assert db.scalar(select(func.count(Task.id)).where(Task.project_id == project.id)) == 0

    with pytest.raises(ValueError, match="APPROVE or REVISE"):
        await continue_workspace_graph(db, workflow)

    workflow = await continue_workspace_graph(
        db,
        workflow,
        "补充安全边界，并为失败场景指定负责人",
        decision="REVISE",
    )
    revised_state = json.loads(workflow.state_json)
    assert workflow.status == WorkflowStatus.paused
    assert workflow.current_node == "plan_review"
    assert revised_state["execution_plan"]["objective"] == "修订后的可审计交付计划"
    assert revised_state["plan_version"] == 2
    assert len(revised_state["plan_revisions"]) == 2
    assert revised_state["plan_revisions"][0]["plan"]["objective"] == "首版交付计划"
    assert revised_state["plan_revisions"][1]["feedback"] == "补充安全边界，并为失败场景指定负责人"
    assert revised_state["plan_revision_count"] == 1
    assert revised_state["plan_approved"] is False
    assert "补充安全边界" in planner_prompts[-1]
    assert "首版交付计划" in planner_prompts[-1]
    assert db.scalar(select(func.count(Task.id)).where(Task.project_id == project.id)) == 0

    with pytest.raises(ValueError, match="version 99 was not found"):
        await continue_workspace_graph(db, workflow, decision="APPROVE", plan_version=99)

    workflow = await continue_workspace_graph(
        db,
        workflow,
        "基于首版重新规划，保留原始交付边界",
        decision="REVISE",
        plan_version=1,
    )
    historical_revision_state = json.loads(workflow.state_json)
    assert workflow.status == WorkflowStatus.paused
    assert workflow.current_node == "plan_review"
    assert historical_revision_state["plan_version"] == 3
    assert len(historical_revision_state["plan_revisions"]) == 3
    assert historical_revision_state["plan_revisions"][2]["feedback"] == "基于首版重新规划，保留原始交付边界"
    assert "基于首版重新规划" in planner_prompts[-1]
    assert "首版交付计划" in planner_prompts[-1]
    assert "修订后的可审计交付计划" not in planner_prompts[-1]

    workflow = await continue_workspace_graph(db, workflow, decision="APPROVE", plan_version=1)
    approved_state = json.loads(workflow.state_json)
    assert workflow.status == WorkflowStatus.paused
    assert workflow.current_node == "report"
    assert approved_state["plan_approved"] is True
    assert approved_state["plan_version"] == 1
    assert approved_state["execution_plan"]["objective"] == "首版交付计划"
    assert len(approved_state["plan_revisions"]) == 3
    assert len(approved_state["specialist_handoffs"]) == 2
    assert db.scalar(select(func.count(Task.id)).where(Task.project_id == project.id)) == 4
    event_types = list(
        db.scalars(
            select(WorkflowEvent.event_type)
            .where(WorkflowEvent.workflow_id == workflow.id)
            .order_by(WorkflowEvent.id)
        )
    )
    assert event_types.count("PLAN_REVISION_REQUESTED") == 2
    assert event_types.count("PLAN_APPROVED") == 1
    assert event_types.count("PLAN_CREATED") == 3
    approved_event = db.scalar(
        select(WorkflowEvent)
        .where(
            WorkflowEvent.workflow_id == workflow.id,
            WorkflowEvent.event_type == "PLAN_APPROVED",
        )
        .order_by(WorkflowEvent.id.desc())
    )
    assert json.loads(approved_event.payload_json)["plan_version"] == 1


@pytest.mark.asyncio
async def test_specialists_execute_dependency_waves_and_forward_upstream_handoffs(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(email="dependency-waves@example.com", name="Dependency Waves", password_hash="hash")
    db.add(user)
    db.flush()
    project = Project(name="Dependency Waves", description="Dependency-aware orchestration", owner_id=user.id)
    db.add(project)
    db.commit()
    active_roles: set[str] = set()
    max_parallel = 0
    specialist_contexts: dict[str, dict] = {}

    async def fake_chat(system_prompt: str, user_prompt: str, *_args) -> str:
        nonlocal max_parallel
        if "动态编排器" in system_prompt:
            return json.dumps(
                {
                    "objective": "按依赖波次完成可追溯交付",
                    "rationale": "知识证据先于测试，测试与运营结论共同约束通知策略",
                    "assignments": [
                        {
                            "role": "test_engineer",
                            "objective": "基于知识证据验证核心路径和边界场景",
                            "deliverable": "测试与验收清单",
                            "depends_on": ["knowledge_admin"],
                        },
                        {
                            "role": "operations_analyst",
                            "objective": "独立验证灰度、监控和故障恢复",
                            "deliverable": "发布运行手册",
                        },
                        {
                            "role": "knowledge_admin",
                            "objective": "整理知识来源、证据和权限边界",
                            "deliverable": "知识证据清单",
                        },
                        {
                            "role": "notification_secretary",
                            "objective": "依据验收和运营结论设计可靠触达",
                            "deliverable": "通知触达方案",
                            "depends_on": ["test_engineer", "operations_analyst"],
                        },
                    ],
                    "success_criteria": ["所有依赖均可追溯", "所有交付均有可复现证据"],
                },
                ensure_ascii=False,
            )
        if "专业交接 Agent" in system_prompt:
            context = json.loads(user_prompt)
            role = context["assignment"]["role"]
            specialist_contexts[role] = context
            active_roles.add(role)
            max_parallel = max(max_parallel, len(active_roles))
            await asyncio.sleep(0.01)
            active_roles.remove(role)
            return (
                f"{role} 已给出明确范围、关键决策、依赖关系、失败信号、监控指标、边界场景、"
                "灰度策略、回滚条件、可复现验收步骤、证据来源、后续负责人和完成时限。"
            )
        if "交接质量评审 Agent" in system_prompt:
            return json.dumps(
                {
                    "passed": True,
                    "score": 96,
                    "issues": [],
                    "revision_roles": [],
                    "summary": "依赖交接达到发布门禁。",
                },
                ensure_ascii=False,
            )
        if "报告生成器" in system_prompt:
            return "# 最终报告\n\n依赖波次执行完成。"
        return "输出包含明确目标、范围、依赖、风险、验收标准和可追溯证据。" * 4

    monkeypatch.setattr(get_llm(), "chat", fake_chat)

    workflow = await run_workspace_graph(
        db,
        project,
        user.id,
        "构建依赖感知的多 Agent 交付流程",
        pause_before_report=True,
    )
    state = json.loads(workflow.state_json)

    assert workflow.current_node == "report"
    assert max_parallel == 2
    assert specialist_contexts["knowledge_admin"]["upstream_handoffs"] == []
    assert [item["role"] for item in specialist_contexts["test_engineer"]["upstream_handoffs"]] == [
        "knowledge_admin"
    ]
    assert [item["role"] for item in specialist_contexts["notification_secretary"]["upstream_handoffs"]] == [
        "test_engineer",
        "operations_analyst",
    ]
    assert len(state["specialist_handoffs"]) == 4
    wave_events = list(
        db.scalars(
            select(WorkflowEvent)
            .where(
                WorkflowEvent.workflow_id == workflow.id,
                WorkflowEvent.event_type == "WAVE_STARTED",
            )
            .order_by(WorkflowEvent.id)
        )
    )
    assert [json.loads(event.payload_json)["roles"] for event in wave_events] == [
        ["operations_analyst", "knowledge_admin"],
        ["test_engineer"],
        ["notification_secretary"],
    ]


@pytest.mark.asyncio
async def test_specialist_wave_checkpoint_survives_retry_without_repeating_completed_agents(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(email="wave-recovery@example.com", name="Wave Recovery", password_hash="hash")
    db.add(user)
    db.flush()
    project = Project(name="Wave Recovery", description="Resume completed specialist waves", owner_id=user.id)
    db.add(project)
    db.flush()
    plan = {
        "objective": "按可恢复波次完成多 Agent 交付",
        "rationale": "独立证据先并行生成，下游只消费已提交 Handoff",
        "assignments": [
            {
                "role": "operations_analyst",
                "objective": "定义灰度、监控和回滚策略",
                "deliverable": "发布运行手册",
                "depends_on": [],
            },
            {
                "role": "knowledge_admin",
                "objective": "整理知识来源、证据和权限边界",
                "deliverable": "知识证据清单",
                "depends_on": [],
            },
            {
                "role": "test_engineer",
                "objective": "基于知识证据验证核心路径",
                "deliverable": "测试与验收清单",
                "depends_on": ["knowledge_admin"],
            },
            {
                "role": "notification_secretary",
                "objective": "依据测试与运营结论设计可靠触达",
                "deliverable": "通知触达方案",
                "depends_on": ["test_engineer", "operations_analyst"],
            },
        ],
        "success_criteria": ["已完成分支不会重复执行", "下游结论具有直接上游证据"],
    }
    state = initial_state(project, "验证可恢复的依赖波次")
    state.update(
        {
            "requirements": {"summary": "可恢复执行"},
            "architecture": {"style": "dependency-dag"},
            "execution_plan": plan,
            "plan_version": 1,
            "plan_approved": True,
        }
    )
    workflow = WorkflowRun(
        project_id=project.id,
        user_id=user.id,
        status=WorkflowStatus.queued,
        current_node="specialists",
        state_json=json.dumps(state, ensure_ascii=False),
        pause_before_report=True,
        max_attempts=2,
    )
    db.add(workflow)
    db.commit()
    specialist_calls: dict[str, int] = {}

    async def fake_chat(system_prompt: str, user_prompt: str, *_args) -> str:
        if "专业交接 Agent" in system_prompt:
            context = json.loads(user_prompt)
            role = context["assignment"]["role"]
            specialist_calls[role] = specialist_calls.get(role, 0) + 1
            if role == "test_engineer" and specialist_calls[role] == 1:
                raise RuntimeError("transient test specialist failure")
            return (
                f"{role} 已给出明确范围、关键决策、依赖关系、失败信号、监控指标、边界场景、"
                "灰度策略、回滚条件、可复现验收步骤、证据来源、后续负责人和完成时限。"
            )
        if "交接质量评审 Agent" in system_prompt:
            return json.dumps(
                {
                    "passed": True,
                    "score": 96,
                    "issues": [],
                    "revision_roles": [],
                    "summary": "恢复后的依赖交接达到门禁。",
                },
                ensure_ascii=False,
            )
        return "输出包含明确目标、范围、依赖、风险、验收标准和可追溯证据。" * 4

    monkeypatch.setattr(get_llm(), "chat", fake_chat)

    first_attempt = await process_workflow(db, workflow.id)
    first_state = json.loads(first_attempt.state_json)
    assert first_attempt.status == WorkflowStatus.queued
    assert first_attempt.current_node == "specialists"
    assert {item["role"] for item in first_state["specialist_handoffs"]} == {
        "operations_analyst",
        "knowledge_admin",
    }
    assert specialist_calls == {
        "operations_analyst": 1,
        "knowledge_admin": 1,
        "test_engineer": 1,
    }

    completed = await process_workflow(db, workflow.id)
    completed_state = json.loads(completed.state_json)
    assert completed.status == WorkflowStatus.paused
    assert completed.current_node == "report"
    assert specialist_calls == {
        "operations_analyst": 1,
        "knowledge_admin": 1,
        "test_engineer": 2,
        "notification_secretary": 1,
    }
    assert len(completed_state["specialist_handoffs"]) == 4
    event_types = list(
        db.scalars(
            select(WorkflowEvent.event_type)
            .where(WorkflowEvent.workflow_id == workflow.id)
            .order_by(WorkflowEvent.id)
        )
    )
    assert event_types.count("WAVE_RESTORED") == 1
    assert event_types.count("WAVE_CHECKPOINTED") == 1
    assert event_types.count("BRANCH_FAILED") == 1
    assert event_types.count("BRANCH_RETRY_SCHEDULED") == 0
    node_events = list(
        db.scalars(
            select(WorkflowEvent)
            .where(
                WorkflowEvent.workflow_id == workflow.id,
                WorkflowEvent.node == "specialists",
                WorkflowEvent.event_type.in_({"NODE_STARTED", "NODE_COMPLETED", "NODE_FAILED"}),
            )
            .order_by(WorkflowEvent.id)
        )
    )
    assert [event.event_type for event in node_events] == [
        "NODE_STARTED",
        "NODE_FAILED",
        "NODE_STARTED",
        "NODE_COMPLETED",
    ]
    assert [json.loads(event.payload_json)["workflow_attempt"] for event in node_events] == [1, 1, 2, 2]


@pytest.mark.asyncio
async def test_specialist_retries_only_transient_failed_branch_inside_same_workflow_attempt(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(email="branch-retry@example.com", name="Branch Retry", password_hash="hash")
    db.add(user)
    db.flush()
    project = Project(name="Branch Retry", description="Retry one transient branch", owner_id=user.id)
    db.add(project)
    db.flush()
    state = initial_state(project, "验证专业分支局部重试")
    state.update(
        {
            "requirements": {"summary": "分支级瞬时错误恢复"},
            "architecture": {"style": "dependency-dag"},
            "execution_plan": {
                "objective": "局部恢复瞬时失败的 Agent",
                "rationale": "成功分支不重复，失败分支在同一 worker 尝试内有界重试",
                "assignments": [
                    {
                        "role": "operations_analyst",
                        "objective": "定义发布和回滚策略",
                        "deliverable": "发布运行手册",
                        "depends_on": [],
                    },
                    {
                        "role": "knowledge_admin",
                        "objective": "整理证据和权限边界",
                        "deliverable": "知识证据清单",
                        "depends_on": [],
                    },
                ],
                "success_criteria": ["成功 Agent 只执行一次", "瞬时失败仅重试对应 Agent"],
            },
            "plan_version": 1,
            "plan_approved": True,
        }
    )
    workflow = WorkflowRun(
        project_id=project.id,
        user_id=user.id,
        status=WorkflowStatus.queued,
        current_node="specialists",
        state_json=json.dumps(state, ensure_ascii=False),
        pause_before_report=True,
        max_attempts=2,
    )
    db.add(workflow)
    db.commit()
    specialist_calls: dict[str, int] = {}

    async def fake_chat(system_prompt: str, user_prompt: str, *_args) -> str:
        if "专业交接 Agent" in system_prompt:
            role = json.loads(user_prompt)["assignment"]["role"]
            specialist_calls[role] = specialist_calls.get(role, 0) + 1
            if role == "knowledge_admin" and specialist_calls[role] == 1:
                raise LLMRetryableError("transient provider failure")
            return (
                f"{role} 已给出明确范围、关键决策、直接依赖、失败信号、监控指标、告警阈值、"
                "边界场景、容量假设、灰度策略、回滚条件、证据来源、权限约束、可复现验收步骤、"
                "后续负责人、完成时限和升级处理路径。"
            )
        if "交接质量评审 Agent" in system_prompt:
            return json.dumps(
                {
                    "passed": True,
                    "score": 97,
                    "issues": [],
                    "revision_roles": [],
                    "summary": "局部重试后的交接通过门禁。",
                },
                ensure_ascii=False,
            )
        return "输出包含明确目标、范围、依赖、风险、验收标准和可追溯证据。" * 4

    monkeypatch.setattr(get_llm(), "chat", fake_chat)
    monkeypatch.setattr("app.langgraph.workflow.settings.workflow_branch_max_attempts", 1)

    completed = await process_workflow(db, workflow.id)

    assert completed.status == WorkflowStatus.paused
    assert completed.current_node == "report"
    assert completed.attempt_count == 1
    assert specialist_calls == {"operations_analyst": 1, "knowledge_admin": 2}
    events = list(
        db.scalars(
            select(WorkflowEvent)
            .where(WorkflowEvent.workflow_id == workflow.id)
            .order_by(WorkflowEvent.id)
        )
    )
    event_types = [event.event_type for event in events]
    assert event_types.count("BRANCH_RETRY_SCHEDULED") == 1
    assert event_types.count("RETRY_SCHEDULED") == 0
    assert event_types.count("NODE_FAILED") == 0
    knowledge_starts = [
        json.loads(event.payload_json)
        for event in events
        if event.event_type == "BRANCH_STARTED"
        and json.loads(event.payload_json).get("role") == "knowledge_admin"
    ]
    assert [payload["branch_attempt"] for payload in knowledge_starts] == [1, 2]
    retry_event = next(event for event in events if event.event_type == "BRANCH_RETRY_SCHEDULED")
    retry_payload = json.loads(retry_event.payload_json)
    assert retry_payload["branch_attempt"] == 1
    assert retry_payload["next_branch_attempt"] == 2
    assert retry_payload["retry_delay_seconds"] == 1.0


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
                    "decisions": [
                        {
                            "title": "发布准入",
                            "outcome": "验收证据和回滚负责人同时就绪后开始灰度。",
                            "rationale": "将质量证据与运营恢复能力绑定为同一门禁。",
                            "source_roles": ["test_engineer", "operations_analyst"],
                            "confidence": 0.94,
                        }
                    ] if passed else [],
                    "conflicts": [] if passed else [
                        {
                            "topic": "验收证据负责人",
                            "positions": [
                                {"role": "test_engineer", "position": "由测试工程师维护。"},
                                {"role": "operations_analyst", "position": "由发布负责人维护。"},
                            ],
                            "status": "OPEN",
                            "resolution": "",
                            "blocking": True,
                            "revision_roles": ["test_engineer", "operations_analyst"],
                        }
                    ],
                    "open_questions": [],
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
    assert revised_state["quality_gate"]["decisions"][0]["title"] == "发布准入"
    assert revised_state["quality_gate"]["conflicts"] == []
    passed_event = db.scalar(
        select(WorkflowEvent)
        .where(
            WorkflowEvent.workflow_id == workflow.id,
            WorkflowEvent.event_type == "QUALITY_GATE_PASSED",
        )
        .order_by(WorkflowEvent.id.desc())
    )
    assert passed_event is not None
    passed_payload = json.loads(passed_event.payload_json)
    assert {
        key: passed_payload[key]
        for key in ("decision_count", "conflict_count", "open_blocker_count")
    } == {
        "decision_count": 1,
        "conflict_count": 0,
        "open_blocker_count": 0,
    }
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
    persisted_state = initial_state(project, "Build handoffs", frozen)
    persisted_state["interventions"] = [
        {
            "reason": "Security review",
            "instruction": "Keep all durable data in the approved region",
            "resume_from_node": "requirement",
        }
    ]
    workflow = WorkflowRun(
        project_id=project.id,
        user_id=user.id,
        status=WorkflowStatus.running,
        current_node="requirement",
        state_json=json.dumps(persisted_state, ensure_ascii=False),
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
    assert calls
    for _system_prompt, user_prompt in calls:
        assert json.loads(user_prompt)["operator_interventions"] == persisted_state["interventions"]
