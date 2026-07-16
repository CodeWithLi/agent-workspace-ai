from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import AgentRole, ProjectMemberRole, TaskStatus, UserRole, WorkflowStatus


class UserCreate(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        if not any(char.isalpha() for char in value) or not any(char.isdigit() for char in value):
            raise ValueError("Password must contain both letters and numbers")
        return value


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str
    role: UserRole
    is_active: bool
    permissions: str
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    members: str = ""


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    members: str
    owner_id: int
    created_at: datetime
    current_user_role: ProjectMemberRole = ProjectMemberRole.owner


class ProjectMemberCreate(BaseModel):
    email: EmailStr
    role: ProjectMemberRole = ProjectMemberRole.viewer

    @field_validator("role")
    @classmethod
    def disallow_owner_assignment(cls, value: ProjectMemberRole) -> ProjectMemberRole:
        if value == ProjectMemberRole.owner:
            raise ValueError("Project ownership cannot be assigned through membership")
        return value


class ProjectMemberOut(BaseModel):
    id: int
    project_id: int
    user_id: int
    email: str
    name: str
    role: ProjectMemberRole
    created_at: datetime


class DashboardStats(BaseModel):
    projects: int
    agents: int
    tasks: dict[str, int]
    documents: int
    recent_activities: list[str]


class RequirementCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    project_id: int | None = None


class RequirementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int | None
    title: str
    content: str
    status: str
    analysis: str
    created_at: datetime


class GlobalSearchResult(BaseModel):
    type: str
    title: str
    description: str
    url: str


class GlobalSearchResponse(BaseModel):
    results: list[GlobalSearchResult]


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    priority: str = "MEDIUM"
    assignee_agent_id: int | None = None
    due_date: str = ""


class TaskUpdate(BaseModel):
    status: TaskStatus


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    title: str
    description: str
    priority: str
    status: TaskStatus
    assignee_agent_id: int | None
    due_date: str
    created_at: datetime
    updated_at: datetime


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    role: AgentRole
    description: str
    system_prompt: str
    model: str
    tools: str
    memory_enable: bool
    knowledge_access: bool


class AgentToolOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    agent_id: int
    name: str
    description: str
    enabled: bool
    allowed_roles: str


class AgentToolUpdate(BaseModel):
    enabled: bool
    allowed_roles: str = "admin,member"


class ChatRequest(BaseModel):
    agent_id: int | None = None
    message: str = Field(min_length=1)
    project_id: int | None = None
    conversation_id: int | None = None


class ToolCallOut(BaseModel):
    name: str
    input: dict[str, Any]
    output: Any


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    role: str
    content: str
    thinking: str
    tool_calls: str
    created_at: datetime


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    project_id: int | None
    agent_id: int
    user_id: int
    created_at: datetime


class ChatResponse(BaseModel):
    conversation_id: int
    agent_id: int
    agent_name: str
    answer: str
    thinking: str
    tool_calls: list[ToolCallOut]
    messages: list[MessageOut]


class AgentRouteResponse(BaseModel):
    agent_id: int
    agent_name: str
    confidence: float
    reason: str


class WorkflowRequest(BaseModel):
    project_id: int
    user_input: str = Field(min_length=1)
    pause_before_report: bool = True


class WorkflowContinueRequest(BaseModel):
    workflow_id: int
    human_feedback: str = ""


class WorkflowResponse(BaseModel):
    workflow_id: int
    project_id: int
    status: WorkflowStatus
    current_node: str
    state: dict[str, Any]


class KnowledgeDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int | None
    filename: str
    content_type: str
    status: str
    summary: str
    created_at: datetime


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    project_id: int | None = None
    top_k: int = Field(default=5, ge=1, le=20)
    min_score: float = Field(default=0.2, ge=0.0, le=1.0)


class KnowledgeSearchResult(BaseModel):
    document_id: int
    filename: str
    content: str
    score: float
    citation: str


class KnowledgeSearchResponse(BaseModel):
    answer: str
    results: list[KnowledgeSearchResult]


class MeetingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    transcript: str = Field(min_length=1)
    project_id: int | None = None


class MeetingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int | None
    title: str
    transcript: str
    summary: str
    action_items: str
    created_at: datetime


class ReportCreate(BaseModel):
    project_id: int
    report_type: str = "daily"


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    report_type: str
    title: str
    content: str
    created_at: datetime


class NotificationCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    channel: str = "email"
    schedule_at: str = ""
    project_id: int | None = None


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int | None
    title: str
    content: str
    channel: str
    schedule_at: str
    status: str
    created_at: datetime


class SettingOut(BaseModel):
    provider: str
    base_url: str
    model: str
    embedding_model: str
    milvus_collection: str
    environment: str
    allow_registration: bool
    registration_email_domains: list[str]


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None
    project_id: int | None
    action: str
    resource_type: str
    resource_id: str
    details: str
    ip_address: str
    created_at: datetime
