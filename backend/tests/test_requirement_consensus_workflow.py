import json

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.llm import get_llm
from app.langgraph.workflow import run_workspace_graph
from app.models import Project, Task, User, WorkflowEvent, WorkflowStatus


def structured_handoff_response(
    role: str,
    evidence_context: dict | None = None,
) -> str:
    payload = {
            "summary": (
                "The specialist completed a verifiable handoff with explicit scope, "
                "ownership, evidence, risk controls, and recovery criteria."
            ),
            "decisions": [
                {
                    "title": "Stage delivery",
                    "outcome": "Validate the core path before expanding the delivery scope.",
                    "rationale": "A staged release limits risk and preserves a deterministic rollback point.",
                }
            ],
            "evidence": [
                {
                    "claim": "The core path has reproducible acceptance evidence.",
                    "source": "Automated acceptance records and the approved success criteria.",
                    "verification": "Rerun the core cases and verify every linked success criterion.",
                }
            ],
            "risks": [
                {
                    "risk": "Scope expansion could exceed the current error budget.",
                    "mitigation": "Stop expansion and roll back when the alert threshold is reached.",
                    "owner_role": role,
                }
            ],
            "open_questions": [],
            "next_actions": [
                {
                    "action": "Run the core-path acceptance suite and archive its evidence.",
                    "owner_role": role,
                    "acceptance_criteria": "All core cases pass and the evidence is independently reviewable.",
                }
            ],
        }
    if evidence_context:
        payload["evidence"][0]["criterion_ids"] = [
            item["criterion_id"] for item in evidence_context["criteria"]
        ]
        payload["evidence"][0]["source_refs"] = [
            item["ref"] for item in evidence_context["sources"]
        ]
    return json.dumps(payload, ensure_ascii=False)


def structured_reviewer_response(user_prompt: str, payload: dict) -> str:
    context = json.loads(user_prompt)
    payload["criterion_verdicts"] = [
        {
            "criterion_id": criterion["criterion_id"],
            "verdict": (
                "PASS"
                if payload["passed"] and criterion.get("evidence_refs")
                else "FAIL"
                if criterion.get("evidence_refs")
                else "ABSTAIN"
            ),
            "confidence": min(1, max(0, payload["score"] / 100)),
            "rationale": "该验收标准已按 Reviewer 独立关注域完成逐项复核。",
            "revision_roles": (
                criterion["owner_roles"]
                if not payload["passed"] and criterion.get("evidence_refs")
                else []
            ),
            "evidence_refs": [
                reference["ref"] for reference in criterion.get("evidence_refs", [])
            ],
        }
        for criterion in context.get("review_criteria", [])
    ]
    return json.dumps(payload, ensure_ascii=False)


def execution_plan() -> dict:
    return {
        "objective": "形成可验证、可恢复的会员平台交付计划",
        "rationale": "测试与运营分别验证验收证据和发布恢复边界。",
        "assignments": [
            {
                "role": "test_engineer",
                "objective": "验证会员核心路径、边界状态和验收证据",
                "deliverable": "可复现测试与验收清单",
                "criterion_ids": ["AC-01"],
            },
            {
                "role": "operations_analyst",
                "objective": "验证监控、灰度发布和故障恢复边界",
                "deliverable": "发布与回滚运行手册",
                "criterion_ids": ["AC-02"],
            },
        ],
        "success_criteria": [
            "会员核心路径都有可复现验收证据和明确负责人",
            "失败场景都有告警阈值、回滚条件和恢复时限",
        ],
    }


def requirement_contract(*, revised: bool) -> dict:
    return {
        "objective": "交付可灰度发布并可回滚的会员平台",
        "target_users": ["会员运营", "平台管理员"],
        "in_scope": ["会员注册与登录", "灰度发布与故障回滚"],
        "out_of_scope": ["线下会员卡发行"],
        "constraints": (
            ["生产数据保留三十天", "发布失败由值班负责人在十分钟内回滚"]
            if revised
            else ["发布过程不得中断现有会员登录"]
        ),
        "assumptions": ["已有可用的生产监控"],
        "acceptance_criteria": [
            {
                "description": "会员可以完成注册、登录和会话恢复",
                "evidence": "端到端自动化用例与成功运行记录",
                "priority": "MUST",
            },
            {
                "description": (
                    "发布失败后由值班负责人在十分钟内完成回滚并保留三十天证据"
                    if revised
                    else "发布失败后能够在十分钟内完成回滚"
                ),
                "evidence": "灰度演练记录、告警时间线与恢复指标",
                "priority": "MUST",
            },
        ],
    }


