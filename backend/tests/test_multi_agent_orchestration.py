import json

import pytest
from pydantic import ValidationError

from app.agent.orchestration import (
    AgentHandoff,
    MultiAgentExecutionPlan,
    build_fallback_plan,
    build_execution_waves,
    build_task_blueprints,
    evaluate_handoffs,
    expand_revision_roles,
    merge_reviewer_decision,
    parse_execution_plan,
)


def test_fallback_plan_selects_context_specific_specialists() -> None:
    plan = build_fallback_plan(
        "设计带 RAG 文档检索、邮件通知和灰度发布能力的企业知识平台"
    )

    roles = [assignment.role for assignment in plan.assignments]
    assert roles == [
        "test_engineer",
        "operations_analyst",
        "knowledge_admin",
        "notification_secretary",
    ]
    assert len(plan.success_criteria) >= 3


def test_execution_plan_parser_accepts_valid_json_and_falls_back_safely() -> None:
    valid = json.dumps(
        {
            "objective": "交付可灰度发布的会员增长能力",
            "rationale": "质量与运营风险需要独立评审",
            "assignments": [
                {
                    "role": "test_engineer",
                    "objective": "定义验收门禁和边界场景",
                    "deliverable": "测试与验收清单",
                },
                {
                    "role": "operations_analyst",
                    "objective": "定义灰度、监控和回滚策略",
                    "deliverable": "发布运行手册",
                },
            ],
            "success_criteria": ["核心路径可验收", "发布过程可回滚"],
        },
        ensure_ascii=False,
    )

    parsed = parse_execution_plan(valid, "会员增长")
    fallback = parse_execution_plan('{"assignments":[{"role":"unknown"}]}', "知识库通知")

    assert parsed.objective == "交付可灰度发布的会员增长能力"
    assert [item.role for item in parsed.assignments] == ["test_engineer", "operations_analyst"]
    assert [item.depends_on for item in parsed.assignments] == [[], []]
    assert [item.role for item in fallback.assignments][:2] == ["test_engineer", "operations_analyst"]


def test_execution_plan_builds_dependency_waves_and_rejects_invalid_graphs() -> None:
    plan_data = {
        "objective": "按依赖顺序生成可验证的跨专业交付",
        "rationale": "知识证据先于测试，测试与运营结论先于通知策略",
        "assignments": [
            {
                "role": "test_engineer",
                "objective": "基于知识证据验证边界场景",
                "deliverable": "测试与验收清单",
                "depends_on": ["knowledge_admin"],
            },
            {
                "role": "operations_analyst",
                "objective": "独立验证灰度、监控和回滚策略",
                "deliverable": "发布运行手册",
            },
            {
                "role": "knowledge_admin",
                "objective": "整理可追溯知识证据和权限边界",
                "deliverable": "知识证据清单",
            },
            {
                "role": "notification_secretary",
                "objective": "基于验收与运营结论设计可靠触达",
                "deliverable": "通知触达方案",
                "depends_on": ["test_engineer", "operations_analyst"],
            },
        ],
        "success_criteria": ["全部依赖可追溯", "每个交付均通过验收"],
    }

    plan = MultiAgentExecutionPlan.model_validate(plan_data)
    waves = build_execution_waves(plan)

    assert [[assignment.role for assignment in wave] for wave in waves] == [
        ["operations_analyst", "knowledge_admin"],
        ["test_engineer"],
        ["notification_secretary"],
    ]
    assert expand_revision_roles(plan, {"knowledge_admin"}) == {
        "knowledge_admin",
        "test_engineer",
        "notification_secretary",
    }
    assert expand_revision_roles(plan, {"notification_secretary"}) == {"notification_secretary"}

    for invalid_assignments in (
        [
            *plan_data["assignments"][:3],
            {**plan_data["assignments"][3], "depends_on": ["notification_secretary"]},
        ],
        [
            {**plan_data["assignments"][0], "depends_on": ["notification_secretary"]},
            *plan_data["assignments"][1:3],
            {**plan_data["assignments"][3], "depends_on": ["test_engineer"]},
        ],
        [
            {**plan_data["assignments"][0], "depends_on": ["operations_analyst", "operations_analyst"]},
            *plan_data["assignments"][1:],
        ],
    ):
        with pytest.raises(ValidationError):
            MultiAgentExecutionPlan.model_validate({**plan_data, "assignments": invalid_assignments})

    unknown_dependency = [
        {**plan_data["assignments"][0], "depends_on": ["notification_secretary"]},
        *plan_data["assignments"][1:3],
    ]
    with pytest.raises(ValidationError):
        MultiAgentExecutionPlan.model_validate({**plan_data, "assignments": unknown_dependency})


def test_quality_gate_requires_complete_substantive_handoffs() -> None:
    plan = build_fallback_plan("设计普通项目交付流程")
    short = [
        AgentHandoff(
            role=assignment.role,
            objective=assignment.objective,
            deliverable=assignment.deliverable,
            content="过短",
            revision_round=0,
        )
        for assignment in plan.assignments
    ]
    substantive = [
        handoff.model_copy(
            update={
                "content": (
                    "给出明确范围、关键决策、边界场景、风险缓解、验收证据与后续负责人。"
                    "每项建议都关联到用户目标，并说明不可行条件和可观测结果。"
                    "同时列出依赖关系、失败信号、灰度策略、回滚条件和可复现的验收步骤。"
                )
            }
        )
        for handoff in short
    ]

    failed = evaluate_handoffs(plan, short)
    passed = evaluate_handoffs(plan, substantive)

    assert failed.passed is False
    assert set(failed.revision_roles) == {item.role for item in plan.assignments}
    assert passed.passed is True
    assert passed.score >= 80


def test_reviewer_cannot_override_deterministic_failure_and_can_request_revision() -> None:
    plan = build_fallback_plan("设计项目交付流程")
    handoffs = [
        AgentHandoff(
            role=assignment.role,
            objective=assignment.objective,
            deliverable=assignment.deliverable,
            content="过短",
            revision_round=0,
        )
        for assignment in plan.assignments
    ]
    deterministic = evaluate_handoffs(plan, handoffs)
    reviewer = json.dumps(
        {
            "passed": True,
            "score": 100,
            "issues": [],
            "revision_roles": [],
            "summary": "评审认为可以通过",
        },
        ensure_ascii=False,
    )

    merged = merge_reviewer_decision(deterministic, reviewer, plan)
    tasks = build_task_blueprints(plan)

    assert merged.passed is False
    assert merged.score < 80
    assert len(tasks) == len(plan.assignments) + 2
    assert len({task["title"] for task in tasks}) == len(tasks)
