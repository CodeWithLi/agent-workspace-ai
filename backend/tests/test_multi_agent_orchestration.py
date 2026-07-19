import json

import pytest
from pydantic import ValidationError

from app.agent.orchestration import (
    AgentHandoff,
    MultiAgentExecutionPlan,
    ReviewerPanelQuorumError,
    build_fallback_plan,
    build_execution_waves,
    build_task_blueprints,
    evaluate_handoffs,
    expand_revision_roles,
    merge_reviewer_decision,
    merge_reviewer_panel,
    parse_execution_plan,
    seal_handoff,
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


def test_handoff_lineage_rejects_tampered_or_stale_downstream_evidence() -> None:
    plan = MultiAgentExecutionPlan.model_validate(
        {
            "objective": "形成可验证、可追溯的发布验收方案",
            "rationale": "运营先定义发布控制，再由测试验证准入条件",
            "assignments": [
                {
                    "role": "operations_analyst",
                    "objective": "定义灰度、监控、失败信号和回滚边界",
                    "deliverable": "发布控制清单",
                    "depends_on": [],
                },
                {
                    "role": "test_engineer",
                    "objective": "基于发布控制清单验证核心路径和边界场景",
                    "deliverable": "验收证据清单",
                    "depends_on": ["operations_analyst"],
                },
            ],
            "success_criteria": ["每项准入条件可复现", "上游结论变化后下游必须重验"],
        }
    )
    operations_assignment, test_assignment = plan.assignments
    operations = seal_handoff(
        plan,
        operations_assignment,
        "发布窗口、监控阈值、失败信号和回滚条件均已绑定负责人及可复现证据。" * 3,
        plan_version=3,
        revision_round=0,
        upstream_handoffs={},
    )
    testing = seal_handoff(
        plan,
        test_assignment,
        "核心路径、边界状态、回滚演练和准入门禁均已引用发布控制清单并完成验证。" * 3,
        plan_version=3,
        revision_round=0,
        upstream_handoffs={"operations_analyst": operations},
    )

    valid = evaluate_handoffs(plan, [operations, testing], plan_version=3)
    tampered_operations = operations.model_copy(
        update={"content": f"{operations.content}未经封存的修改"}
    )
    tampered = evaluate_handoffs(
        plan,
        [tampered_operations, testing],
        plan_version=3,
    )
    revised_operations = seal_handoff(
        plan,
        operations_assignment,
        f"{operations.content} 已批准的新阈值",
        plan_version=3,
        revision_round=1,
        upstream_handoffs={},
    )
    stale = evaluate_handoffs(
        plan,
        [revised_operations, testing],
        plan_version=3,
    )

    lineage_check = next(check for check in valid.checks if check["name"] == "handoff_lineage")
    assert valid.passed is True
    assert lineage_check["passed"] is True
    assert lineage_check["detail"].startswith("2 sealed handoffs")
    assert tampered.passed is False
    assert set(tampered.revision_roles) == {"operations_analyst", "test_engineer"}
    assert stale.passed is False
    assert stale.revision_roles == ["test_engineer"]
    assert any("证据链失效" in issue for issue in stale.issues)


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


def test_blocking_collaboration_ledger_forces_targeted_revision() -> None:
    plan = build_fallback_plan("设计可灰度发布并可回滚的项目交付流程")
    handoffs = [
        AgentHandoff(
            role=assignment.role,
            objective=assignment.objective,
            deliverable=assignment.deliverable,
            content=(
                "明确范围、关键决策、依赖、边界场景、失败信号、验收证据和后续负责人。"
                "同时给出灰度发布、回滚条件、监控阈值和可复现的验证步骤。"
                "每项结论都关联成功标准、证据来源、完成时限和可审计的责任边界。"
            ),
            revision_round=0,
        )
        for assignment in plan.assignments
    ]
    deterministic = evaluate_handoffs(plan, handoffs)
    reviewer = json.dumps(
        {
            "passed": True,
            "score": 96,
            "issues": [],
            "revision_roles": [],
            "summary": "专业结论完整，但发布条件仍有阻塞冲突。",
            "decisions": [
                {
                    "title": "发布策略",
                    "outcome": "采用分阶段灰度发布。",
                    "rationale": "降低首次上线风险并保留快速回滚窗口。",
                    "source_roles": ["test_engineer", "operations_analyst"],
                    "confidence": 0.92,
                }
            ],
            "conflicts": [
                {
                    "topic": "发布准入条件",
                    "positions": [
                        {"role": "test_engineer", "position": "全量回归通过后才能发布。"},
                        {"role": "operations_analyst", "position": "核心冒烟通过即可开始灰度。"},
                    ],
                    "status": "OPEN",
                    "resolution": "",
                    "blocking": True,
                    "revision_roles": [],
                }
            ],
            "open_questions": [
                {
                    "question": "谁负责确认灰度扩容阈值？",
                    "owner_role": "operations_analyst",
                    "blocking": True,
                }
            ],
        },
        ensure_ascii=False,
    )

    merged = merge_reviewer_decision(deterministic, reviewer, plan)

    assert deterministic.passed is True
    assert merged.passed is False
    assert merged.score <= 79
    assert set(merged.revision_roles) == {"test_engineer", "operations_analyst"}
    assert merged.decisions[0].title == "发布策略"
    assert merged.conflicts[0].status == "OPEN"
    assert set(merged.conflicts[0].revision_roles) == {"test_engineer", "operations_analyst"}
    assert merged.open_questions[0].blocking is True
    assert any("阻塞冲突" in issue for issue in merged.issues)
    assert any("阻塞问题" in issue for issue in merged.issues)

    resolved_payload = json.loads(reviewer)
    resolved_payload["conflicts"][0].update(
        {
            "status": "RESOLVED",
            "resolution": "核心冒烟通过后启动灰度，全量回归通过后才能扩容。",
            "blocking": False,
        }
    )
    resolved_payload["open_questions"] = []
    resolved = merge_reviewer_decision(
        deterministic,
        json.dumps(resolved_payload, ensure_ascii=False),
        plan,
    )

    assert resolved.passed is True
    assert resolved.score == 96
    assert resolved.conflicts[0].status == "RESOLVED"
    assert resolved.conflicts[0].resolution.startswith("核心冒烟通过后")


def test_reviewer_panel_uses_structured_majority_and_preserves_dissent() -> None:
    plan = build_fallback_plan("设计可灰度发布并可回滚的项目交付流程")
    handoffs = [
        AgentHandoff(
            role=assignment.role,
            objective=assignment.objective,
            deliverable=assignment.deliverable,
            content=(
                "明确范围、关键决策、依赖、边界场景、失败信号、验收证据和后续负责人。"
                "同时给出灰度发布、回滚条件、监控阈值和可复现的验证步骤。"
                "每项结论都关联成功标准、证据来源、完成时限和可审计责任边界。"
            ),
            revision_round=0,
        )
        for assignment in plan.assignments
    ]
    deterministic = evaluate_handoffs(plan, handoffs)
    shared_decision = {
        "title": "发布策略",
        "outcome": "采用分阶段灰度发布。",
        "rationale": "降低首发风险并保留快速回滚窗口。",
        "source_roles": ["test_engineer", "operations_analyst"],
        "confidence": 0.91,
    }

    def reviewer_output(*, passed: bool, score: int, summary: str) -> str:
        return json.dumps(
            {
                "passed": passed,
                "score": score,
                "issues": [] if passed else ["架构依赖仍需收敛"],
                "revision_roles": [] if passed else ["operations_analyst"],
                "summary": summary,
                "decisions": [shared_decision],
                "conflicts": [],
                "open_questions": [],
            },
            ensure_ascii=False,
        )

    panel = merge_reviewer_panel(
        deterministic,
        {
            "test_engineer": reviewer_output(
                passed=True,
                score=94,
                summary="质量与安全证据满足门禁。",
            ),
            "operations_analyst": reviewer_output(
                passed=True,
                score=88,
                summary="发布和回滚方案可执行。",
            ),
            "architect": reviewer_output(
                passed=False,
                score=72,
                summary="少数意见：架构依赖仍可收敛。",
            ),
        },
        plan,
    )

    assert panel.passed is True
    assert panel.score == 88
    assert panel.reviewer_quorum == 2
    assert panel.reviewer_valid_count == 3
    assert panel.reviewer_pass_count == 2
    assert panel.reviewer_disagreement_count == 1
    assert [reviewer.role for reviewer in panel.reviewers] == [
        "test_engineer",
        "operations_analyst",
        "architect",
    ]
    assert [reviewer.passed for reviewer in panel.reviewers] == [True, True, False]
    assert len(panel.decisions) == 1
    assert panel.revision_roles == []
    assert "架构依赖仍需收敛" in panel.issues


def test_reviewer_panel_blocks_any_open_blocker_and_requires_quorum() -> None:
    plan = build_fallback_plan("设计可灰度发布并可回滚的项目交付流程")
    handoffs = [
        AgentHandoff(
            role=assignment.role,
            objective=assignment.objective,
            deliverable=assignment.deliverable,
            content=(
                "范围、决策、依赖、风险、边界、验收证据和负责人完整。"
                "灰度、监控、失败信号、回滚条件和复现步骤均已确认。" * 2
            ),
            revision_round=0,
        )
        for assignment in plan.assignments
    ]
    deterministic = evaluate_handoffs(plan, handoffs)
    passing = json.dumps(
        {
            "passed": True,
            "score": 93,
            "issues": [],
            "revision_roles": [],
            "summary": "同意放行。",
            "decisions": [],
            "conflicts": [],
            "open_questions": [],
        },
        ensure_ascii=False,
    )
    blocker = json.dumps(
        {
            "passed": True,
            "score": 96,
            "issues": [],
            "revision_roles": [],
            "summary": "存在尚未闭合的发布责任。",
            "decisions": [],
            "conflicts": [],
            "open_questions": [
                {
                    "question": "谁负责确认灰度扩容阈值？",
                    "owner_role": "operations_analyst",
                    "blocking": True,
                }
            ],
        },
        ensure_ascii=False,
    )

    blocked = merge_reviewer_panel(
        deterministic,
        {
            "test_engineer": passing,
            "operations_analyst": passing,
            "architect": blocker,
        },
        plan,
    )
    with pytest.raises(ReviewerPanelQuorumError):
        merge_reviewer_panel(
            deterministic,
            {
                "test_engineer": passing,
                "operations_analyst": "not-json",
                "architect": "also-not-json",
            },
            plan,
        )

    assert blocked.passed is False
    assert blocked.score == 79
    assert blocked.revision_roles == ["operations_analyst"]
    assert blocked.open_questions[0].blocking is True
    assert blocked.reviewer_pass_count == 2
