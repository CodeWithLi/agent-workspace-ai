from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import AgentRole, ProjectMemberRole, SagaStepStatus, TaskStatus, TraceAlertStatus, UserRole, WorkflowStatus


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
    ai_token_balance: int
    created_at: datetime


class UserAdminUpdate(BaseModel):
    role: UserRole | None = None
    is_active: bool | None = None
    permissions: list[str] | None = None


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
    status: str
    created_at: datetime
    updated_at: datetime
    current_user_role: ProjectMemberRole = ProjectMemberRole.owner


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    status: str | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str | None) -> str | None:
        if value is not None and value not in {"ACTIVE", "ARCHIVED"}:
            raise ValueError("Project status must be ACTIVE or ARCHIVED")
        return value


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
    updated_at: datetime


class RequirementUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, min_length=1)
    status: str | None = None


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
    assignee_user_id: int | None = None
    due_date: str = ""
    due_at: datetime | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    priority: str | None = None
    status: TaskStatus | None = None
    assignee_agent_id: int | None = None
    assignee_user_id: int | None = None
    due_at: datetime | None = None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    title: str
    description: str
    priority: str
    status: TaskStatus
    assignee_agent_id: int | None
    assignee_user_id: int | None
    due_date: str
    due_at: datetime | None
    source_prototype_id: int | None
    source_prototype_version: int | None
    source_screen_id: str | None
    created_at: datetime
    updated_at: datetime


class TaskCommentCreate(BaseModel):
    content: str = Field(min_length=1, max_length=5000)


class TaskCommentOut(BaseModel):
    id: int
    task_id: int
    user_id: int
    user_name: str
    content: str
    created_at: datetime


class ProjectActivityOut(BaseModel):
    id: int
    action: str
    resource_type: str
    resource_id: str
    details: str
    user_id: int | None
    created_at: datetime


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
    human_approval_required: bool
    concurrency_limit: int
    current_version: int


class AgentUpdate(BaseModel):
    description: str = Field(min_length=1, max_length=2000)
    system_prompt: str = Field(min_length=1, max_length=12000)
    model: str = Field(min_length=1, max_length=100)
    memory_enable: bool
    knowledge_access: bool
    human_approval_required: bool
    concurrency_limit: int = Field(ge=1, le=100)


class AgentVersionCreate(AgentUpdate):
    release_note: str = Field(default="", max_length=500)


class AgentVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    agent_id: int
    version: int
    status: str
    description: str
    system_prompt: str
    model: str
    memory_enable: bool
    knowledge_access: bool
    human_approval_required: bool
    concurrency_limit: int
    release_note: str
    created_by_user_id: int | None
    created_at: datetime
    published_at: datetime | None


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


class AgentActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    project_id: int | None
    agent_id: int
    conversation_id: int | None
    tool_name: str
    input_json: str
    result_json: str
    status: str
    approved_by_user_id: int | None
    created_at: datetime
    decided_at: datetime | None


class AgentRouteRequest(BaseModel):
    agent_id: int | None = None
    message: str = Field(min_length=1, max_length=12000)
    project_id: int | None = None
    conversation_id: int | None = None


class ChatRequest(AgentRouteRequest):
    request_id: str = Field(min_length=8, max_length=64)


class DiscussionRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    project_id: int | None = None
    conversation_id: int | None = None
    request_id: str = Field(min_length=8, max_length=64)


class ToolCallOut(BaseModel):
    name: str
    input: dict[str, Any]
    output: Any


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    agent_id: int | None
    role: str
    stage: str
    content: str
    thinking: str
    tool_calls: str
    parent_message_id: int | None
    regenerated_from_id: int | None
    created_at: datetime


class MessageFeedbackRequest(BaseModel):
    rating: int
    comment: str = Field(default="", max_length=2000)

    @field_validator("rating")
    @classmethod
    def validate_rating(cls, value: int) -> int:
        if value not in {-1, 1}:
            raise ValueError("Rating must be -1 or 1")
        return value


class MessageFeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    message_id: int
    user_id: int
    rating: int
    comment: str
    created_at: datetime
    updated_at: datetime


class MessageRegenerateRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=64)


