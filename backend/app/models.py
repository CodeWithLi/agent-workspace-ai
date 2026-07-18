from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum as SqlEnum, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class UserRole(str, Enum):
    admin = "admin"
    member = "member"


class AgentRole(str, Enum):
    product_manager = "product_manager"
    project_manager = "project_manager"
    architect = "architect"
    test_engineer = "test_engineer"
    meeting_summarizer = "meeting_summarizer"
    knowledge_admin = "knowledge_admin"
    notification_secretary = "notification_secretary"
    operations_analyst = "operations_analyst"


class ProjectMemberRole(str, Enum):
    owner = "owner"
    editor = "editor"
    viewer = "viewer"


class TaskStatus(str, Enum):
    todo = "TODO"
    running = "RUNNING"
    done = "DONE"
    failed = "FAILED"


class WorkflowStatus(str, Enum):
    queued = "QUEUED"
    running = "RUNNING"
    cancelling = "CANCELLING"
    compensating = "COMPENSATING"
    compensation_failed = "COMPENSATION_FAILED"
    cancelled = "CANCELLED"
    paused = "PAUSED"
    completed = "COMPLETED"
    failed = "FAILED"


class SagaStepStatus(str, Enum):
    pending = "PENDING"
    executing = "EXECUTING"
    completed = "COMPLETED"
    failed = "FAILED"
    compensating = "COMPENSATING"
    compensated = "COMPENSATED"
    compensation_failed = "COMPENSATION_FAILED"


class PrototypeGenerationOperation(str, Enum):
    create = "CREATE"
    regenerate = "REGENERATE"


