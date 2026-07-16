import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.audit import record_audit
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import AgentRun
from app.services.billing import refund_consumption


logger = logging.getLogger(__name__)
settings = get_settings()


class AgentRunReaper:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="agent-run-reaper")

    async def stop(self) -> None:
        if not self._task:
            return
        self._stop.set()
        await self._task
        self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.recover_once()
            except Exception:
                logger.exception("Agent run reaper iteration failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=60)
            except TimeoutError:
                pass

    def recover_once(self) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.agent_run_stale_minutes)
        with SessionLocal() as db:
            runs = list(
                db.scalars(
                    select(AgentRun)
                    .where(AgentRun.status == "RUNNING", AgentRun.started_at <= cutoff)
                    .with_for_update(skip_locked=True)
                    .limit(100)
                )
            )
            for run in runs:
                run.status = "FAILED"
                run.error = "Execution lease expired before completion"
                run.finished_at = datetime.now(timezone.utc)
                if run.billing_transaction_id:
                    refund_consumption(db, run.billing_transaction_id, "Stale Agent run recovered")
                record_audit(
                    db,
                    "agent.run_recovered",
                    run.user_id,
                    run.project_id,
                    "agent_run",
                    run.id,
                    {"request_id": run.request_id},
                )
            db.commit()
            return len(runs)


agent_run_reaper = AgentRunReaper()