class MessageRegenerateOut(BaseModel):
    message: MessageOut
    token_balance: int


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    project_id: int | None
    agent_id: int
    user_id: int
    mode: str
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
    user_input: str = Field(min_length=1, max_length=20000)
    pause_before_report: bool = True
    require_plan_approval: bool = False
    request_id: str = Field(min_length=8, max_length=64)


class WorkflowContinueRequest(BaseModel):
    workflow_id: int
    human_feedback: str = Field(default="", max_length=4000)
    decision: Literal["APPROVE", "REVISE"] | None = None
    plan_version: int | None = Field(default=None, ge=1)


class WorkflowPauseRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=64)
    reason: str = Field(min_length=3, max_length=1000)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 3:
            raise ValueError("Pause reason must contain at least 3 non-whitespace characters")
        return normalized


class WorkflowRetryRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=64)


class WorkflowResponse(BaseModel):
    workflow_id: int
    project_id: int
    parent_workflow_id: int | None
    retry_from_node: str
    retry_sequence: int
    pause_requested_at: datetime | None
    pause_requested_by_user_id: int | None
    pause_reason: str
    intervention_count: int
    status: WorkflowStatus
    current_node: str
    state: dict[str, Any]
    attempt_count: int
    max_attempts: int
    error: str
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class WorkflowEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workflow_id: int
    node: str
    event_type: str
    message: str
    payload_json: str
    created_at: datetime


class WorkflowEventResponse(BaseModel):
    id: int
    workflow_id: int
    node: str
    event_type: str
    message: str
    payload: dict[str, Any]
    created_at: datetime


class WorkflowSagaStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workflow_id: int
    sequence: int
    node: str
    tool_name: str
    compensation_action: str
    idempotency_key: str
    status: SagaStepStatus
    input_json: str
    output_json: str
    transition_log_json: str
    execute_attempts: int
    compensation_attempts: int
    error: str
    started_at: datetime | None
    completed_at: datetime | None
    compensated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class WorkflowPublishRequest(BaseModel):
    document_type: str = Field(min_length=1, max_length=50)
    target: str
    request_id: str = Field(min_length=8, max_length=64)

    @field_validator("target")
    @classmethod
    def validate_publish_target(cls, value: str) -> str:
        if value not in {"report", "knowledge"}:
            raise ValueError("Publish target must be report or knowledge")
        return value


class WorkflowPublicationOut(BaseModel):
    id: int
    workflow_id: int
    document_type: str
    target: str
    report_id: int | None
    document_id: int | None


class TraceWindowOut(BaseModel):
    start_at: datetime
    end_at: datetime
    days: int
    analysis_truncated: bool


class TraceMetricSummaryOut(BaseModel):
    total_runs: int
    active_runs: int
    completed_runs: int
    failed_runs: int
    cancelled_runs: int
    success_rate: float
    average_duration_ms: int
    p95_duration_ms: int
    total_tokens: int
    total_cost_micros: int
    total_llm_calls: int


class TraceTrendPointOut(BaseModel):
    bucket: str
    runs: int
    completed: int
    failed: int
    cancelled: int
    total_tokens: int
    total_cost_micros: int


class TraceProjectOptionOut(BaseModel):
    project_id: int
    project_name: str


class TraceAgentMetricOut(BaseModel):
    agent_id: int | None
    agent_name: str
    agent_role: str
    providers: list[str]
    models: list[str]
    workflow_count: int
    call_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    total_cost_micros: int
    average_latency_ms: int
    p95_latency_ms: int
    max_latency_ms: int


class TraceBottleneckOut(BaseModel):
    key: str
    node: str
    label: str
    kind: str
    execution_count: int
    average_duration_ms: int
    p95_duration_ms: int
    max_duration_ms: int
    compute_share_percent: float


class TraceRunOut(BaseModel):
    workflow_id: int
    project_id: int
    parent_workflow_id: int | None
    retry_from_node: str
    retry_sequence: int
    intervention_count: int
    project_name: str
    owner_id: int
    owner_name: str
    status: WorkflowStatus
    current_node: str
    duration_ms: int
    queue_ms: int
    total_tokens: int
    total_cost_micros: int
    llm_call_count: int
    agent_count: int
    event_count: int
    error: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class TraceOverviewOut(BaseModel):
    window: TraceWindowOut
    metrics: TraceMetricSummaryOut
    status_counts: dict[str, int]
    trend: list[TraceTrendPointOut]
    projects: list[TraceProjectOptionOut]
    agents: list[TraceAgentMetricOut]
    bottlenecks: list[TraceBottleneckOut]
    recent_runs: list[TraceRunOut]


