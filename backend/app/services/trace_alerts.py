import asyncio
import logging

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.observability import sync_trace_alerts


logger = logging.getLogger(__name__)
settings = get_settings()


class TraceAlertDispatcher:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if not settings.observability_alert_worker_enabled or self._task:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="trace-alert-dispatcher")
        logger.info("Trace alert dispatcher started")

    async def stop(self) -> None:
        if not self._task:
            return
        self._stop.set()
        await self._task
        self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.sync_once()
            except Exception:
                logger.exception("Trace alert dispatcher iteration failed")
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=settings.observability_alert_poll_seconds,
                )
            except TimeoutError:
                pass

    def sync_once(self) -> int:
        with SessionLocal() as db:
            created_count = sync_trace_alerts(
                db,
                None,
                days=settings.observability_alert_lookback_days,
                project_id=None,
            )
            db.commit()
            return created_count


trace_alert_dispatcher = TraceAlertDispatcher()
