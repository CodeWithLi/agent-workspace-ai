from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Agent Workspace AI"
    api_prefix: str = "/api/v1"
    environment: str = "development"
    auto_create_schema: bool = True
    secret_key: str = Field(default="change-me-in-production", min_length=16)
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = Field(default=30, ge=1, le=180)
    refresh_cookie_name: str = "agent_workspace_refresh"
    admin_cookie_name: str = "agent_workspace_admin"
    allow_registration: bool = True
    first_superuser_email: str | None = None
    registration_email_domains: list[str] = []
    trusted_hosts: list[str] = ["localhost", "127.0.0.1", "*.localhost"]

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/agent_workspace_ai"
    redis_url: str = "redis://localhost:6379/0"

    llm_provider: str = "zhipu"
    llm_api_key: str | None = None
    llm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    llm_model: str = "glm-4-flash"
    llm_fallback_enabled: bool = True
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    llm_input_cost_per_million: float = Field(default=0.0, ge=0, le=10000)
    llm_output_cost_per_million: float = Field(default=0.0, ge=0, le=10000)
    embedding_cost_per_million: float = Field(default=0.0, ge=0, le=10000)
    evaluation_case_min_score: float = Field(default=0.8, ge=0, le=1)
    evaluation_min_average: float = Field(default=0.8, ge=0, le=1)
    evaluation_average_regression_tolerance: float = Field(default=0.02, ge=0, le=1)
    evaluation_case_regression_tolerance: float = Field(default=0.10, ge=0, le=1)
    evaluation_judge_model: str | None = None
    evaluation_worker_enabled: bool = True
    evaluation_poll_seconds: int = Field(default=1, ge=1, le=60)
    evaluation_lease_seconds: int = Field(default=300, ge=60, le=3600)
    evaluation_max_attempts: int = Field(default=2, ge=1, le=10)
    evaluation_retry_base_seconds: int = Field(default=5, ge=1, le=300)
    embedding_model: str = "embedding-3"
    embedding_api_key: str | None = None
    embedding_base_url: str | None = None
    embedding_dimensions: int = Field(default=256, ge=32, le=2048)
    rag_top_k: int = Field(default=5, ge=1, le=20)
    rag_min_score: float = Field(default=0.2, ge=0.0, le=1.0)
    rag_chunk_size: int = Field(default=900, ge=200, le=4000)
    rag_chunk_overlap: int = Field(default=140, ge=0, le=1000)
    rag_child_chunk_tokens: int = Field(default=400, ge=64, le=2000)
    rag_parent_chunk_tokens: int = Field(default=1200, ge=128, le=8000)
    rag_chunk_overlap_tokens: int = Field(default=100, ge=0, le=500)
    rag_min_chunk_tokens: int = Field(default=30, ge=1, le=500)
    rag_chunk_strategy: str = "structural"
    rag_semantic_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    rag_multi_vector_enabled: bool = False
    rag_context_max_tokens: int = Field(default=4000, ge=256, le=32000)
    rag_min_query_coverage: float = Field(default=0.15, ge=0.0, le=1.0)
    rag_dense_override_score: float = Field(default=0.72, ge=0.0, le=1.0)
    rag_query_rewrite_enabled: bool = True
    rag_query_rewrite_max_variants: int = Field(default=3, ge=1, le=5)
    reranker_enabled: bool = False
    reranker_base_url: str | None = None
    reranker_api_key: str | None = None
    reranker_model: str = "bge-reranker-v2-m3"
    reranker_candidate_limit: int = Field(default=40, ge=5, le=200)
    reranker_timeout_seconds: float = Field(default=15.0, ge=1.0, le=120.0)
    reranker_cost_per_million: float = Field(default=0.0, ge=0, le=10000)
    rag_rerank_override_score: float = Field(default=0.6, ge=0.0, le=1.0)
    rag_fallback_candidate_limit: int = Field(default=1000, ge=50, le=10000)
    rag_parser_backend: str = "native"
    rag_parser_fallback_enabled: bool = True
    docling_serve_url: str | None = None
    docling_serve_api_key: str | None = None
    docling_timeout_seconds: float = Field(default=300.0, ge=10.0, le=1800.0)
    docling_do_ocr: bool = True
    rag_max_uncompressed_mb: int = Field(default=200, ge=10, le=2000)
    rag_max_document_chars: int = Field(default=2_000_000, ge=10_000, le=20_000_000)
    rag_max_pdf_pages: int = Field(default=500, ge=1, le=5000)
    rag_max_elements: int = Field(default=50_000, ge=100, le=500_000)
    rag_max_chunks: int = Field(default=10_000, ge=10, le=100_000)
    knowledge_worker_enabled: bool = True
    knowledge_poll_seconds: int = Field(default=1, ge=1, le=60)
    knowledge_lease_seconds: int = Field(default=300, ge=60, le=3600)
    knowledge_max_attempts: int = Field(default=3, ge=1, le=10)

    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_collection: str = "knowledge_chunks_v4"
    vector_fallback_enabled: bool = True
    metrics_enabled: bool = True

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "agent-workspace"
    minio_secure: bool = False
    storage_fallback_enabled: bool = True
    local_upload_dir: str = "storage/uploads"
    max_upload_mb: int = Field(default=25, ge=1, le=200)

    notification_worker_enabled: bool = True
    notification_poll_seconds: int = Field(default=5, ge=1, le=300)
    notification_max_attempts: int = Field(default=3, ge=1, le=10)
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_starttls: bool = True

    welcome_ai_tokens: int = Field(default=1000, ge=0, le=1_000_000)
    chat_token_cost: int = Field(default=10, ge=1, le=10_000)
    discussion_token_cost: int = Field(default=50, ge=1, le=50_000)
    workflow_token_cost: int = Field(default=100, ge=1, le=100_000)
    recharge_tokens_per_yuan: int = Field(default=100, ge=1, le=100_000)
    agent_concurrency_acquire_timeout: float = Field(default=3.0, ge=0.1, le=30.0)
    agent_concurrency_lease_seconds: int = Field(default=180, ge=30, le=900)
    agent_run_stale_minutes: int = Field(default=15, ge=5, le=1440)
    workflow_worker_enabled: bool = True
    workflow_poll_seconds: int = Field(default=1, ge=1, le=60)
    workflow_lease_seconds: int = Field(default=900, ge=60, le=7200)
    workflow_max_attempts: int = Field(default=2, ge=1, le=10)
    workflow_compensation_max_attempts: int = Field(default=3, ge=1, le=10)
    prototype_generation_worker_enabled: bool = True
    prototype_generation_poll_seconds: int = Field(default=1, ge=1, le=60)
    prototype_generation_lease_seconds: int = Field(default=300, ge=60, le=3600)
    prototype_generation_max_attempts: int = Field(default=3, ge=1, le=10)
    prototype_generation_retry_base_seconds: int = Field(default=5, ge=1, le=300)
    prototype_generation_retry_max_seconds: int = Field(default=300, ge=5, le=3600)
    prototype_generation_shutdown_grace_seconds: int = Field(default=15, ge=1, le=300)

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        if self.rag_chunk_overlap >= self.rag_chunk_size:
            raise ValueError("RAG character overlap must be smaller than character chunk size")
        if self.rag_parent_chunk_tokens < self.rag_child_chunk_tokens:
            raise ValueError("RAG parent token budget must not be smaller than child token budget")
        if self.rag_chunk_overlap_tokens >= self.rag_child_chunk_tokens:
            raise ValueError("RAG token overlap must be smaller than child token budget")
        if self.rag_min_chunk_tokens > self.rag_child_chunk_tokens:
            raise ValueError("RAG minimum chunk tokens must not exceed child token budget")
        if self.rag_chunk_strategy not in {"structural", "semantic"}:
            raise ValueError("RAG chunk strategy must be structural or semantic")
        if self.rag_parser_backend not in {"native", "auto", "docling"}:
            raise ValueError("RAG parser backend must be native, auto or docling")
        if self.prototype_generation_retry_max_seconds < self.prototype_generation_retry_base_seconds:
            raise ValueError("Prototype generation retry maximum must not be smaller than its base delay")
        if self.environment == "production":
            if self.secret_key in {"change-me-in-production", "please-change-this-secret"} or len(self.secret_key) < 32:
                raise ValueError("Production SECRET_KEY must be unique and at least 32 characters")
            if self.llm_fallback_enabled:
                raise ValueError("Production requires LLM_FALLBACK_ENABLED=false")
            if self.storage_fallback_enabled:
                raise ValueError("Production requires STORAGE_FALLBACK_ENABLED=false")
            if self.vector_fallback_enabled:
                raise ValueError("Production requires VECTOR_FALLBACK_ENABLED=false")
            if not self.first_superuser_email:
                raise ValueError("Production requires FIRST_SUPERUSER_EMAIL")
            if self.auto_create_schema:
                raise ValueError("Production requires AUTO_CREATE_SCHEMA=false and Alembic migrations")
        return self

    model_config = SettingsConfigDict(
        env_file=(".env", "dependencies.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
