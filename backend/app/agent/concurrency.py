import asyncio
import logging
import time
from contextlib import suppress
from dataclasses import dataclass
from uuid import uuid4

import redis.asyncio as redis_async

from app.core.config import get_settings


settings = get_settings()
logger = logging.getLogger(__name__)
_local_limiters: dict[int, "LocalAgentLimiter"] = {}
_redis_retry_after = 0.0


class AgentBusyError(RuntimeError):
    pass


class LocalAgentLimiter:
    def __init__(self) -> None:
        self.active = 0
        self._condition = asyncio.Condition()

    async def acquire(self, limit: int, timeout: float) -> None:
        async with self._condition:
            await asyncio.wait_for(
                self._condition.wait_for(lambda: self.active < limit),
                timeout=timeout,
            )
            self.active += 1

    async def release(self) -> None:
        async with self._condition:
            self.active = max(0, self.active - 1)
            self._condition.notify_all()


@dataclass
class AgentLease:
    agent_id: int
    token: str
    redis_client: redis_async.Redis | None = None
    local_limiter: LocalAgentLimiter | None = None
    heartbeat_task: asyncio.Task | None = None
    released: bool = False

    def start_heartbeat(self) -> None:
        if self.redis_client and not self.heartbeat_task:
            self.heartbeat_task = asyncio.create_task(
                self._heartbeat(), name=f"agent-lease-{self.agent_id}"
            )

    async def renew(self) -> bool:
        if not self.redis_client or self.released:
            return False
        now_ms = int(time.time() * 1000)
        expires_ms = now_ms + settings.agent_concurrency_lease_seconds * 1000
        renewed = await self.redis_client.eval(
            RENEW_SCRIPT,
            1,
            f"agent:slots:{self.agent_id}",
            expires_ms,
            self.token,
        )
        return renewed == 1

    async def _heartbeat(self) -> None:
        interval = max(1.0, settings.agent_concurrency_lease_seconds / 3)
        while not self.released:
            await asyncio.sleep(interval)
            try:
                if not await self.renew():
                    logger.warning("Agent lease disappeared before release: agent_id=%s", self.agent_id)
                    return
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Agent lease renewal failed: agent_id=%s", self.agent_id)

    async def release(self) -> None:
        if self.released:
            return
        self.released = True
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.heartbeat_task
            self.heartbeat_task = None
        if self.redis_client:
            try:
                await self.redis_client.zrem(f"agent:slots:{self.agent_id}", self.token)
            except Exception:
                logger.exception("Agent lease release failed: agent_id=%s", self.agent_id)
            finally:
                await self.redis_client.aclose()
        if self.local_limiter:
            await self.local_limiter.release()


ACQUIRE_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local expires = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local token = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, '-inf', now)
if redis.call('ZCARD', key) >= limit then
  return 0
end
redis.call('ZADD', key, expires, token)
redis.call('EXPIRE', key, math.ceil((expires - now) / 1000))
return 1
"""

RENEW_SCRIPT = """
local key = KEYS[1]
local expires = tonumber(ARGV[1])
local token = ARGV[2]
if redis.call('ZSCORE', key, token) == false then
  return 0
end
redis.call('ZADD', key, expires, token)
local now = tonumber(redis.call('TIME')[1]) * 1000
redis.call('EXPIRE', key, math.ceil((expires - now) / 1000))
return 1
"""


async def _acquire_redis(agent_id: int, limit: int, token: str) -> AgentLease | None:
    global _redis_retry_after
    if time.monotonic() < _redis_retry_after:
        return None
    client = redis_async.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=0.25,
        socket_timeout=0.5,
    )
    deadline = time.monotonic() + settings.agent_concurrency_acquire_timeout
    try:
        while time.monotonic() < deadline:
            now_ms = int(time.time() * 1000)
            expires_ms = now_ms + settings.agent_concurrency_lease_seconds * 1000
            acquired = await client.eval(
                ACQUIRE_SCRIPT,
                1,
                f"agent:slots:{agent_id}",
                now_ms,
                expires_ms,
                limit,
                token,
            )
            if acquired == 1:
                lease = AgentLease(agent_id=agent_id, token=token, redis_client=client)
                lease.start_heartbeat()
                return lease
            await asyncio.sleep(0.1)
    except Exception:
        _redis_retry_after = time.monotonic() + 10
        await client.aclose()
        return None
    await client.aclose()
    raise AgentBusyError("AI employee is at its concurrency limit")


async def acquire_agent_slot(agent_id: int, limit: int) -> AgentLease:
    normalized_limit = max(1, limit)
    token = str(uuid4())
    redis_lease = await _acquire_redis(agent_id, normalized_limit, token)
    if redis_lease:
        return redis_lease

    limiter = _local_limiters.setdefault(agent_id, LocalAgentLimiter())
    try:
        await limiter.acquire(normalized_limit, settings.agent_concurrency_acquire_timeout)
    except TimeoutError as exc:
        raise AgentBusyError("AI employee is at its concurrency limit") from exc
    return AgentLease(agent_id=agent_id, token=token, local_limiter=limiter)
