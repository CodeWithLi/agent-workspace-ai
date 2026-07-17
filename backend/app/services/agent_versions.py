from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Agent, AgentPromptVersion


VERSION_FIELDS = (
    "description",
    "system_prompt",
    "model",
    "memory_enable",
    "knowledge_access",
    "human_approval_required",
    "concurrency_limit",
)


def ensure_initial_agent_version(db: Session, agent: Agent) -> AgentPromptVersion:
    existing = db.scalar(
        select(AgentPromptVersion).where(
            AgentPromptVersion.agent_id == agent.id,
            AgentPromptVersion.version == 1,
        )
    )
    if existing:
        return existing
    version = AgentPromptVersion(
        agent_id=agent.id,
        version=1,
        status="PUBLISHED",
        release_note="Initial version",
        published_at=datetime.now(timezone.utc),
        **{field: getattr(agent, field) for field in VERSION_FIELDS},
    )
    agent.current_version = 1
    db.add(version)
    db.flush()
    return version


def next_agent_version(db: Session, agent_id: int) -> int:
    return (db.scalar(select(func.max(AgentPromptVersion.version)).where(AgentPromptVersion.agent_id == agent_id)) or 0) + 1


def create_version(
    db: Session,
    agent: Agent,
    values: dict,
    user_id: int,
    *,
    status: str = "DRAFT",
    release_note: str = "",
) -> AgentPromptVersion:
    version = AgentPromptVersion(
        agent_id=agent.id,
        version=next_agent_version(db, agent.id),
        status=status,
        release_note=release_note,
        created_by_user_id=user_id,
        published_at=datetime.now(timezone.utc) if status == "PUBLISHED" else None,
        **{field: values[field] for field in VERSION_FIELDS},
    )
    db.add(version)
    db.flush()
    if status == "PUBLISHED":
        activate_version(db, agent, version)
    return version


def activate_version(db: Session, agent: Agent, version: AgentPromptVersion) -> AgentPromptVersion:
    published = list(
        db.scalars(
            select(AgentPromptVersion).where(
                AgentPromptVersion.agent_id == agent.id,
                AgentPromptVersion.status == "PUBLISHED",
                AgentPromptVersion.id != version.id,
            )
        )
    )
    for item in published:
        item.status = "ARCHIVED"
    for field in VERSION_FIELDS:
        setattr(agent, field, getattr(version, field))
    version.status = "PUBLISHED"
    version.published_at = datetime.now(timezone.utc)
    agent.current_version = version.version
    db.flush()
    return version


def rollback_to_version(db: Session, agent: Agent, target: AgentPromptVersion, user_id: int) -> AgentPromptVersion:
    values = {field: getattr(target, field) for field in VERSION_FIELDS}
    return create_version(
        db,
        agent,
        values,
        user_id,
        status="PUBLISHED",
        release_note=f"Rollback to version {target.version}",
    )
