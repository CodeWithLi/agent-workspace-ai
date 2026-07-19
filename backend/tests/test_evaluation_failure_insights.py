import json

from sqlalchemy.orm import Session

from app.models import (
    Agent,
    AgentRole,
    Conversation,
    EvaluationCase,
    Message,
    MessageFeedback,
    User,
    UserRole,
)
from app.schemas import EvaluationFailureInsightsOut
from app.services.evaluation_failure_insights import build_failure_insights
from app.services.evaluation_feedback import (
    dismiss_feedback_candidate,
    promote_feedback_to_case,
)
from app.services.evaluation_privacy import (
    redact_evaluation_case_values,
    redact_evaluation_text,
)


def _feedback(
    db: Session,
    *,
    user: User,
    agent: Agent,
    input_text: str,
    answer: str,
    comment: str,
) -> MessageFeedback:
    conversation = Conversation(
        title="Failure insight source",
        agent_id=agent.id,
        user_id=user.id,
    )
    db.add(conversation)
    db.flush()
    user_message = Message(
        conversation_id=conversation.id,
        role="user",
        content=input_text,
    )
    db.add(user_message)
    db.flush()
    assistant_message = Message(
        conversation_id=conversation.id,
        agent_id=agent.id,
        role="assistant",
        content=answer,
        parent_message_id=user_message.id,
    )
    db.add(assistant_message)
    db.flush()
    feedback = MessageFeedback(
        message_id=assistant_message.id,
        user_id=user.id,
        rating=-1,
        comment=comment,
    )
    db.add(feedback)
    db.flush()
    return feedback


def test_evaluation_redaction_replaces_identifiers_and_secrets() -> None:
    source = (
        "联系 alice@example.com 或 +86 13800138000，身份证 11010519491231002X，"
        "银行卡 6222 0212 3456 7890，IP 192.168.10.8，Authorization: Bearer abcdefghijklmnop，"
        "api_key=sk-live-secret-value"
    )

    result = redact_evaluation_text(source)

    assert "alice@example.com" not in result.text
    assert "13800138000" not in result.text
    assert "11010519491231002X" not in result.text
    assert "6222 0212 3456 7890" not in result.text
    assert "192.168.10.8" not in result.text
    assert "abcdefghijklmnop" not in result.text
    assert "sk-live-secret-value" not in result.text
    assert set(result.categories) == {
        "bank_card",
        "credential",
        "email",
        "id_number",
        "ip_address",
        "phone",
    }
    assert result.count == 7
    assert redact_evaluation_text("计划版本 2026，评分 0.85").text == "计划版本 2026，评分 0.85"
    named = redact_evaluation_text(
        "Alice Sensitive 提交了这个反馈",
        personal_names=("Alice Sensitive",),
    )
    assert named.text == "[NAME_REDACTED] 提交了这个反馈"
    assert named.categories == ("name",)

    case_values = redact_evaluation_case_values(
        {
            "name": "alice@example.com 回归",
            "input_text": "联系 13800138000",
            "expected_keywords": ["alice@example.com"],
            "forbidden_keywords": ["sk-production-secret-value"],
            "rubric": "不得输出 api_key=sk-production-secret-value",
        },
        personal_names=("Alice Sensitive",),
    )
    assert "alice@example.com" not in json.dumps(case_values, ensure_ascii=False)
    assert "13800138000" not in str(case_values["input_text"])
    assert "sk-production-secret-value" not in json.dumps(case_values, ensure_ascii=False)