class TraceSLOTargetsOut(BaseModel):
    success_rate_percent: float
    p95_duration_ms: int
    average_cost_micros: int
    minimum_sample_runs: int
    anomaly_sensitivity: float


class TraceSLOMetricOut(BaseModel):
    key: str
    label: str
    unit: str
    target: float
    actual: float
    compliant: bool


class TraceHealthSummaryOut(BaseModel):
    status: str
    sample_count: int
    completed_count: int
    failed_count: int
    compliant_metric_count: int
    breached_metric_count: int
    error_budget_allowed_failures: float
    error_budget_consumed_failures: int
    error_budget_remaining_percent: float


class TraceAnomalyOut(BaseModel):
    workflow_id: int
    project_id: int
    project_name: str
    status: WorkflowStatus
    severity: str
    signals: list[str]
    duration_ms: int
    total_cost_micros: int
    detected_at: datetime


class TraceHealthOut(BaseModel):
    window: TraceWindowOut
    targets: TraceSLOTargetsOut
    summary: TraceHealthSummaryOut
    metrics: list[TraceSLOMetricOut]
    anomalies: list[TraceAnomalyOut]


class TraceAlertOut(BaseModel):
    id: int
    workflow_id: int
    project_id: int
    project_name: str
    severity: str
    status: TraceAlertStatus
    signals: list[str]
    duration_ms: int
    total_cost_micros: int
    detected_at: datetime
    acknowledged_by_user_id: int | None
    acknowledged_at: datetime | None
    resolved_by_user_id: int | None
    resolved_at: datetime | None
    resolution_note: str
    created_at: datetime
    updated_at: datetime


class TraceAlertSummaryOut(BaseModel):
    total: int
    open: int
    acknowledged: int
    resolved: int
    critical: int


class TraceAlertCollectionOut(BaseModel):
    summary: TraceAlertSummaryOut
    items: list[TraceAlertOut]


class TraceAlertSyncOut(BaseModel):
    created_count: int


class TraceAlertBulkUpdate(BaseModel):
    alert_ids: list[int] = Field(min_length=1, max_length=100)
    action: str
    resolution_note: str = Field(default="", max_length=500)

    @field_validator("alert_ids")
    @classmethod
    def validate_alert_ids(cls, value: list[int]) -> list[int]:
        if any(item <= 0 for item in value):
            raise ValueError("Alert IDs must be positive")
        return list(dict.fromkeys(value))

    @field_validator("action")
    @classmethod
    def validate_action(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"ACKNOWLEDGE", "RESOLVE"}:
            raise ValueError("Alert action must be ACKNOWLEDGE or RESOLVE")
        return normalized


class TraceSpanOut(BaseModel):
    span_id: str
    kind: str
    node: str
    label: str
    agent_role: str
    agent_name: str
    status: str
    attempt: int
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int
    llm_call_count: int
    total_tokens: int
    total_cost_micros: int
    model_latency_ms: int
    payload: dict[str, Any]


class TraceModelCallOut(BaseModel):
    id: int
    agent_id: int | None
    agent_name: str
    agent_role: str
    operation: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_micros: int
    latency_ms: int
    usage_source: str
    created_at: datetime


class TraceEventDetailOut(BaseModel):
    id: int
    node: str
    event_type: str
    message: str
    payload: dict[str, Any]
    created_at: datetime


class TraceDetailMetricsOut(BaseModel):
    total_duration_ms: int
    queue_ms: int
    active_compute_ms: int
    human_wait_ms: int
    coordination_ms: int
    total_tokens: int
    total_cost_micros: int
    total_llm_calls: int
    critical_span_id: str | None


class TraceDetailOut(BaseModel):
    run: TraceRunOut
    metrics: TraceDetailMetricsOut
    spans: list[TraceSpanOut]
    model_calls: list[TraceModelCallOut]
    events: list[TraceEventDetailOut]


class TraceComparisonMetricOut(BaseModel):
    key: str
    label: str
    unit: str
    baseline_value: int
    candidate_value: int
    delta: int
    delta_percent: float | None
    direction: str
    lower_is_better: bool


