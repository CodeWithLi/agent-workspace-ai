from __future__ import annotations

import time

import redis
from fastapi import HTTPException, Request, status

from app.core.config import get_settings


settings = get_settings()
_memory_bucket: dict[str, list[float]] = {}


def _client() -> redis.Redis | None:
    try:
        client = redis.from_url(settings.redis_url, decode_responses=True)
        client.ping()
        return client
    except Exception:
        return None


def check_rate_limit(key: str, limit: int = 8, window_seconds: int = 60) -> None:
    now = time.time()
    client = _client()
    if client:
        redis_key = f"rate:{key}"
        count = client.incr(redis_key)
        if count == 1:
            client.expire(redis_key, window_seconds)
        if count > limit:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many attempts")
        return

    bucket = [ts for ts in _memory_bucket.get(key, []) if now - ts < window_seconds]
    bucket.append(now)
    _memory_bucket[key] = bucket
    if len(bucket) > limit:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many attempts")


def login_rate_limit_key(request: Request, email: str) -> str:
    client_host = request.client.host if request.client else "unknown"
    return f"login:{client_host}:{email.lower()}"
