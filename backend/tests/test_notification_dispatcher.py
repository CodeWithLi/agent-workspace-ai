from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import AuditLog, Notification, User, UserRole
from app.services import notifications as notification_service


@pytest.mark.asyncio
async def test_dispatcher_delivers_in_app_notification_once(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(notification_service, "SessionLocal", factory)
    sender = User(email="sender@example.com", name="Sender", password_hash="hash", role=UserRole.member)
    recipient = User(email="recipient@example.com", name="Recipient", password_hash="hash", role=UserRole.member)
    db.add_all([sender, recipient])
    db.flush()
    item = Notification(
        user_id=sender.id,
        recipient_user_id=recipient.id,
        recipient_email=recipient.email,
        title="Review",
        content="Please review",
        channel="in_app",
        status="SCHEDULED",
        scheduled_for=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    db.add(item)
    db.commit()

    dispatcher = notification_service.NotificationDispatcher()
    assert await dispatcher.dispatch_due() == 1
    db.expire_all()
    delivered = db.get(Notification, item.id)
    assert delivered is not None
    assert delivered.status == "SENT"
    assert delivered.attempts == 1
    assert delivered.sent_at is not None
    assert await dispatcher.dispatch_due() == 0
    assert db.scalar(select(func.count(AuditLog.id)).where(AuditLog.action == "notification.sent")) == 1


@pytest.mark.asyncio
async def test_dispatcher_records_terminal_email_failure(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(notification_service, "SessionLocal", factory)
    monkeypatch.setattr(notification_service.settings, "notification_max_attempts", 1)
    monkeypatch.setattr(notification_service.settings, "smtp_host", None)
    sender = User(email="mail-sender@example.com", name="Sender", password_hash="hash", role=UserRole.member)
    db.add(sender)
    db.flush()
    item = Notification(
        user_id=sender.id,
        recipient_email="target@example.com",
        title="Mail",
        content="Body",
        channel="email",
        status="SCHEDULED",
        scheduled_for=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    db.add(item)
    db.commit()

    assert await notification_service.NotificationDispatcher().dispatch_due() == 1
    db.expire_all()
    failed = db.get(Notification, item.id)
    assert failed is not None
    assert failed.status == "FAILED"
    assert "SMTP_HOST" in failed.last_error
    assert db.scalar(select(func.count(AuditLog.id)).where(AuditLog.action == "notification.failed")) == 1