def accepted_review(summary: str) -> str:
    return json.dumps(
        {
            "decision": "ACCEPT",
            "confidence": 0.94,
            "summary": summary,
            "concerns": [],
            "proposed_changes": [],
        },
        ensure_ascii=False,
    )


def accepted_commitment() -> str:
    return json.dumps(
        {
            "decision": "ACCEPT",
            "confidence": 0.93,
            "summary": "输入、依赖、能力和交付边界完整，可以执行。",
            "missing_inputs": [],
            "dependency_concerns": [],
            "proposed_changes": [],
        },
        ensure_ascii=False,
    )


def arbiter_decision() -> str:
    return json.dumps(
        {
            "selected_candidate_id": "risk_control",
            "selection_reason": "风险方案完整覆盖恢复责任和验收证据。",
            "dissenting_candidate_ids": ["delivery_confidence", "parallel_efficiency"],
            "dissent_summary": "保留交付与并行效率视角。",
        },
        ensure_ascii=False,
    )


@pytest.mark.asyncio
async def test_requirement_challenges_are_revised_re_reviewed_and_forwarded(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(email="requirement-consensus@example.com", name="Requirement Consensus", password_hash="hash")
    db.add(user)
    db.flush()
    project = Project(name="Requirement Consensus", owner_id=user.id)
    db.add(project)
    db.commit()
    review_contexts: list[tuple[str, dict]] = []
    revision_contexts: list[dict] = []
    planner_contexts: list[dict] = []

    async def fake_chat(system_prompt: str, user_prompt: str, *_args) -> str:
        if "结构化需求合同 Agent" in system_prompt:
            return json.dumps(requirement_contract(revised=False), ensure_ascii=False)
        if "需求共识修订 Agent" in system_prompt:
            context = json.loads(user_prompt)
            revision_contexts.append(context)
            return json.dumps(requirement_contract(revised=True), ensure_ascii=False)
        if "需求合同可行性评审 Agent" in system_prompt:
            context = json.loads(user_prompt)
            review_contexts.append(("architect", context))
            if "生产数据保留三十天" not in context["contract"]["constraints"]:
                return json.dumps(
                    {
                        "decision": "CHALLENGE",
                        "confidence": 0.91,
                        "summary": "缺少生产数据保留和回滚责任边界。",
                        "concerns": ["未定义生产数据保留周期"],
                        "proposed_changes": ["补充数据保留周期与回滚责任人"],
                    },
                    ensure_ascii=False,
                )
            return accepted_review("数据保留、恢复责任和系统边界完整可行。")
        if "需求合同可验收性评审 Agent" in system_prompt:
            context = json.loads(user_prompt)
            review_contexts.append(("test_engineer", context))
            return accepted_review("每项标准都包含行为、证据和可量化恢复阈值。")
        if "动态编排器" in system_prompt:
            planner_contexts.append(json.loads(user_prompt))
            return json.dumps(execution_plan(), ensure_ascii=False)
        if "执行前承诺 Agent" in system_prompt:
            return accepted_commitment()
        if "独立执行计划仲裁 Agent" in system_prompt:
            return arbiter_decision()
        if "专业交接 Agent" in system_prompt:
            context = json.loads(user_prompt)
            role = context["assignment"]["role"]
            return structured_handoff_response(role, context.get("evidence_context"))
        if "交接质量评审 Agent" in system_prompt:
            return structured_reviewer_response(
                user_prompt,
                {
                    "passed": True,
                    "score": 96,
                    "issues": [],
                    "revision_roles": [],
                    "summary": "专业交接达到发布门禁。",
                },
            )
        if "报告生成器" in system_prompt:
            return "# 最终报告\n\n需求共识与执行证据均已闭环。"
        return "输出包含明确目标、范围、依赖、风险、验收标准和可追溯证据。" * 4

    monkeypatch.setattr(get_llm(), "chat", fake_chat)

    workflow = await run_workspace_graph(
        db,
        project,
        user.id,
        "构建可灰度发布并可回滚的会员平台",
        pause_before_report=False,
        require_plan_approval=False,
    )
    state = json.loads(workflow.state_json)
    consensus = state["requirements"]["consensus"]

    assert workflow.status == WorkflowStatus.completed
    assert consensus["status"] == "READY"
    assert consensus["origin"] == "negotiated_revision"
    assert consensus["revision_attempted"] is True
    assert consensus["revision_valid"] is True
    assert consensus["reviewer_accept_count"] == 2
    assert consensus["reviewer_challenge_count"] == 0
    assert consensus["revision_challenges"][0]["role"] == "architect"
    assert len(revision_contexts) == 1
    assert revision_contexts[0]["review_challenges"][0]["concerns"] == [
        "未定义生产数据保留周期"
    ]
    assert len(review_contexts) == 4
    assert {role for role, _context in review_contexts[:2]} == {"architect", "test_engineer"}
    assert all(
        context["requirements"]["contract"]["constraints"][0] == "生产数据保留三十天"
        for context in planner_contexts
    )
    event = db.scalar(
        select(WorkflowEvent)
        .where(
            WorkflowEvent.workflow_id == workflow.id,
            WorkflowEvent.event_type == "REQUIREMENTS_CONSENSUS_REACHED",
        )
        .order_by(WorkflowEvent.id.desc())
    )
    assert json.loads(event.payload_json) == {
        "acceptance_criteria_count": 2,
        "requirement_consensus_status": "READY",
        "requirement_contract_origin": "negotiated_revision",
        "requirement_review_count": 2,
        "requirement_review_valid_count": 2,
        "requirement_review_accept_count": 2,
        "requirement_review_challenge_count": 0,
        "requirement_review_abstain_count": 0,
        "requirement_revision_attempted": True,
        "requirement_revision_valid": True,
    }
    assert db.scalar(select(func.count(Task.id)).where(Task.project_id == project.id)) >= 4


@pytest.mark.asyncio
async def test_unchanged_requirement_revision_forces_plan_review_once(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(email="requirement-gate@example.com", name="Requirement Gate", password_hash="hash")
    db.add(user)
    db.flush()
    project = Project(name="Requirement Gate", owner_id=user.id)
    db.add(project)
    db.commit()
    revision_contexts: list[dict] = []
    planner_contexts: list[dict] = []

    async def fake_chat(system_prompt: str, user_prompt: str, *_args) -> str:
        if "结构化需求合同 Agent" in system_prompt:
            return json.dumps(requirement_contract(revised=False), ensure_ascii=False)
        if "需求共识修订 Agent" in system_prompt:
            context = json.loads(user_prompt)
            revision_contexts.append(context)
            return json.dumps(context["source_contract"], ensure_ascii=False)
        if "需求合同可行性评审 Agent" in system_prompt:
            return json.dumps(
                {
                    "decision": "CHALLENGE",
                    "confidence": 0.91,
                    "summary": "缺少生产数据保留和回滚责任边界。",
                    "concerns": ["未定义生产数据保留周期"],
                    "proposed_changes": ["补充数据保留周期与回滚责任人"],
                },
                ensure_ascii=False,
            )
        if "需求合同可验收性评审 Agent" in system_prompt:
            return accepted_review("验收标准具备可验证证据。")
        if "动态编排器" in system_prompt:
            planner_contexts.append(json.loads(user_prompt))
            return json.dumps(execution_plan(), ensure_ascii=False)
        if "执行前承诺 Agent" in system_prompt:
            return accepted_commitment()
        if "独立执行计划仲裁 Agent" in system_prompt:
            return arbiter_decision()
        return "输出包含明确目标、范围、依赖、风险、验收标准和可追溯证据。" * 4

    monkeypatch.setattr(get_llm(), "chat", fake_chat)

    workflow = await run_workspace_graph(
        db,
        project,
        user.id,
        "构建可灰度发布并可回滚的会员平台",
        pause_before_report=False,
        require_plan_approval=False,
    )
    state = json.loads(workflow.state_json)
    consensus = state["requirements"]["consensus"]

    assert workflow.status == WorkflowStatus.paused
    assert workflow.current_node == "plan_review"
    assert state["require_plan_approval"] is True
    assert state["plan_approved"] is False
    assert consensus["status"] == "CHALLENGED"
    assert consensus["origin"] == "model_draft"
    assert consensus["revision_attempted"] is True
    assert consensus["revision_valid"] is False
    assert len(revision_contexts) == 1
    assert all(
        context["requirements"]["consensus"]["reviews"][0]["concerns"]
        == ["未定义生产数据保留周期"]
        for context in planner_contexts
    )
    assert state["specialist_handoffs"] == []
    assert db.scalar(select(func.count(Task.id)).where(Task.project_id == project.id)) == 0
