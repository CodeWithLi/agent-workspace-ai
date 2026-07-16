from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, Enum as SqlEnum, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
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
    running = "RUNNING"
    paused = "PAUSED"
    completed = "COMPLETED"
    failed = "FAILED"


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    owner: Mapped[User] = relationship(back_populates="projects")
    tasks: Mapped[list["Task"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="project")
    documents: Mapped[list["KnowledgeDocument"]] = relationship(back_populates="project")
    meetings: Mapped[list["Meeting"]] = relationship(back_populates="project")
    reports: Mapped[list["Report"]] = relationship(back_populates="project")
    notifications: Mapped[list["Notification"]] = relationship(back_populates="project")
    workflows: Mapped[list["WorkflowRun"]] = relationship(back_populates="project")
    requirements: Mapped[list["Requirement"]] = relationship(back_populates="project")
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

    project: Mapped[Project | None] = relationship(back_populates="requirements")


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


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(200), default="New conversation")
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project | None] = relationship(back_populates="conversations")
    agent: Mapped[Agent] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(30))
    content: Mapped[str] = mapped_column(Text)
    tool_calls: Mapped[str] = mapped_column(Text, default="[]")
    thinking: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Task(Base):
    __tablename__ = "tasks"

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
    due_date: Mapped[str] = mapped_column(String(50), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    project: Mapped[Project] = relationship(back_populates="tasks")


class KnowledgeDocument(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100), default="application/octet-stream")
    storage_path: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(30), default="INDEXED")
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project | None] = relationship(back_populates="documents")
    chunks: Mapped[list["Embedding"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Embedding(Base):
    __tablename__ = "embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    content: Mapped[str] = mapped_column(Text)
    chunk_index: Mapped[int] = mapped_column(Integer)
    vector_id: Mapped[str | None] = mapped_column(String(100))
    vector_json: Mapped[str] = mapped_column(Text, default="[]")
    score_hint: Mapped[float] = mapped_column(Float, default=0.0)
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
        default=WorkflowStatus.running,
    )
    current_node: Mapped[str] = mapped_column(String(100), default="requirement")
    state_json: Mapped[str] = mapped_column(Text, default="{}")
    human_feedback: Mapped[str] = mapped_column(Text, default="")
    request_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    project: Mapped[Project] = relationship(back_populates="workflows")


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
