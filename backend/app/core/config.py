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
    embedding_model: str = "embedding-3"
    embedding_api_key: str | None = None
    embedding_base_url: str | None = None
    embedding_dimensions: int = Field(default=256, ge=32, le=2048)

    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_collection: str = "knowledge_chunks_v2"

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
    workflow_token_cost: int = Field(default=100, ge=1, le=100_000)
    recharge_tokens_per_yuan: int = Field(default=100, ge=1, le=100_000)
    agent_concurrency_acquire_timeout: float = Field(default=3.0, ge=0.1, le=30.0)
    agent_concurrency_lease_seconds: int = Field(default=180, ge=30, le=900)
    agent_run_stale_minutes: int = Field(default=15, ge=5, le=1440)

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        if self.environment == "production":
            if self.secret_key in {"change-me-in-production", "please-change-this-secret"} or len(self.secret_key) < 32:
                raise ValueError("Production SECRET_KEY must be unique and at least 32 characters")
            if self.llm_fallback_enabled:
                raise ValueError("Production requires LLM_FALLBACK_ENABLED=false")
            if self.storage_fallback_enabled:
                raise ValueError("Production requires STORAGE_FALLBACK_ENABLED=false")
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
