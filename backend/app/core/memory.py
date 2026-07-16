import json
import logging

import redis
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Memory


logger = logging.getLogger(__name__)
settings = get_settings()


def _redis_client() -> redis.Redis | None:
    try:
        client = redis.from_url(settings.redis_url, decode_responses=True)
        client.ping()
        return client
    except Exception:
        return None


def get_user_preferences(user_id: int) -> dict:
    client = _redis_client()
    if client is None:
        return {}
    raw = client.get(f"user:{user_id}:preferences")
    return json.loads(raw) if raw else {}


def set_user_preference(user_id: int, key: str, value: str) -> None:
    client = _redis_client()
    if client is None:
        logger.info("Redis unavailable, skip long-term memory update")
        return
    data = get_user_preferences(user_id)
    data[key] = value
    client.set(f"user:{user_id}:preferences", json.dumps(data, ensure_ascii=False))


def save_project_memory(
    db: Session,
    user_id: int,
    project_id: int | None,
    agent_id: int | None,
    key: str,
    value: str,
) -> Memory:
    memory = Memory(user_id=user_id, project_id=project_id, agent_id=agent_id, key=key, value=value)
    db.add(memory)
    db.commit()
    db.refresh(memory)
    compact_project_memory(db, user_id, project_id, agent_id)
    return memory


def load_project_memory(db: Session, user_id: int, project_id: int | None, limit: int = 8) -> list[Memory]:
    stmt = select(Memory).where(Memory.user_id == user_id)
    if project_id:
        stmt = stmt.where(Memory.project_id == project_id)
    return list(db.scalars(stmt.order_by(Memory.created_at.desc()).limit(limit)))


def compact_project_memory(
    db: Session,
    user_id: int,
    project_id: int | None,
    agent_id: int | None,
    keep_latest: int = 12,
) -> None:
    if project_id is None:
        return
    stmt = (
        select(Memory)
        .where(Memory.user_id == user_id, Memory.project_id == project_id)
        .order_by(Memory.created_at.desc(), Memory.id.desc())
    )
    if agent_id:
        stmt = stmt.where(Memory.agent_id == agent_id)
    memories = list(db.scalars(stmt))
    summaries = [item for item in memories if item.memory_type == "summary" and item.key == "compressed_history"]
    regular = [item for item in memories if item not in summaries]
    if len(regular) <= keep_latest and len(summaries) <= 1:
        return

    overflow = regular[keep_latest:]
    summary_parts = [item.value for item in summaries[:1]]
    summary_parts.extend(f"- {item.key}: {item.value[:220]}" for item in reversed(overflow[:20]))
    delete_ids = [item.id for item in overflow + summaries]
    if delete_ids:
        db.execute(delete(Memory).where(Memory.id.in_(delete_ids)))
    merged_summary = "\n".join(summary_parts)[-4000:]
    if merged_summary:
        db.add(
            Memory(
                user_id=user_id,
                project_id=project_id,
                agent_id=agent_id,
                memory_type="summary",
                key="compressed_history",
                value=merged_summary,
            )
        )
    db.commit()