class PrototypeGenerationStatus(str, Enum):
    queued = "QUEUED"
    running = "RUNNING"
    succeeded = "SUCCEEDED"
    failed = "FAILED"
    cancelling = "CANCELLING"
    cancelled = "CANCELLED"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(SqlEnum(UserRole), default=UserRole.member)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    permissions: Mapped[str] = mapped_column(Text, default="")
    ai_token_balance: Mapped[int] = mapped_column(Integer, default=1000)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    projects: Mapped[list["Project"]] = relationship(back_populates="owner")
    project_memberships: Mapped[list["ProjectMember"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    sessions: Mapped[list["UserSession"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    refresh_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_address: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="sessions")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    members: Mapped[str] = mapped_column(Text, default="")
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    owner: Mapped[User] = relationship(back_populates="projects")
    tasks: Mapped[list["Task"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="project")
    documents: Mapped[list["KnowledgeDocument"]] = relationship(back_populates="project")
    meetings: Mapped[list["Meeting"]] = relationship(back_populates="project")
    reports: Mapped[list["Report"]] = relationship(back_populates="project")
    notifications: Mapped[list["Notification"]] = relationship(back_populates="project")
    workflows: Mapped[list["WorkflowRun"]] = relationship(back_populates="project")
    requirements: Mapped[list["Requirement"]] = relationship(back_populates="project")
    prototypes: Mapped[list["ProductPrototype"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    member_links: Mapped[list["ProjectMember"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_member"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[ProjectMemberRole] = mapped_column(
        SqlEnum(ProjectMemberRole, values_callable=lambda enum: [item.value for item in enum], native_enum=False),
        default=ProjectMemberRole.viewer,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="member_links")
    user: Mapped[User] = relationship(back_populates="project_memberships")


class Requirement(Base):
    __tablename__ = "requirements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="NEW")
    analysis: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    project: Mapped[Project | None] = relationship(back_populates="requirements")
    prototypes: Mapped[list["ProductPrototype"]] = relationship(back_populates="requirement")


class ProductPrototype(Base):
    __tablename__ = "product_prototypes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    requirement_id: Mapped[int | None] = mapped_column(
        ForeignKey("requirements.id", ondelete="SET NULL"), index=True
    )
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    active_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped[Project] = relationship(back_populates="prototypes")
    requirement: Mapped[Requirement | None] = relationship(back_populates="prototypes")
    versions: Mapped[list["ProductPrototypeVersion"]] = relationship(
        back_populates="prototype", cascade="all, delete-orphan", order_by="ProductPrototypeVersion.version"
    )
    review_comments: Mapped[list["PrototypeReviewComment"]] = relationship(
        back_populates="prototype", cascade="all, delete-orphan"
    )
    test_cases: Mapped[list["PrototypeTestCase"]] = relationship(
        back_populates="prototype", cascade="all, delete-orphan"
    )
    materializations: Mapped[list["ProductPrototypeMaterialization"]] = relationship(
        back_populates="prototype", cascade="all, delete-orphan"
    )


class ProductPrototypeVersion(Base):
    __tablename__ = "product_prototype_versions"
    __table_args__ = (
        UniqueConstraint("prototype_id", "version", name="uq_product_prototype_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    prototype_id: Mapped[int] = mapped_column(
        ForeignKey("product_prototypes.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    source_prompt: Mapped[str] = mapped_column(Text)
    specification_json: Mapped[str] = mapped_column(Text)
    agent_trace_json: Mapped[str] = mapped_column(Text, default="[]")
    quality_json: Mapped[str] = mapped_column(Text, default="{}")
    generation_mode: Mapped[str] = mapped_column(String(30), default="MULTI_AGENT")
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    prototype: Mapped[ProductPrototype] = relationship(back_populates="versions")


class PrototypeGenerationJob(Base):
    __tablename__ = "prototype_generation_jobs"
    __table_args__ = (
        CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="ck_prototype_generation_progress_percent",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_prototype_generation_attempt_count"),
        CheckConstraint("max_attempts > 0", name="ck_prototype_generation_max_attempts"),
        CheckConstraint("target_version > 0", name="ck_prototype_generation_target_version"),
        Index("ix_prototype_generation_jobs_queue", "status", "next_attempt_at", "created_at"),
        Index(
            "uq_prototype_generation_active_target_version",
            "prototype_id",
            "target_version",
            unique=True,
            postgresql_where=text(
                "prototype_id IS NOT NULL AND status IN ('QUEUED','RUNNING','CANCELLING')"
            ),
            sqlite_where=text(
                "prototype_id IS NOT NULL AND status IN ('QUEUED','RUNNING','CANCELLING')"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    request_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    request_payload_hash: Mapped[str] = mapped_column(String(64))
    operation: Mapped[PrototypeGenerationOperation] = mapped_column(
        SqlEnum(
            PrototypeGenerationOperation,
            values_callable=lambda enum: [item.value for item in enum],
            native_enum=False,
        ),
        index=True,
    )
    status: Mapped[PrototypeGenerationStatus] = mapped_column(
        SqlEnum(
            PrototypeGenerationStatus,
            values_callable=lambda enum: [item.value for item in enum],
            native_enum=False,
        ),
        default=PrototypeGenerationStatus.queued,
        index=True,
    )
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    requirement_id: Mapped[int | None] = mapped_column(ForeignKey("requirements.id", ondelete="SET NULL"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    prototype_id: Mapped[int | None] = mapped_column(ForeignKey("product_prototypes.id", ondelete="SET NULL"), index=True)
    base_version: Mapped[int | None] = mapped_column(Integer)
    target_version: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(200))
    source_prompt: Mapped[str] = mapped_column(Text)
    requirement_snapshot_json: Mapped[str] = mapped_column(Text, default="null")
    agent_snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    state_json: Mapped[str] = mapped_column(Text, default="{}")
    stage: Mapped[str] = mapped_column(String(100), default="queued")
    stage_history_json: Mapped[str] = mapped_column(Text, default="[]")
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    latest_event_id: Mapped[int | None] = mapped_column(Integer)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    lease_token: Mapped[str | None] = mapped_column(String(64), index=True)
    error_code: Mapped[str] = mapped_column(String(100), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_prototype_id: Mapped[int | None] = mapped_column(ForeignKey("product_prototypes.id", ondelete="SET NULL"), index=True)
    result_version: Mapped[int | None] = mapped_column(Integer)
    result_version_id: Mapped[int | None] = mapped_column(ForeignKey("product_prototype_versions.id", ondelete="SET NULL"), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    events: Mapped[list["PrototypeGenerationEvent"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class PrototypeGenerationEvent(Base):
    __tablename__ = "prototype_generation_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("prototype_generation_jobs.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(100), default="")
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    message: Mapped[str] = mapped_column(String(500), default="")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    job: Mapped[PrototypeGenerationJob] = relationship(back_populates="events")


class PrototypeReviewComment(Base):
    __tablename__ = "prototype_review_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    prototype_id: Mapped[int] = mapped_column(
        ForeignKey("product_prototypes.id", ondelete="CASCADE"), index=True
    )
    prototype_version: Mapped[int] = mapped_column(Integer, index=True)
    screen_id: Mapped[str | None] = mapped_column(String(64), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="OPEN", index=True)
    resolved_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    prototype: Mapped[ProductPrototype] = relationship(back_populates="review_comments")


class PrototypeTestCase(Base):
    __tablename__ = "prototype_test_cases"
    __table_args__ = (
        UniqueConstraint(
            "prototype_id",
            "prototype_version",
            "case_key",
            name="uq_prototype_test_case_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    prototype_id: Mapped[int] = mapped_column(
        ForeignKey("product_prototypes.id", ondelete="CASCADE"), index=True
    )
    prototype_version: Mapped[int] = mapped_column(Integer, index=True)
    screen_id: Mapped[str] = mapped_column(String(64), index=True)
    case_key: Mapped[str] = mapped_column(String(150))
    title: Mapped[str] = mapped_column(String(200))
    preconditions: Mapped[str] = mapped_column(Text, default="")
    steps_json: Mapped[str] = mapped_column(Text, default="[]")
    expected_result: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(30), default="MEDIUM")
    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    prototype: Mapped[ProductPrototype] = relationship(back_populates="test_cases")


class ProductPrototypeMaterialization(Base):
    __tablename__ = "product_prototype_materializations"
    __table_args__ = (
        UniqueConstraint(
            "prototype_id",
            "prototype_version",
            name="uq_product_prototype_materialization_version",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    prototype_id: Mapped[int] = mapped_column(
        ForeignKey("product_prototypes.id", ondelete="CASCADE"), index=True
    )
    prototype_version: Mapped[int] = mapped_column(Integer)
    request_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    task_count: Mapped[int] = mapped_column(Integer, default=0)
    test_case_count: Mapped[int] = mapped_column(Integer, default=0)
    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    prototype: Mapped[ProductPrototype] = relationship(back_populates="materializations")


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    role: Mapped[AgentRole] = mapped_column(SqlEnum(AgentRole), unique=True)
    description: Mapped[str] = mapped_column(Text)
    system_prompt: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(100), default="glm-4-flash")
    tools: Mapped[str] = mapped_column(String(500), default="")
    memory_enable: Mapped[bool] = mapped_column(Boolean, default=True)
    knowledge_access: Mapped[bool] = mapped_column(Boolean, default=True)
    human_approval_required: Mapped[bool] = mapped_column(Boolean, default=False)
    concurrency_limit: Mapped[int] = mapped_column(Integer, default=4)
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversations: Mapped[list["Conversation"]] = relationship(back_populates="agent")
    tool_links: Mapped[list["AgentTool"]] = relationship(back_populates="agent", cascade="all, delete-orphan")


class AgentAction(Base):
    __tablename__ = "agent_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"), index=True)
    tool_name: Mapped[str] = mapped_column(String(100))
    input_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(30), default="PENDING", index=True)
    approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    request_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"), index=True)
    billing_transaction_id: Mapped[int | None] = mapped_column(ForeignKey("token_transactions.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(30), default="RUNNING", index=True)
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentTool(Base):
    __tablename__ = "agent_tools"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    allowed_roles: Mapped[str] = mapped_column(String(200), default="admin,member")

    agent: Mapped[Agent] = relationship(back_populates="tool_links")


class AgentPromptVersion(Base):
    __tablename__ = "agent_prompt_versions"
    __table_args__ = (UniqueConstraint("agent_id", "version", name="uq_agent_prompt_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    description: Mapped[str] = mapped_column(Text)
    system_prompt: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(100))
    memory_enable: Mapped[bool] = mapped_column(Boolean, default=True)
    knowledge_access: Mapped[bool] = mapped_column(Boolean, default=True)
    human_approval_required: Mapped[bool] = mapped_column(Boolean, default=False)
    concurrency_limit: Mapped[int] = mapped_column(Integer, default=4)
    release_note: Mapped[str] = mapped_column(String(500), default="")
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(200), default="New conversation")
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    mode: Mapped[str] = mapped_column(String(20), default="SINGLE", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project | None] = relationship(back_populates="conversations")
    agent: Mapped[Agent] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"), index=True)
    role: Mapped[str] = mapped_column(String(30))
    stage: Mapped[str] = mapped_column(String(30), default="answer")
    content: Mapped[str] = mapped_column(Text)
    tool_calls: Mapped[str] = mapped_column(Text, default="[]")
    thinking: Mapped[str] = mapped_column(Text, default="")
    parent_message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"), index=True)
    regenerated_from_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class MessageFeedback(Base):
    __tablename__ = "message_feedback"
    __table_args__ = (UniqueConstraint("message_id", "user_id", name="uq_message_feedback_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "source_prototype_id",
            "source_prototype_version",
            "source_screen_id",
            name="uq_task_prototype_screen",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str] = mapped_column(String(30), default="MEDIUM")
    status: Mapped[TaskStatus] = mapped_column(
        SqlEnum(TaskStatus, values_callable=lambda enum: [item.value for item in enum], native_enum=False),
        default=TaskStatus.todo,
    )
    assignee_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    assignee_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    due_date: Mapped[str] = mapped_column(String(50), default="")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    source_prototype_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_prototypes.id", ondelete="SET NULL"), index=True
    )
    source_prototype_version: Mapped[int | None] = mapped_column(Integer)
    source_screen_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    project: Mapped[Project] = relationship(back_populates="tasks")


class TaskComment(Base):
    __tablename__ = "task_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeDocument(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100), default="application/octet-stream")
    storage_path: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(30), default="QUEUED", index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    dedup_key: Mapped[str | None] = mapped_column(String(150), unique=True, index=True)
    source_label: Mapped[str] = mapped_column(String(100), default="upload")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    version: Mapped[int] = mapped_column(Integer, default=1)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    error: Mapped[str] = mapped_column(Text, default="")
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active_index_version: Mapped[int] = mapped_column(Integer, default=0, index=True)
    pending_index_version: Mapped[int | None] = mapped_column(Integer)
    parser_name: Mapped[str] = mapped_column(String(100), default="")
    parser_version: Mapped[str] = mapped_column(String(50), default="")
    chunker_name: Mapped[str] = mapped_column(String(100), default="")
    chunker_version: Mapped[str] = mapped_column(String(50), default="")
    element_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    index_config_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    project: Mapped[Project | None] = relationship(back_populates="documents")
    chunks: Mapped[list["Embedding"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    elements: Mapped[list["KnowledgeElement"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    index_versions: Mapped[list["KnowledgeIndexVersion"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class KnowledgeIndexVersion(Base):
    __tablename__ = "document_index_versions"
    __table_args__ = (UniqueConstraint("document_id", "version", name="uq_document_index_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="STAGING", index=True)
    parser_name: Mapped[str] = mapped_column(String(100), default="")
    parser_version: Mapped[str] = mapped_column(String(50), default="")
    chunker_name: Mapped[str] = mapped_column(String(100), default="")
    chunker_version: Mapped[str] = mapped_column(String(50), default="")
    embedding_model: Mapped[str] = mapped_column(String(100), default="")
    embedding_dimensions: Mapped[int] = mapped_column(Integer, default=0)
    element_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str] = mapped_column(Text, default="")
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    document: Mapped[KnowledgeDocument] = relationship(back_populates="index_versions")


class KnowledgeElement(Base):
    __tablename__ = "document_elements"
    __table_args__ = (
        UniqueConstraint("document_id", "index_version", "element_index", name="uq_document_element_version_index"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    index_version: Mapped[int] = mapped_column(Integer, index=True)
    stable_id: Mapped[str] = mapped_column(String(64), index=True)
    element_index: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(30), index=True)
    content: Mapped[str] = mapped_column(Text)
    heading_path_json: Mapped[str] = mapped_column(Text, default="[]")
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    char_start: Mapped[int] = mapped_column(Integer, default=0)
    char_end: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped[KnowledgeDocument] = relationship(back_populates="elements")


class Embedding(Base):
    __tablename__ = "embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    content: Mapped[str] = mapped_column(Text)
    chunk_index: Mapped[int] = mapped_column(Integer)
    vector_id: Mapped[str | None] = mapped_column(String(100))
    vector_json: Mapped[str] = mapped_column(Text, default="[]")
    parent_vector_json: Mapped[str] = mapped_column(Text, default="[]")
    score_hint: Mapped[float] = mapped_column(Float, default=0.0)
    stable_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    index_version: Mapped[int] = mapped_column(Integer, default=0, index=True)
    parent_stable_id: Mapped[str] = mapped_column(String(64), default="")
    parent_content: Mapped[str] = mapped_column(Text, default="")
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    heading_path_json: Mapped[str] = mapped_column(Text, default="[]")
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    element_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped[KnowledgeDocument] = relationship(back_populates="chunks")


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    transcript: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, default="")
    action_items: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    project: Mapped[Project | None] = relationship(back_populates="meetings")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    report_type: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    project: Mapped[Project] = relationship(back_populates="reports")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    recipient_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    recipient_email: Mapped[str] = mapped_column(String(255), default="")
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(String(50), default="email")
    schedule_at: Mapped[str] = mapped_column(String(50), default="")
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project | None] = relationship(back_populates="notifications")


class Memory(Base):
    __tablename__ = "memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    memory_type: Mapped[str] = mapped_column(String(30), default="project")
    key: Mapped[str] = mapped_column(String(100))
    value: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    status: Mapped[WorkflowStatus] = mapped_column(
        SqlEnum(WorkflowStatus, values_callable=lambda enum: [item.value for item in enum], native_enum=False),
        default=WorkflowStatus.queued,
    )
    current_node: Mapped[str] = mapped_column(String(100), default="requirement")
    state_json: Mapped[str] = mapped_column(Text, default="{}")
    human_feedback: Mapped[str] = mapped_column(Text, default="")
    request_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    billing_transaction_id: Mapped[int | None] = mapped_column(ForeignKey("token_transactions.id", ondelete="SET NULL"))
    pause_before_report: Mapped[bool] = mapped_column(Boolean, default=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    error: Mapped[str] = mapped_column(Text, default="")
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    lease_token: Mapped[str | None] = mapped_column(String(64), index=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    project: Mapped[Project] = relationship(back_populates="workflows")
    events: Mapped[list["WorkflowEvent"]] = relationship(back_populates="workflow", cascade="all, delete-orphan")
    saga_steps: Mapped[list["WorkflowSagaStep"]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan"
    )


class WorkflowEvent(Base):
    __tablename__ = "workflow_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True)
    node: Mapped[str] = mapped_column(String(100), default="")
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    message: Mapped[str] = mapped_column(String(500), default="")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    workflow: Mapped[WorkflowRun] = relationship(back_populates="events")


class WorkflowSagaStep(Base):
    __tablename__ = "workflow_saga_steps"
    __table_args__ = (
        UniqueConstraint("workflow_id", "idempotency_key", name="uq_workflow_saga_step_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer, index=True)
    node: Mapped[str] = mapped_column(String(100), index=True)
    tool_name: Mapped[str] = mapped_column(String(100), index=True)
    compensation_action: Mapped[str] = mapped_column(String(100))
    idempotency_key: Mapped[str] = mapped_column(String(150))
    status: Mapped[SagaStepStatus] = mapped_column(
        SqlEnum(SagaStepStatus, values_callable=lambda enum: [item.value for item in enum], native_enum=False),
        default=SagaStepStatus.pending,
        index=True,
    )
    input_json: Mapped[str] = mapped_column(Text, default="{}")
    output_json: Mapped[str] = mapped_column(Text, default="{}")
    transition_log_json: Mapped[str] = mapped_column(Text, default="[]")
    execute_attempts: Mapped[int] = mapped_column(Integer, default=0)
    compensation_attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    compensated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    workflow: Mapped[WorkflowRun] = relationship(back_populates="saga_steps")


class WorkflowArtifactPublication(Base):
    __tablename__ = "workflow_artifact_publications"
    __table_args__ = (
        UniqueConstraint("workflow_id", "document_type", "target", name="uq_workflow_artifact_target"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True)
    document_type: Mapped[str] = mapped_column(String(50))
    target: Mapped[str] = mapped_column(String(30))
    report_id: Mapped[int | None] = mapped_column(ForeignKey("reports.id", ondelete="SET NULL"))
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    request_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SystemSettingOverride(Base):
    __tablename__ = "system_setting_overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    value_json: Mapped[str] = mapped_column(Text)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TokenTransaction(Base):
    __tablename__ = "token_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    amount: Mapped[int] = mapped_column(Integer)
    balance_after: Mapped[int] = mapped_column(Integer)
    transaction_type: Mapped[str] = mapped_column(String(30), index=True)
    reference_type: Mapped[str] = mapped_column(String(50), default="")
    reference_id: Mapped[str] = mapped_column(String(100), default="")
    idempotency_key: Mapped[str | None] = mapped_column(String(150), unique=True, index=True)
    description: Mapped[str] = mapped_column(String(300), default="")
    operator_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class LLMUsage(Base):
    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"), index=True)
    workflow_id: Mapped[int | None] = mapped_column(ForeignKey("workflow_runs.id", ondelete="SET NULL"), index=True)
    agent_run_id: Mapped[int | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"), index=True)
    operation: Mapped[str] = mapped_column(String(30), index=True)
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_micros: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    usage_source: Mapped[str] = mapped_column(String(30), default="provider")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class EvaluationCase(Base):
    __tablename__ = "evaluation_cases"
    __table_args__ = (
        CheckConstraint("minimum_score >= 0 AND minimum_score <= 1", name="ck_evaluation_case_minimum_score"),
        CheckConstraint("weight > 0", name="ck_evaluation_case_weight"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    agent_role: Mapped[str] = mapped_column(String(50), index=True)
    input_text: Mapped[str] = mapped_column(Text)
    expected_keywords_json: Mapped[str] = mapped_column(Text, default="[]")
    forbidden_keywords_json: Mapped[str] = mapped_column(Text, default="[]")
    rubric: Mapped[str] = mapped_column(Text, default="")
    minimum_score: Mapped[float] = mapped_column(Float, default=0.8)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class EvaluationSuiteRevision(Base):
    __tablename__ = "evaluation_suite_revisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    version: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    cases_snapshot_json: Mapped[str] = mapped_column(Text, default="[]")
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    __table_args__ = (
        CheckConstraint("completed_cases >= 0", name="ck_evaluation_run_completed_cases"),
        CheckConstraint("attempt_count >= 0", name="ck_evaluation_run_attempt_count"),
        CheckConstraint("max_attempts > 0", name="ck_evaluation_run_max_attempts"),
        Index("ix_evaluation_runs_queue", "status", "next_attempt_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    request_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    request_payload_hash: Mapped[str] = mapped_column(String(64), default="")
    suite_revision_id: Mapped[int | None] = mapped_column(
        ForeignKey("evaluation_suite_revisions.id", ondelete="SET NULL"), index=True
    )
    baseline_run_id: Mapped[int | None] = mapped_column(ForeignKey("evaluation_runs.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="QUEUED", index=True)
    total_cases: Mapped[int] = mapped_column(Integer, default=0)
    completed_cases: Mapped[int] = mapped_column(Integer, default=0)
    passed_cases: Mapped[int] = mapped_column(Integer, default=0)
    average_score: Mapped[float] = mapped_column(Float, default=0.0)
    baseline_average_score: Mapped[float | None] = mapped_column(Float)
    score_delta: Mapped[float | None] = mapped_column(Float)
    gate_passed: Mapped[bool | None] = mapped_column(Boolean)
    gate_failures_json: Mapped[str] = mapped_column(Text, default="[]")
    dimension_averages_json: Mapped[str] = mapped_column(Text, default="{}")
    baseline_dimension_averages_json: Mapped[str] = mapped_column(Text, default="{}")
    agent_snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str] = mapped_column(Text, default="")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    lease_token: Mapped[str | None] = mapped_column(String(64), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"
    __table_args__ = (
        UniqueConstraint("run_id", "case_id", name="uq_evaluation_run_case"),
        CheckConstraint("latency_ms >= 0", name="ck_evaluation_result_latency_ms"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("evaluation_runs.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("evaluation_cases.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    baseline_result_id: Mapped[int | None] = mapped_column(ForeignKey("evaluation_results.id", ondelete="SET NULL"))
    case_snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    agent_snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    answer: Mapped[str] = mapped_column(Text, default="")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    baseline_answer: Mapped[str] = mapped_column(Text, default="")
    baseline_score: Mapped[float | None] = mapped_column(Float)
    score_delta: Mapped[float | None] = mapped_column(Float)
    dimension_scores_json: Mapped[str] = mapped_column(Text, default="{}")
    baseline_dimension_scores_json: Mapped[str] = mapped_column(Text, default="{}")
    score_source: Mapped[str] = mapped_column(String(30), default="deterministic_fallback")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    regressed: Mapped[bool] = mapped_column(Boolean, default=False)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RechargeOrder(Base):
    __tablename__ = "recharge_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    order_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    token_amount: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="PAID", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    resource_type: Mapped[str] = mapped_column(String(60), default="")
    resource_id: Mapped[str] = mapped_column(String(100), default="")
    details: Mapped[str] = mapped_column(Text, default="{}")
    ip_address: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
