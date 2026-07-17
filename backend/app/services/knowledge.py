import asyncio
import logging
from datetime import datetime, timedelta, timezone
from time import perf_counter

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.metrics import RAG_INDEX_CHUNKS, RAG_INDEX_DURATION
from app.models import KnowledgeDocument
from app.rag.service import index_stored_document


logger = logging.getLogger(__name__)
settings = get_settings()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def claim_document(db: Session) -> int | None:
    cutoff = utc_now() - timedelta(seconds=settings.knowledge_lease_seconds)
    document = db.scalar(
        select(KnowledgeDocument)
        .where(
            or_(
                KnowledgeDocument.status == "QUEUED",
                (KnowledgeDocument.status == "INDEXING")
                & (or_(KnowledgeDocument.locked_at.is_(None), KnowledgeDocument.locked_at <= cutoff)),
            )
        )
        .order_by(KnowledgeDocument.created_at, KnowledgeDocument.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if not document:
        return None
    document.status = "INDEXING"
    document.locked_at = utc_now()
    document.attempts += 1
    document.error = ""
    db.commit()
    return document.id


async def process_document(db: Session, document_id: int, *, claimed: bool = False) -> KnowledgeDocument:
    document = db.get(KnowledgeDocument, document_id)
    if not document:
        raise LookupError("Knowledge document not found")
    if not claimed:
        if document.status != "QUEUED":
            return document
        document.status = "INDEXING"
        document.locked_at = utc_now()
        document.attempts += 1
        document.error = ""
        db.commit()
    try:
        started = perf_counter()
        await index_stored_document(db, document)
        RAG_INDEX_DURATION.labels(
            document.parser_name or "unknown",
            document.chunker_name or "unknown",
            "success",
        ).observe(perf_counter() - started)
        RAG_INDEX_CHUNKS.observe(document.chunk_count)
        record_audit(
            db,
            "knowledge.indexed",
            document.owner_id,
            document.project_id,
            "document",
            document.id,
            {
                "chunks": document.chunk_count,
                "document_version": document.version,
                "index_version": document.active_index_version,
            },
        )
        db.commit()
        db.refresh(document)
        return document
    except Exception as exc:
        RAG_INDEX_DURATION.labels(
            document.parser_name or "unknown",
            document.chunker_name or "unknown",
            "failed",
        ).observe(perf_counter() - started)
        db.rollback()
        document = db.get(KnowledgeDocument, document_id)
        document.locked_at = None
        document.error = str(exc)[:2000]
        if document.attempts < document.max_attempts:
            document.status = "QUEUED"
        else:
            document.status = "FAILED"
            record_audit(
                db,
                "knowledge.failed",
                document.owner_id,
                document.project_id,
                "document",
                document.id,
                {"attempts": document.attempts, "error": document.error},
            )
        db.commit()
        logger.exception("Knowledge document %s indexing failed", document_id)
        return document


class KnowledgeDispatcher:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if not settings.knowledge_worker_enabled or self._task:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="knowledge-dispatcher")
        logger.info("Knowledge dispatcher started")

    async def stop(self) -> None:
        if not self._task:
            return
        self._stop.set()
        await self._task
        self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                processed = await self.dispatch_once()
            except Exception:
                processed = False
                logger.exception("Knowledge dispatcher iteration failed")
            if processed:
                continue
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=settings.knowledge_poll_seconds)
            except TimeoutError:
                pass

    async def dispatch_once(self) -> bool:
        with SessionLocal() as db:
            document_id = claim_document(db)
            if document_id is None:
                return False
            await process_document(db, document_id, claimed=True)
            return True


knowledge_dispatcher = KnowledgeDispatcher()
