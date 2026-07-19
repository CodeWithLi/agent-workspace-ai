import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.models import (
    Agent,
    Conversation,
    EvaluationCase,
    EvaluationFeedbackReview,
    Message,
    MessageFeedback,
    User,
)
from app.services.evaluation_privacy import (
    redact_evaluation_case_values,
    redact_evaluation_text,
)


class EvaluationFeedbackConflict(RuntimeError):
    pass


def _json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _source_objects(
    db: Session,
    feedback: MessageFeedback,
) -> tuple[Message, Conversation, Agent, User | None, Message | None]:
    message = db.get(Message, feedback.message_id)
    if not message or message.role != "assistant":
        raise EvaluationFeedbackConflict("Feedback source answer no longer exists")
    conversation = db.get(Conversation, message.conversation_id)
    if not conversation:
        raise EvaluationFeedbackConflict("Feedback source conversation no longer exists")
    agent = db.get(Agent, message.agent_id or conversation.agent_id)
    if not agent:
        raise EvaluationFeedbackConflict("Feedback source Agent no longer exists")
    source_user = db.get(User, feedback.user_id)
    user_message = db.get(Message, message.parent_message_id) if message.parent_message_id else None
    if not user_message or user_message.role != "user":
        user_message = db.scalar(
            select(Message)
            .where(
                Message.conversation_id == conversation.id,
                Message.role == "user",
                Message.id < message.id,
            )
            .order_by(Message.id.desc())
            .limit(1)
        )
    return message, conversation, agent, source_user, user_message


def _source_snapshot(db: Session, feedback: MessageFeedback) -> dict[str, Any]:
    message, conversation, agent, source_user, user_message = _source_objects(db, feedback)
    return {
        "feedback_id": feedback.id,
        "message_id": message.id,
        "user_message_id": user_message.id if user_message else None,
        "conversation_id": conversation.id,
        "project_id": conversation.project_id,
        "user_id": feedback.user_id,
        "user_name": source_user.name if source_user else f"User #{feedback.user_id}",
        "agent_id": agent.id,
        "agent_name": agent.name,
        "agent_role": str(getattr(agent.role, "value", agent.role)),
        "input_text": user_message.content if user_message else "",
        "answer": message.content,
        "comment": feedback.comment,
        "rating": feedback.rating,
        "feedback_created_at": feedback.created_at.isoformat(),
    }


def _candidate_data(
    snapshot: dict[str, Any],
    review: EvaluationFeedbackReview | None = None,
) -> dict[str, Any]:
    redacted_fields: list[str] = []
    redaction_count = 0
    redacted_values: dict[str, str] = {}
    personal_names = (str(snapshot.get("user_name") or ""),)
    for field in ("input_text", "answer", "comment", "resolution_note"):
        raw_value = review.resolution_note if field == "resolution_note" and review else snapshot.get(field)
        result = redact_evaluation_text(
            str(raw_value or ""),
            personal_names=personal_names,
        )
        redacted_values[field] = result.text
        redaction_count += result.count
        if result.count:
            redacted_fields.append(field)
    return {
        "feedback_id": int(snapshot["feedback_id"]),
        "review_id": review.id if review else None,
        "status": review.status if review else "PENDING",
        "evaluation_case_id": review.evaluation_case_id if review else None,
        "message_id": int(snapshot["message_id"]),
        "conversation_id": int(snapshot["conversation_id"]),
        "project_id": snapshot.get("project_id"),
        "user_id": int(snapshot["user_id"]),
        "user_name": f"User #{snapshot['user_id']}",
        "agent_id": int(snapshot["agent_id"]),
        "agent_name": str(snapshot.get("agent_name") or f"Agent #{snapshot['agent_id']}"),
        "agent_role": str(snapshot.get("agent_role") or ""),
        "input_text": redacted_values["input_text"],
        "answer": redacted_values["answer"],
        "comment": redacted_values["comment"],
        "resolution_note": redacted_values["resolution_note"],
        "redaction_count": redaction_count,
        "redacted_fields": redacted_fields,
        "created_at": snapshot["feedback_created_at"],
        "reviewed_at": review.reviewed_at if review else None,
    }


