import json

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.api.deps import require_admin
from app.api.routes.evaluations import (
    dismiss_evaluation_feedback,
    list_evaluation_feedback,
    promote_evaluation_feedback,
)
from app.models import (
    Agent,
    AgentRole,
    AuditLog,
    Conversation,
    EvaluationCase,
    EvaluationFeedbackReview,
    Message,
    MessageFeedback,
    User,
    UserRole,
)
from app.schemas import EvaluationFeedbackDismissRequest, EvaluationFeedbackPromoteRequest


def request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/evaluations/feedback/1/promote",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 1234),
        }
    )


def seed_feedback(
    db: Session,
) -> tuple[User, User, MessageFeedback, MessageFeedback, MessageFeedback, Message, Message]:
    admin = User(
        email="feedback-admin@example.com",
        name="Feedback Admin",
        password_hash="hash",
        role=UserRole.admin,
    )
    member = User(
        email="feedback-member@example.com",
        name="Feedback Member",
        password_hash="hash",
        role=UserRole.member,
    )
    agent = Agent(
        name="Feedback Architect",
        role=AgentRole.architect,
        description="Architecture feedback Agent",
        system_prompt="architecture",
        model="test-model",
        tools="",
        current_version=3,
    )
    db.add_all([admin, member, agent])
    db.flush()
    conversation = Conversation(
        title="Feedback source",
        agent_id=agent.id,
        user_id=member.id,
    )
    db.add(conversation)
    db.flush()

    first_input = Message(
        conversation_id=conversation.id,
        role="user",
        content="Design a tenant-safe architecture with citations",
    )
    second_input = Message(
        conversation_id=conversation.id,
        role="user",
        content="Explain the rollback sequence",
    )
    positive_input = Message(
        conversation_id=conversation.id,
        role="user",
        content="Summarize the architecture",
    )
    db.add_all([first_input, second_input, positive_input])
    db.flush()
    first_answer = Message(
        conversation_id=conversation.id,
        agent_id=agent.id,
        role="assistant",
        content="Sensitive weak answer without citations",
        parent_message_id=first_input.id,
    )
    second_answer = Message(
        conversation_id=conversation.id,
        agent_id=agent.id,
        role="assistant",
        content="Rollback answer needs ordering",
        parent_message_id=second_input.id,
    )
    positive_answer = Message(
        conversation_id=conversation.id,
        agent_id=agent.id,
        role="assistant",
        content="Helpful architecture summary",
        parent_message_id=positive_input.id,
    )
    db.add_all([first_answer, second_answer, positive_answer])
    db.flush()
    first_feedback = MessageFeedback(
        message_id=first_answer.id,
        user_id=member.id,
        rating=-1,
        comment="Sensitive comment: citations are missing",
    )
    second_feedback = MessageFeedback(
        message_id=second_answer.id,
        user_id=member.id,
        rating=-1,
        comment="The sequence is ambiguous",
    )
    positive_feedback = MessageFeedback(
        message_id=positive_answer.id,
        user_id=member.id,
        rating=1,
        comment="Useful",
    )
    db.add_all([first_feedback, second_feedback, positive_feedback])
    db.commit()
    return (
        admin,
        member,
        first_feedback,
        second_feedback,
        positive_feedback,
        first_input,
        first_answer,
    )


def test_only_admins_can_triage_negative_feedback(db: Session) -> None:
    admin, member, first, second, positive, _, _ = seed_feedback(db)
    conversation_id = db.get(Message, second.message_id).conversation_id
    fallback_input = Message(
        conversation_id=conversation_id,
        role="user",
        content="Recover this source input without a parent link",
    )
    db.add(fallback_input)
    db.flush()
    fallback_answer = Message(
        conversation_id=conversation_id,
        agent_id=db.get(Message, second.message_id).agent_id,
        role="assistant",
        content="Weak answer with no parent link",
    )
    db.add(fallback_answer)
    db.flush()
    fallback_feedback = MessageFeedback(
        message_id=fallback_answer.id,
        user_id=member.id,
        rating=-1,
        comment="Missing traceable evidence",
    )
    db.add(fallback_feedback)
    db.commit()

    with pytest.raises(HTTPException) as permission_error:
        require_admin(member)
    assert permission_error.value.status_code == 403

    pending = list_evaluation_feedback("PENDING", admin, db)
    assert {item.feedback_id for item in pending} == {first.id, second.id, fallback_feedback.id}
    assert positive.id not in {item.feedback_id for item in pending}
    first_item = next(item for item in pending if item.feedback_id == first.id)
    assert first_item.agent_role == AgentRole.architect.value
    assert first_item.input_text == "Design a tenant-safe architecture with citations"
    assert first_item.answer == "Sensitive weak answer without citations"
    fallback_item = next(item for item in pending if item.feedback_id == fallback_feedback.id)
    assert fallback_item.input_text == "Recover this source input without a parent link"