def test_failure_insights_cluster_by_role_redact_evidence_and_measure_coverage(
    db: Session,
) -> None:
    user = User(
        email="insight-source@example.com",
        name="Alice Sensitive",
        password_hash="hash",
        role=UserRole.member,
    )
    architect = Agent(
        name="Insight Architect",
        role=AgentRole.architect,
        description="Architecture Agent",
        system_prompt="architecture",
        model="test-model",
        tools="",
    )
    tester = Agent(
        name="Insight Tester",
        role=AgentRole.test_engineer,
        description="Testing Agent",
        system_prompt="testing",
        model="test-model",
        tools="",
    )
    db.add_all([user, architect, tester])
    db.flush()
    first = _feedback(
        db,
        user=user,
        agent=architect,
        input_text="为 alice@example.com 设计租户隔离，并提供引用证据",
        answer="请使用 token=top-secret-token 共享数据库。",
        comment="缺少租户隔离与引用证据",
    )
    second = _feedback(
        db,
        user=user,
        agent=architect,
        input_text="解释租户隔离方案与可验证引用",
        answer="没有引用来源。",
        comment="租户隔离没有引用证据",
    )
    third = _feedback(
        db,
        user=user,
        agent=tester,
        input_text="为手机号 13800138000 设计回归测试",
        answer="只测试成功路径。",
        comment="缺少异常路径与边界测试",
    )
    ignored = _feedback(
        db,
        user=user,
        agent=architect,
        input_text="旧的无关反馈",
        answer="旧回答",
        comment="已经确认不可复现",
    )
    converted, _ = promote_feedback_to_case(
        db,
        feedback_id=first.id,
        request_id="converted-feedback-insight",
        user_id=user.id,
        case_values={
            "name": "架构租户隔离引用回归",
            "expected_keywords": ["租户隔离", "引用证据"],
            "forbidden_keywords": [],
            "rubric": "必须提供可验证的隔离边界和引用。",
            "minimum_score": 0.8,
            "weight": 1,
        },
    )
    dismiss_feedback_candidate(
        db,
        feedback_id=ignored.id,
        request_id="dismissed-feedback-insight",
        user_id=user.id,
        reason="不可复现",
    )
    db.commit()
    case = db.get(EvaluationCase, converted.evaluation_case_id)
    assert case is not None

    insights = build_failure_insights(db)
    response = EvaluationFailureInsightsOut(**insights)

    assert insights["source_feedback_count"] == 3
    assert response.source_feedback_count == 3
    assert insights["pending_feedback_count"] == 2
    assert insights["converted_feedback_count"] == 1
    assert insights["total_cluster_count"] == 2
    assert insights["covered_cluster_count"] == 1
    assert insights["gap_cluster_count"] == 1
    assert insights["coverage_percent"] == 0.5
    assert insights["redacted_value_count"] >= 3
    clusters = {cluster["agent_role"]: cluster for cluster in insights["clusters"]}
    architecture = clusters[AgentRole.architect.value]
    assert architecture["failure_count"] == 2
    assert architecture["coverage_status"] == "COVERED"
    assert architecture["matching_case_ids"] == [case.id]
    assert architecture["representative"]["feedback_id"] == second.id
    assert architecture["representative"]["user_name"] == f"User #{user.id}"
    assert "alice@example.com" not in json.dumps(architecture, ensure_ascii=False, default=str)
    testing = clusters[AgentRole.test_engineer.value]
    assert testing["failure_count"] == 1
    assert testing["coverage_status"] == "GAP"
    assert testing["recommended_action"] == "CREATE_CASE"
    assert testing["representative"]["feedback_id"] == third.id
    assert "13800138000" not in json.dumps(testing, ensure_ascii=False, default=str)


def test_failure_cluster_ids_are_unique_when_evidence_has_no_tokens(db: Session) -> None:
    user = User(
        email="empty-insight@example.com",
        name="Empty Insight User",
        password_hash="hash",
        role=UserRole.member,
    )
    agent = Agent(
        name="Empty Insight Architect",
        role=AgentRole.architect,
        description="Architecture Agent",
        system_prompt="architecture",
        model="test-model",
        tools="",
    )
    db.add_all([user, agent])
    db.flush()
    _feedback(
        db,
        user=user,
        agent=agent,
        input_text="好",
        answer="甲",
        comment="",
    )
    _feedback(
        db,
        user=user,
        agent=agent,
        input_text="差",
        answer="乙",
        comment="",
    )
    db.commit()

    clusters = build_failure_insights(db)["clusters"]

    assert len(clusters) == 2
    assert len({cluster["cluster_id"] for cluster in clusters}) == 2
