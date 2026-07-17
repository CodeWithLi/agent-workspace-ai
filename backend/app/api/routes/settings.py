import asyncio
import smtplib

import redis
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.audit import record_audit
from app.core.config import get_settings
from app.core.database import get_db
from app.core.llm import get_llm
from app.core.runtime_config import apply_runtime_settings, runtime_setting_items, update_runtime_settings
from app.core.storage import object_storage
from app.models import User
from app.rag.advanced_parser import docling_parser
from app.rag.reranker import reranker
from app.rag.vector_store import vector_store
from app.schemas import (
    SettingCollectionOut,
    SettingConnectionTestOut,
    SettingConnectionTestRequest,
    SettingUpdate,
)


router = APIRouter()
settings = get_settings()


def collection(db: Session) -> SettingCollectionOut:
    return SettingCollectionOut(environment=settings.environment, items=runtime_setting_items(db))


@router.get("", response_model=SettingCollectionOut)
def get_system_settings(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SettingCollectionOut:
    return collection(db)


@router.patch("", response_model=SettingCollectionOut)
def update_system_settings(
    payload: SettingUpdate,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SettingCollectionOut:
    try:
        changed = update_runtime_settings(db, payload.values, current_user.id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if changed:
        record_audit(
            db,
            "settings.update",
            current_user.id,
            resource_type="system_settings",
            details={"keys": changed},
            request=request,
        )
    db.commit()
    return collection(db)


def _smtp_connection() -> None:
    if not settings.smtp_host:
        raise RuntimeError("SMTP host is not configured")
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as client:
        if settings.smtp_starttls:
            client.starttls()
        if settings.smtp_username:
            client.login(settings.smtp_username, settings.smtp_password or "")
        client.noop()


@router.post("/test-connection", response_model=SettingConnectionTestOut)
async def test_system_connection(
    payload: SettingConnectionTestRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SettingConnectionTestOut:
    apply_runtime_settings(db)
    try:
        if payload.target == "llm":
            gateway = get_llm()
            if not getattr(gateway, "api_key", None):
                raise RuntimeError("LLM API key is not configured")
            await gateway.chat("Reply with OK only.", "Connection test")
        elif payload.target == "embedding":
            gateway = get_llm()
            if not settings.embedding_api_key and not getattr(gateway, "api_key", None):
                raise RuntimeError("Embedding API key is not configured")
            vector = await gateway.embed("Connection test")
            if not vector:
                raise RuntimeError("Embedding provider returned an empty vector")
        elif payload.target == "reranker":
            await reranker.healthcheck()
        elif payload.target == "docling":
            await docling_parser.healthcheck()
        elif payload.target == "redis":
            await asyncio.to_thread(redis.from_url(settings.redis_url).ping)
        elif payload.target == "milvus":
            vector_store.connected = False
            if not await asyncio.to_thread(vector_store.connect):
                raise RuntimeError("Milvus connection failed")
        elif payload.target == "minio":
            await asyncio.to_thread(object_storage._client)
        elif payload.target == "smtp":
            await asyncio.to_thread(_smtp_connection)
        message = f"{payload.target} connection succeeded"
        ok = True
    except Exception as exc:
        message = str(exc)[:500] or f"{payload.target} connection failed"
        ok = False
    record_audit(
        db,
        "settings.connection_test",
        current_user.id,
        resource_type="system_settings",
        resource_id=payload.target,
        details={"ok": ok},
    )
    db.commit()
    return SettingConnectionTestOut(target=payload.target, ok=ok, message=message)