class TraceComparisonAgentOut(BaseModel):
    key: str
    agent_id: int | None
    agent_name: str
    agent_role: str
    change_type: str
    baseline_providers: list[str]
    candidate_providers: list[str]
    baseline_models: list[str]
    candidate_models: list[str]
    baseline_calls: int
    candidate_calls: int
    baseline_tokens: int
    candidate_tokens: int
    token_delta: int
    baseline_cost_micros: int
    candidate_cost_micros: int
    cost_delta_micros: int
    baseline_average_latency_ms: int
    candidate_average_latency_ms: int
    latency_delta_ms: int
    latency_direction: str


class TraceComparisonSpanOut(BaseModel):
    key: str
    kind: str
    node: str
    label: str
    agent_role: str
    change_type: str
    baseline_executions: int
    candidate_executions: int
    baseline_duration_ms: int
    candidate_duration_ms: int
    duration_delta_ms: int
    duration_delta_percent: float | None
    duration_direction: str
    baseline_tokens: int
    candidate_tokens: int
    token_delta: int
    baseline_cost_micros: int
    candidate_cost_micros: int
    cost_delta_micros: int


class TraceComparisonSummaryOut(BaseModel):
    verdict: str
    outcome_direction: str
    regression_count: int
    improvement_count: int
    changed_agent_count: int
    changed_span_count: int


class TraceComparisonOut(BaseModel):
    baseline: TraceRunOut
    candidate: TraceRunOut
    summary: TraceComparisonSummaryOut
    metrics: list[TraceComparisonMetricOut]
    agents: list[TraceComparisonAgentOut]
    spans: list[TraceComparisonSpanOut]


class KnowledgeDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int | None
    filename: str
    content_type: str
    status: str
    summary: str
    source_label: str
    metadata_json: str
    version: int
    attempts: int
    max_attempts: int
    error: str
    indexed_at: datetime | None
    active_index_version: int
    pending_index_version: int | None
    parser_name: str
    parser_version: str
    chunker_name: str
    chunker_version: str
    element_count: int
    chunk_count: int
    index_config_json: str
    created_at: datetime
    updated_at: datetime


class KnowledgeDocumentUpdate(BaseModel):
    tags: list[str] = Field(default_factory=list)
    source_label: str = Field(default="upload", min_length=1, max_length=100)


class KnowledgeDocumentActionRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=64)


class KnowledgeIndexVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: int
    status: str
    parser_name: str
    parser_version: str
    chunker_name: str
    chunker_version: str
    embedding_model: str
    embedding_dimensions: int
    element_count: int
    chunk_count: int
    config_json: str
    error: str
    activated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class KnowledgeChunkOut(BaseModel):
    document_id: int
    filename: str
    chunk_index: int
    content: str
    citation: str
    stable_id: str = ""
    index_version: int = 0
    parent_stable_id: str = ""
    parent_content: str = ""
    heading_path: list[str] = Field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None
    token_count: int = 0


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    project_id: int | None = None
    top_k: int | None = Field(default=None, ge=1, le=20)
    min_score: float | None = Field(default=None, ge=0.0, le=1.0)
    document_ids: list[int] = Field(default_factory=list, max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=20)
    source_labels: list[str] = Field(default_factory=list, max_length=20)


class KnowledgeSearchResult(BaseModel):
    document_id: int
    filename: str
    chunk_index: int
    content: str
    score: float
    citation: str
    stable_id: str = ""
    index_version: int = 0
    heading_path: list[str] = Field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None
    sparse_score: float = 0.0
    dense_score: float = 0.0
    hybrid_score: float = 0.0
    query_coverage: float = 0.0
    rerank_score: float | None = None
    rerank_fallback: bool | None = None
    source_label: str = ""
    tags: list[str] = Field(default_factory=list)


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
    updated_at: datetime


class MeetingUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    transcript: str | None = Field(default=None, min_length=1)
    summary: str | None = None
    action_items: list[dict[str, Any]] | None = None


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
    updated_at: datetime


class ReportUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, min_length=1)
    report_type: str | None = Field(default=None, min_length=1, max_length=50)


class NotificationCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    channel: str = "in_app"
    recipient_email: EmailStr | None = None
    schedule_at: datetime | None = None
    project_id: int | None = None

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, value: str) -> str:
        if value not in {"in_app", "email"}:
            raise ValueError("Notification channel must be in_app or email")
        return value


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int | None
    title: str
    content: str
    channel: str
    schedule_at: str
    recipient_user_id: int | None
    recipient_email: str
    scheduled_for: datetime | None
    status: str
    attempts: int
    sent_at: datetime | None
    last_error: str
    created_at: datetime


