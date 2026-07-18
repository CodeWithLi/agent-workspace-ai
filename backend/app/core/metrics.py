from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest


HTTP_REQUESTS = Counter(
    "agent_workspace_http_requests_total",
    "HTTP requests by method, route and status",
    ("method", "route", "status"),
)
HTTP_DURATION = Histogram(
    "agent_workspace_http_request_duration_seconds",
    "HTTP request duration by method and route",
    ("method", "route"),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 90),
)
HTTP_IN_PROGRESS = Gauge(
    "agent_workspace_http_requests_in_progress",
    "HTTP requests currently being processed",
    ("method",),
)
WORKFLOW_QUEUE = Gauge("agent_workspace_workflow_queue", "Workflows by status", ("status",))
KNOWLEDGE_QUEUE = Gauge("agent_workspace_knowledge_queue", "Knowledge documents by status", ("status",))
NOTIFICATION_QUEUE = Gauge("agent_workspace_notification_queue", "Notifications by status", ("status",))
PROTOTYPE_GENERATION_QUEUE = Gauge(
    "agent_workspace_prototype_generation_queue",
    "Prototype generation jobs by status",
    ("status",),
)
PROTOTYPE_GENERATION_EVENTS = Counter(
    "agent_workspace_prototype_generation_events_total",
    "Prototype generation events by type",
    ("event_type",),
)
PROTOTYPE_GENERATION_DURATION = Histogram(
    "agent_workspace_prototype_generation_duration_seconds",
    "Prototype generation duration by operation and terminal status",
    ("operation", "status"),
    buckets=(1, 5, 15, 30, 60, 90, 120, 180, 300, 600, 1200),
)
EVALUATION_QUEUE = Gauge(
    "agent_workspace_evaluation_queue",
    "Agent evaluation runs by status",
    ("status",),
)
EVALUATION_DURATION = Histogram(
    "agent_workspace_evaluation_duration_seconds",
    "Agent evaluation duration by terminal status",
    ("status",),
    buckets=(1, 5, 15, 30, 60, 90, 120, 180, 300, 600, 1200),
)
AGENT_OPTIMIZATION_QUEUE = Gauge(
    "agent_workspace_agent_optimization_queue",
    "Agent prompt optimization jobs by status",
    ("status",),
)
AGENT_OPTIMIZATION_DURATION = Histogram(
    "agent_workspace_agent_optimization_duration_seconds",
    "Agent prompt optimization duration by terminal status",
    ("status",),
    buckets=(1, 5, 15, 30, 60, 90, 120, 180, 300, 600, 1200),
)
SAGA_STEPS = Counter(
    "agent_workspace_saga_step_transitions_total",
    "Durable Saga step state transitions",
    ("tool", "status"),
)
SAGA_COMPENSATION_DURATION = Histogram(
    "agent_workspace_saga_compensation_duration_seconds",
    "Workflow Saga compensation duration",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 15, 30, 90),
)
SAGA_STEP_GAUGE = Gauge("agent_workspace_saga_steps", "Workflow Saga steps by status", ("status",))
RAG_INDEX_DURATION = Histogram(
    "agent_workspace_rag_index_duration_seconds",
    "Knowledge indexing duration by parser, chunker and status",
    ("parser", "chunker", "status"),
    buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 900),
)
RAG_INDEX_CHUNKS = Histogram(
    "agent_workspace_rag_index_chunks",
    "Chunks produced by a successful knowledge indexing run",
    buckets=(1, 2, 5, 10, 25, 50, 100, 250, 500, 1000, 5000),
)
RAG_EMBEDDING_CHUNKS = Counter(
    "agent_workspace_rag_embedding_chunks_total",
    "Knowledge chunks by embedding source",
    ("source",),
)
RAG_SEARCH_DURATION = Histogram(
    "agent_workspace_rag_search_duration_seconds",
    "End-to-end knowledge search duration",
    ("status",),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)
RAG_SEARCH_RESULTS = Histogram(
    "agent_workspace_rag_search_results",
    "Number of knowledge results returned",
    buckets=(0, 1, 2, 3, 5, 10, 20),
)
RAG_QUERY_REWRITES = Counter(
    "agent_workspace_rag_query_rewrites_total",
    "Query rewrite attempts by outcome",
    ("status",),
)
RAG_RERANK_REQUESTS = Counter(
    "agent_workspace_rag_rerank_requests_total",
    "Cross-encoder reranker requests by outcome",
    ("status",),
)


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
