import json

from app.agent.requirements import (
    build_fallback_requirement_contract,
    build_requirement_consensus,
    parse_requirement_contract,
    parse_requirement_review,
)


def requirement_contract_json() -> str:
    return json.dumps(
        {
            "objective": "交付可灰度发布并可回滚的会员增长平台",
            "target_users": ["会员运营", "平台管理员"],
            "in_scope": ["会员注册与登录", "灰度发布与故障回滚"],
            "out_of_scope": ["线下会员卡发行"],
            "constraints": ["发布过程不得中断现有会员登录"],
            "assumptions": ["已有可用的短信服务与生产监控"],
            "acceptance_criteria": [
                {
                    "description": "会员可以完成注册、登录和会话恢复",
                    "evidence": "端到端自动化用例与成功运行记录",
                    "priority": "MUST",
                },
                {
                    "description": "发布失败后能够在十分钟内完成回滚",
                    "evidence": "灰度演练记录、告警时间线与恢复指标",
                    "priority": "MUST",
                },
            ],
        },
        ensure_ascii=False,
    )


def test_requirement_contract_is_strictly_parsed_and_fallback_remains_goal_specific() -> None:
    contract = parse_requirement_contract(
        requirement_contract_json(),
        "构建会员增长平台",
    )
    fallback = build_fallback_requirement_contract("制作宠物医院预约与复诊提醒系统")
    long_input_fallback = build_fallback_requirement_contract("长目标" * 1000)

    assert contract is not None
    assert [item.criterion_id for item in contract.acceptance_criteria] == ["AC-01", "AC-02"]
    assert contract.acceptance_criteria[1].priority == "MUST"
    assert parse_requirement_contract("not-json", "构建会员增长平台") is None
    assert "宠物医院预约与复诊提醒系统" in fallback.objective
    assert "宠物医院预约与复诊提醒系统" in fallback.in_scope[0]
    assert all(item.criterion_id.startswith("AC-") for item in fallback.acceptance_criteria)
    assert len(long_input_fallback.objective) <= 1000
    assert all(len(item) <= 500 for item in long_input_fallback.in_scope)


def test_requirement_reviews_reject_ambiguous_contracts_and_consensus_preserves_evidence() -> None:
    contract = parse_requirement_contract(requirement_contract_json(), "构建会员增长平台")
    assert contract is not None
    architect = parse_requirement_review(
        json.dumps(
            {
                "decision": "CHALLENGE",
                "confidence": 0.9,
                "summary": "缺少生产数据保留和故障恢复边界。",
                "concerns": ["未定义生产数据保留周期"],
                "proposed_changes": ["补充数据保留周期与恢复责任人"],
            },
            ensure_ascii=False,
        ),
        "architect",
    )
    tester = parse_requirement_review(
        json.dumps(
            {
                "decision": "ACCEPT",
                "confidence": 0.92,
                "summary": "验收标准包含行为、证据和恢复阈值，可以测试。",
                "concerns": [],
                "proposed_changes": [],
            },
            ensure_ascii=False,
        ),
        "test_engineer",
    )
    invalid_accept = parse_requirement_review(
        json.dumps(
            {
                "decision": "ACCEPT",
                "confidence": 0.8,
                "summary": "接受但仍声明缺口。",
                "concerns": ["仍缺少数据边界"],
                "proposed_changes": [],
            },
            ensure_ascii=False,
        ),
        "architect",
    )
    empty_challenge = parse_requirement_review(
        json.dumps(
            {
                "decision": "CHALLENGE",
                "confidence": 0.8,
                "summary": "需求不够清晰。",
                "concerns": [],
                "proposed_changes": [],
            },
            ensure_ascii=False,
        ),
        "test_engineer",
    )

    consensus = build_requirement_consensus(
        contract,
        [architect, tester],
        origin="model_draft",
    )

    assert consensus.status == "CHALLENGED"
    assert consensus.reviewer_valid_count == 2
    assert consensus.reviewer_accept_count == 1
    assert consensus.reviewer_challenge_count == 1
    assert len(consensus.contract_fingerprint) == 64
    assert invalid_accept.decision == "ABSTAIN"
    assert invalid_accept.structured is False
    assert empty_challenge.decision == "ABSTAIN"
