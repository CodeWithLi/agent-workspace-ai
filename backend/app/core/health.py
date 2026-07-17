import socket

import httpx
import redis
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import engine
from app.core.llm import get_llm
from app.core.storage import object_storage
from app.rag.vector_store import vector_store


settings = get_settings()


def readiness_components() -> dict[str, str]:
    components: dict[str, str] = {}
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        components["database"] = "ok"
    except Exception:
        components["database"] = "unavailable"
    try:
        redis.from_url(settings.redis_url, socket_connect_timeout=3, socket_timeout=3).ping()
        components["redis"] = "ok"
    except Exception:
        components["redis"] = "unavailable"
    try:
        object_storage._client()
        components["minio"] = "ok"
    except Exception:
        components["minio"] = "fallback" if settings.storage_fallback_enabled else "unavailable"
    vector_store.connected = False
    try:
        components["milvus"] = "ok" if vector_store.connect() else (
            "fallback" if settings.vector_fallback_enabled else "unavailable"
        )
    except Exception:
        components["milvus"] = "unavailable"
    gateway = get_llm()
    if not gateway.api_key:
        components["llm"] = "fallback" if settings.llm_fallback_enabled else "unavailable"
    else:
        try:
            response = httpx.get(
                f"{gateway.base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {gateway.api_key}"},
                timeout=5,
            )
            components["llm"] = "ok" if response.status_code < 500 else "unavailable"
        except Exception:
            components["llm"] = "unavailable"
    if not settings.smtp_host:
        components["smtp"] = "disabled"
    else:
        try:
            with socket.create_connection((settings.smtp_host, settings.smtp_port), timeout=3):
                components["smtp"] = "ok"
        except Exception:
            components["smtp"] = "unavailable"
    return components


def is_ready(components: dict[str, str]) -> bool:
    required = {"database", "redis", "minio", "milvus", "llm"}
    return all(components.get(name) in {"ok", "fallback"} for name in required)
