import asyncio
import logging
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from sqlalchemy import or_, select

from app.core.audit import record_audit
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import Notification


logger = logging.getLogger(__name__)
settings = get_settings()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class NotificationDeliveryError(RuntimeError):
    pass


def send_email(notification: Notification) -> None:
    if not settings.smtp_host or not settings.smtp_from_email:
        raise NotificationDeliveryError("SMTP_HOST and SMTP_FROM_EMAIL are required for email delivery")
    if not notification.recipient_email:
        raise NotificationDeliveryError("Email recipient is missing")
    message = EmailMessage()
    message["From"] = settings.smtp_from_email
    message["To"] = notification.recipient_email
    message["Subject"] = notification.title
    message.set_content(notification.content)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as client:
        if settings.smtp_starttls:
            client.starttls()
        if settings.smtp_username:
            client.login(settings.smtp_username, settings.smtp_password or "")
        client.send_message(message)


async def deliver(notification: Notification) -> None:
    if notification.channel == "in_app":
        if notification.recipient_user_id is None:
            raise NotificationDeliveryError("In-app recipient user is missing")
        return
    if notification.channel == "email":
        await asyncio.to_thread(send_email, notification)
        return
    raise NotificationDeliveryError(f"Unsupported notification channel: {notification.channel}")


class NotificationDispatcher:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if not settings.notification_worker_enabled or self._task:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="notification-dispatcher")
        logger.info("Notification dispatcher started")

    async def stop(self) -> None:
        if not self._task:
            return
        self._stop.set()
        await self._task
        self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.dispatch_due()
            except Exception:
                logger.exception("Notification dispatcher iteration failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=settings.notification_poll_seconds)
            except TimeoutError:
                pass

    async def dispatch_due(self) -> int:
        claimed_ids = self._claim_due()
        for notification_id in claimed_ids:
            await self._deliver_claimed(notification_id)
        return len(claimed_ids)

    def _claim_due(self) -> list[int]:
        now = utc_now()
        stale_lock = now - timedelta(minutes=5)
        with SessionLocal() as db:
            stmt = (
                select(Notification)
                .where(
                    Notification.attempts < settings.notification_max_attempts,
                    or_(
                        (Notification.status == "SCHEDULED") & (Notification.scheduled_for <= now),
                        (Notification.status == "SENDING") & (Notification.locked_at <= stale_lock),
                    ),
                )
                .order_by(Notification.scheduled_for)
                .limit(20)
                .with_for_update(skip_locked=True)
            )
            notifications = list(db.scalars(stmt))
            for notification in notifications:
                notification.status = "SENDING"
                notification.locked_at = now
                notification.attempts += 1
            db.commit()
            return [notification.id for notification in notifications]

    async def _deliver_claimed(self, notification_id: int) -> None:
        with SessionLocal() as db:
            notification = db.get(Notification, notification_id)
            if not notification or notification.status != "SENDING":
                return
            try:
                await deliver(notification)
                notification.status = "SENT"
                notification.sent_at = utc_now()
                notification.locked_at = None
                notification.last_error = ""
                record_audit(
                    db,
                    "notification.sent",
                    notification.user_id,
                    notification.project_id,
                    "notification",
                    notification.id,
                    {"channel": notification.channel, "recipient_user_id": notification.recipient_user_id},
                )
            except Exception as exc:
                notification.last_error = str(exc)[:1000]
                notification.locked_at = None
                if notification.attempts >= settings.notification_max_attempts:
                    notification.status = "FAILED"
                else:
                    notification.status = "SCHEDULED"
                    notification.scheduled_for = utc_now() + timedelta(minutes=2 ** notification.attempts)
                record_audit(
                    db,
                    "notification.failed",
                    notification.user_id,
                    notification.project_id,
                    "notification",
                    notification.id,
                    {"channel": notification.channel, "attempt": notification.attempts, "error": notification.last_error},
                )
            db.commit()


notification_dispatcher = NotificationDispatcher()