class SettingItemOut(BaseModel):
    key: str
    label: str
    category: str
    value: Any | None
    value_type: str
    minimum: float | None
    maximum: float | None
    secret: bool
    configured: bool
    source: str
    restart_required: bool
    updated_at: datetime | None


class SettingCollectionOut(BaseModel):
    environment: str
    items: list[SettingItemOut]


class SettingUpdate(BaseModel):
    values: dict[str, Any]


class SettingConnectionTestRequest(BaseModel):
    target: str

    @field_validator("target")
    @classmethod
    def validate_target(cls, value: str) -> str:
        allowed = {"llm", "embedding", "reranker", "docling", "redis", "milvus", "minio", "smtp"}
        if value not in allowed:
            raise ValueError(f"Connection target must be one of: {', '.join(sorted(allowed))}")
        return value


class SettingConnectionTestOut(BaseModel):
    target: str
    ok: bool
    message: str


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


class EvaluationCaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    agent_role: AgentRole
    input_text: str = Field(min_length=1, max_length=20000)
    expected_keywords: list[str] = Field(default_factory=list)
    forbidden_keywords: list[str] = Field(default_factory=list)
    rubric: str = Field(default="", max_length=10000)
    minimum_score: float = Field(default=0.8, ge=0, le=1)
    weight: float = Field(default=1.0, gt=0, le=100)
    enabled: bool = True


class EvaluationCaseUpdate(EvaluationCaseCreate):
    pass


class EvaluationCaseOut(BaseModel):
    id: int
    name: str
    agent_role: str
    input_text: str
    expected_keywords: list[str]
    forbidden_keywords: list[str]
    rubric: str
    minimum_score: float
    weight: float
    enabled: bool
    created_at: datetime
    updated_at: datetime


class EvaluationCoverageOut(BaseModel):
    required_roles: list[str]
    covered_roles: list[str]
    missing_roles: list[str]
    case_counts: dict[str, int]
    total_enabled_cases: int
    coverage_percent: float
    gate_ready: bool


class EvaluationCaseBootstrapOut(BaseModel):
    created_roles: list[str]
    created_case_ids: list[int]
    coverage: EvaluationCoverageOut


class EvaluationFeedbackPromoteRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    request_id: str = Field(min_length=8, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    expected_keywords: list[str] = Field(default_factory=list)
    forbidden_keywords: list[str] = Field(default_factory=list)
    rubric: str = Field(min_length=1, max_length=10000)
    minimum_score: float = Field(default=0.8, ge=0, le=1)
    weight: float = Field(default=1.0, gt=0, le=100)


class EvaluationFeedbackDismissRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    request_id: str = Field(min_length=8, max_length=64)
    reason: str = Field(min_length=1, max_length=1000)


class EvaluationFeedbackCandidateOut(BaseModel):
    feedback_id: int
    review_id: int | None
    status: str
    evaluation_case_id: int | None
    message_id: int
    conversation_id: int
    project_id: int | None
    user_id: int
    user_name: str
    agent_id: int
    agent_name: str
    agent_role: str
    input_text: str
    answer: str
    comment: str
    resolution_note: str
    created_at: datetime
    reviewed_at: datetime | None


class EvaluationRunCreate(BaseModel):
    request_id: str = Field(min_length=8, max_length=64)
    baseline_run_id: int | None = Field(default=None, ge=1)
    candidate_version_id: int | None = Field(default=None, ge=1)


class EvaluationReleaseRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=64)


class AgentEvaluationReleaseOut(BaseModel):
    id: int
    evaluation_run_id: int
    agent_id: int
    agent_name: str
    candidate_version_id: int | None
    candidate_version: int
    previous_version: int
    expected_current_version: int
    status: str
    published_by_user_id: int | None
    published_at: datetime
    rollback_version: int | None
    rolled_back_by_user_id: int | None
    rolled_back_at: datetime | None


class EvaluationAgentSnapshotOut(BaseModel):
    id: int
    name: str
    role: str
    version: int
    model: str