def test_feedback_review_payloads_strip_and_reject_blank_text() -> None:
    promote = EvaluationFeedbackPromoteRequest(
        request_id="  feedback-request  ",
        name="  Evidence regression  ",
        expected_keywords=[" evidence "],
        forbidden_keywords=[],
        rubric="  Cite verifiable evidence.  ",
    )
    dismiss = EvaluationFeedbackDismissRequest(
        request_id="  dismiss-request  ",
        reason="  Not reproducible  ",
    )

    assert promote.request_id == "feedback-request"
    assert promote.name == "Evidence regression"
    assert promote.expected_keywords == ["evidence"]
    assert promote.rubric == "Cite verifiable evidence."
    assert dismiss.reason == "Not reproducible"

    with pytest.raises(ValidationError):
        EvaluationFeedbackPromoteRequest(
            request_id="        ",
            name="Evidence regression",
            expected_keywords=[],
            forbidden_keywords=[],
            rubric="Cite evidence",
        )
    with pytest.raises(ValidationError):
        EvaluationFeedbackDismissRequest(
            request_id="dismiss-request",
            reason="   ",
        )


def test_feedback_promotion_is_idempotent_and_freezes_source_evidence(db: Session) -> None:
    admin, _, feedback, _, _, source_input, source_answer = seed_feedback(db)
    payload = EvaluationFeedbackPromoteRequest(
        request_id="feedback-promotion-request",
        name="Architecture citation regression",
        expected_keywords=["citation", "tenant"],
        forbidden_keywords=["skip isolation"],
        rubric="The answer must isolate tenants and cite evidence.",
        minimum_score=0.8,
        weight=2,
    )

    first = promote_evaluation_feedback(feedback.id, payload, request(), admin, db)
    second = promote_evaluation_feedback(feedback.id, payload, request(), admin, db)

    assert first.review_id == second.review_id
    assert first.status == "CONVERTED"
    assert first.evaluation_case_id is not None
    case = db.get(EvaluationCase, first.evaluation_case_id)
    assert case is not None
    assert case.agent_role == AgentRole.architect.value
    assert case.input_text == source_input.content
    assert json.loads(case.expected_keywords_json) == ["citation", "tenant"]
    assert db.scalar(select(func.count(EvaluationCase.id))) == 1
    assert db.scalar(select(func.count(EvaluationFeedbackReview.id))) == 1

    review = db.get(EvaluationFeedbackReview, first.review_id)
    snapshot = json.loads(review.source_snapshot_json)
    assert snapshot["input_text"] == "Design a tenant-safe architecture with citations"
    assert snapshot["answer"] == "Sensitive weak answer without citations"
    assert snapshot["comment"] == "Sensitive comment: citations are missing"

    source_input.content = "Mutated source input"
    source_answer.content = "Mutated source answer"
    feedback.comment = "Mutated feedback"
    db.commit()
    converted = list_evaluation_feedback("CONVERTED", admin, db)
    assert converted[0].input_text == "Design a tenant-safe architecture with citations"
    assert converted[0].answer == "Sensitive weak answer without citations"
    assert converted[0].comment == "Sensitive comment: citations are missing"

    audit = db.scalar(select(AuditLog).where(AuditLog.action == "evaluation.feedback_convert"))
    assert audit is not None
    assert "Sensitive weak answer" not in audit.details
    assert "Sensitive comment" not in audit.details

    with pytest.raises(HTTPException) as conflict:
        promote_evaluation_feedback(
            feedback.id,
            payload.model_copy(update={"request_id": "different-promotion-request"}),
            request(),
            admin,
            db,
        )
    assert conflict.value.status_code == 409


def test_feedback_dismissal_is_idempotent_and_positive_feedback_is_ineligible(db: Session) -> None:
    admin, _, _, feedback, positive, _, _ = seed_feedback(db)
    payload = EvaluationFeedbackDismissRequest(
        request_id="feedback-dismiss-request",
        reason="Not reproducible after reviewing the full conversation",
    )

    first = dismiss_evaluation_feedback(feedback.id, payload, request(), admin, db)
    second = dismiss_evaluation_feedback(feedback.id, payload, request(), admin, db)

    assert first.review_id == second.review_id
    assert first.status == "DISMISSED"
    assert first.evaluation_case_id is None
    assert first.resolution_note == payload.reason
    assert db.scalar(select(func.count(EvaluationFeedbackReview.id))) == 1
    assert db.scalar(select(func.count(EvaluationCase.id))) == 0

    with pytest.raises(HTTPException) as positive_error:
        promote_evaluation_feedback(
            positive.id,
            EvaluationFeedbackPromoteRequest(
                request_id="positive-feedback-request",
                name="Ineligible positive feedback",
                expected_keywords=[],
                forbidden_keywords=[],
                rubric="Positive feedback must not enter the failure dataset.",
                minimum_score=0.8,
                weight=1,
            ),
            request(),
            admin,
            db,
        )
    assert positive_error.value.status_code == 409
