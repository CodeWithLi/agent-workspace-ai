from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import AgentRun
from app.services.billing import refund_consumption


def complete_agent_run(db: Session, run_id: int, conversation_id: int) -> None:
    run = db.get(AgentRun, run_id)
    if not run or run.status != "RUNNING":
        return
    run.status = "COMPLETED"
    run.conversation_id = conversation_id
    run.finished_at = datetime.now(timezone.utc)
    db.commit()


def fail_agent_run(db: Session, run_id: int, billing_transaction_id: int | None, error: str) -> None:
    run = db.get(AgentRun, run_id)
    should_refund = bool(run and run.status == "RUNNING")
    if run and run.status == "RUNNING":
        run.status = "FAILED"
        run.error = error[:1000]
        run.finished_at = datetime.now(timezone.utc)
    if billing_transaction_id and should_refund:
        refund_consumption(db, billing_transaction_id, "Agent execution failed")
    db.commit()