class EvaluationResultOut(BaseModel):
    id: int
    case_id: int
    case_name: str
    agent_role: str
    agent_name: str
    agent_version: int | None
    model: str
    input_text: str
    expected_keywords: list[str]
    forbidden_keywords: list[str]
    rubric: str
    answer: str
    score: float
    baseline_answer: str
    baseline_score: float | None
    score_delta: float | None
    dimensions: dict[str, float]
    baseline_dimensions: dict[str, float]
    score_source: str
    latency_ms: int
    regressed: bool
    passed: bool
    optimization_eligible: bool
    matched_keywords: list[str]
    missing_keywords: list[str]
    forbidden_hits: list[str]
    judge_reason: str
    judge_error: str
    error: str
    created_at: datetime


class EvaluationRunOut(BaseModel):
    id: int
    request_id: str | None
    status: str
    suite_revision: int | None
    baseline_run_id: int | None
    candidate_agent_id: int | None
    candidate_agent_name: str
    candidate_version_id: int | None
    candidate_version: int | None
    expected_current_version: int | None
    release: AgentEvaluationReleaseOut | None
    total_cases: int
    completed_cases: int
    progress_percent: int
    passed_cases: int
    average_score: float
    baseline_average_score: float | None
    score_delta: float | None
    gate_passed: bool | None
    gate_failures: list[str]
    dimension_averages: dict[str, float]
    baseline_dimension_averages: dict[str, float]
    agent_snapshots: list[EvaluationAgentSnapshotOut]
    error: str
    attempt_count: int
    max_attempts: int
    retryable: bool
    created_by_user_id: int | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class EvaluationRunDetailOut(EvaluationRunOut):
    results: list[EvaluationResultOut]


class AgentOptimizationJobCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    request_id: str = Field(min_length=8, max_length=64)
    evaluation_run_id: int = Field(ge=1)
    result_ids: list[int] = Field(default_factory=list, max_length=20)
    agent_id: int | None = Field(default=None, ge=1)


class AgentOptimizationEvidenceOut(BaseModel):
    result_id: int
    case_id: int | None
    case_name: str
    score: float
    regressed: bool
    failure_signals: list[str]


class AgentOptimizationJobOut(BaseModel):
    id: int
    request_id: str
    evaluation_run_id: int
    agent_id: int
    agent_name: str
    agent_role: str
    source_version_id: int | None
    source_version: int
    source_result_ids: list[int]
    evidence_count: int
    evidence_fingerprint: str
    status: str
    stage: str
    progress_percent: int
    optimizer_model: str
    reviewer_model: str
    change_summary: str
    reviewer_risk_level: str
    reviewer_approved: bool | None
    revision_round_count: int
    draft_version_id: int | None
    draft_version: int | None
    draft_status: str
    error_code: str
    error_message: str
    attempt_count: int
    max_attempts: int
    retryable: bool
    cancellable: bool
    created_by_user_id: int | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class AgentOptimizationJobDetailOut(AgentOptimizationJobOut):
    proposed_system_prompt: str
    reviewer_reason: str
    reviewer_risks: list[Any]
    revision_history: list[dict[str, Any]]
    safety_checks: dict[str, Any]
    evidence: list[AgentOptimizationEvidenceOut]


class TokenTransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    amount: int
    balance_after: int
    transaction_type: str
    reference_type: str
    reference_id: str
    description: str
    created_at: datetime


class LLMUsageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None
    project_id: int | None
    agent_id: int | None
    workflow_id: int | None
    agent_run_id: int | None
    operation: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_micros: int
    latency_ms: int
    usage_source: str
    created_at: datetime


class RechargeOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_no: str
    user_id: int
    amount_cents: int
    token_amount: int
    status: str
    created_at: datetime
    paid_at: datetime | None


class WalletOut(BaseModel):
    balance: int
    chat_cost: int
    workflow_cost: int
    recharge_tokens_per_yuan: int
    fake_recharge: bool = True
    transactions: list[TokenTransactionOut]


class RechargeRequest(BaseModel):
    amount_yuan: int = Field(ge=1, le=10_000)
    request_id: str = Field(min_length=8, max_length=64)


class AdminTokenAdjustment(BaseModel):
    user_id: int
    amount: int = Field(ge=-1_000_000, le=1_000_000)
    reason: str = Field(min_length=2, max_length=300)
    request_id: str = Field(min_length=8, max_length=64)