def _pending_feedback(db: Session, *, limit: int = 100) -> list[dict[str, Any]]:
    parent = aliased(Message)
    rows = db.execute(
        select(
            MessageFeedback,
            Message,
            Conversation,
            Agent,
            User,
            parent,
        )
        .join(Message, Message.id == MessageFeedback.message_id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .join(Agent, Agent.id == func.coalesce(Message.agent_id, Conversation.agent_id))
        .join(User, User.id == MessageFeedback.user_id)
        .outerjoin(parent, parent.id == Message.parent_message_id)
        .outerjoin(
            EvaluationFeedbackReview,
            EvaluationFeedbackReview.feedback_id == MessageFeedback.id,
        )
        .where(
            MessageFeedback.rating == -1,
            Message.role == "assistant",
            EvaluationFeedbackReview.id.is_(None),
        )
        .order_by(MessageFeedback.created_at.desc(), MessageFeedback.id.desc())
        .limit(limit)
    ).all()
    output: list[dict[str, Any]] = []
    for feedback, message, conversation, agent, source_user, user_message in rows:
        if not user_message or user_message.role != "user":
            user_message = db.scalar(
                select(Message)
                .where(
                    Message.conversation_id == conversation.id,
                    Message.role == "user",
                    Message.id < message.id,
                )
                .order_by(Message.id.desc())
                .limit(1)
            )
        snapshot = {
            "feedback_id": feedback.id,
            "message_id": message.id,
            "conversation_id": conversation.id,
            "project_id": conversation.project_id,
            "user_id": feedback.user_id,
            "user_name": source_user.name,
            "agent_id": agent.id,
            "agent_name": agent.name,
            "agent_role": str(getattr(agent.role, "value", agent.role)),
            "input_text": user_message.content if user_message else "",
            "answer": message.content,
            "comment": feedback.comment,
            "feedback_created_at": feedback.created_at,
        }
        output.append(_candidate_data(snapshot))
    return output


def _reviewed_feedback(
    db: Session,
    status: str | None = None,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    stmt = select(EvaluationFeedbackReview)
    if status:
        stmt = stmt.where(EvaluationFeedbackReview.status == status)
    reviews = db.scalars(
        stmt.order_by(
            EvaluationFeedbackReview.reviewed_at.desc(),
            EvaluationFeedbackReview.id.desc(),
        ).limit(limit)
    )
    return [
        _candidate_data(_json_object(review.source_snapshot_json), review)
        for review in reviews
    ]


def list_feedback_candidates(
    db: Session,
    status: str,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    if status == "PENDING":
        return _pending_feedback(db, limit=limit)
    if status in {"CONVERTED", "DISMISSED"}:
        return _reviewed_feedback(db, status, limit=limit)
    if status == "ALL":
        rows = [*_pending_feedback(db, limit=limit), *_reviewed_feedback(db, limit=limit)]
        return sorted(
            rows,
            key=lambda item: str(item.get("reviewed_at") or item["created_at"]),
            reverse=True,
        )[:limit]
    raise ValueError("Feedback status must be PENDING, CONVERTED, DISMISSED or ALL")


def reviewed_feedback_candidate(review: EvaluationFeedbackReview) -> dict[str, Any]:
    return _candidate_data(_json_object(review.source_snapshot_json), review)


def _existing_review(
    db: Session,
    *,
    feedback_id: int,
    request_id: str,
    expected_status: str,
) -> EvaluationFeedbackReview | None:
    request_match = db.scalar(
        select(EvaluationFeedbackReview).where(
            EvaluationFeedbackReview.request_id == request_id
        )
    )
    if request_match:
        if request_match.feedback_id != feedback_id or request_match.status != expected_status:
            raise EvaluationFeedbackConflict("Feedback review request ID is already in use")
        return request_match
    feedback_match = db.scalar(
        select(EvaluationFeedbackReview).where(
            EvaluationFeedbackReview.feedback_id == feedback_id
        )
    )
    if feedback_match:
        raise EvaluationFeedbackConflict("Feedback has already been reviewed")
    return None


def promote_feedback_to_case(
    db: Session,
    *,
    feedback_id: int,
    request_id: str,
    user_id: int,
    case_values: dict[str, Any],
) -> tuple[EvaluationFeedbackReview, bool]:
    request_id = request_id.strip()[:64]
    existing = _existing_review(
        db,
        feedback_id=feedback_id,
        request_id=request_id,
        expected_status="CONVERTED",
    )
    if existing:
        return existing, False
    feedback = db.scalar(
        select(MessageFeedback)
        .where(MessageFeedback.id == feedback_id)
        .with_for_update()
    )
    if not feedback or feedback.rating != -1:
        raise EvaluationFeedbackConflict("Only current negative feedback can enter the evaluation dataset")
    snapshot = _source_snapshot(db, feedback)
    if not snapshot["input_text"]:
        raise EvaluationFeedbackConflict("Feedback source user input is unavailable")
    redacted = redact_evaluation_case_values(
        {**case_values, "input_text": snapshot["input_text"]},
        personal_names=(str(snapshot.get("user_name") or ""),),
    )
    case = EvaluationCase(
        name=str(redacted["name"]).strip(),
        agent_role=snapshot["agent_role"],
        input_text=str(redacted["input_text"]).strip(),
        expected_keywords_json=json.dumps(redacted["expected_keywords"], ensure_ascii=False),
        forbidden_keywords_json=json.dumps(redacted["forbidden_keywords"], ensure_ascii=False),
        rubric=str(redacted["rubric"]).strip(),
        minimum_score=float(case_values["minimum_score"]),
        weight=float(case_values["weight"]),
        enabled=True,
        created_by_user_id=user_id,
    )
    db.add(case)
    db.flush()
    review = EvaluationFeedbackReview(
        request_id=request_id,
        feedback_id=feedback.id,
        evaluation_case_id=case.id,
        status="CONVERTED",
        source_user_id=feedback.user_id,
        agent_id=snapshot["agent_id"],
        message_id=snapshot["message_id"],
        user_message_id=snapshot["user_message_id"],
        agent_role=snapshot["agent_role"],
        source_snapshot_json=json.dumps(snapshot, ensure_ascii=False),
        resolution_note="Converted to evaluation case",
        reviewed_by_user_id=user_id,
        reviewed_at=datetime.now(timezone.utc),
    )
    db.add(review)
    db.flush()
    return review, True


def dismiss_feedback_candidate(
    db: Session,
    *,
    feedback_id: int,
    request_id: str,
    user_id: int,
    reason: str,
) -> tuple[EvaluationFeedbackReview, bool]:
    request_id = request_id.strip()[:64]
    existing = _existing_review(
        db,
        feedback_id=feedback_id,
        request_id=request_id,
        expected_status="DISMISSED",
    )
    if existing:
        return existing, False
    feedback = db.scalar(
        select(MessageFeedback)
        .where(MessageFeedback.id == feedback_id)
        .with_for_update()
    )
    if not feedback or feedback.rating != -1:
        raise EvaluationFeedbackConflict("Only current negative feedback can be reviewed")
    snapshot = _source_snapshot(db, feedback)
    review = EvaluationFeedbackReview(
        request_id=request_id,
        feedback_id=feedback.id,
        status="DISMISSED",
        source_user_id=feedback.user_id,
        agent_id=snapshot["agent_id"],
        message_id=snapshot["message_id"],
        user_message_id=snapshot["user_message_id"],
        agent_role=snapshot["agent_role"],
        source_snapshot_json=json.dumps(snapshot, ensure_ascii=False),
        resolution_note=reason.strip(),
        reviewed_by_user_id=user_id,
        reviewed_at=datetime.now(timezone.utc),
    )
    db.add(review)
    db.flush()
    return review, True
