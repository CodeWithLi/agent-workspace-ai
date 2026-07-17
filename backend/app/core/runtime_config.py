import asyncio
import base64
import hashlib
import json
import logging
import os
from dataclasses import dataclass
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import SystemSettingOverride


logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass(frozen=True)
class ConfigDefinition:
    key: str
    label: str
    category: str
    value_type: type
    secret: bool = False
    minimum: float | None = None
    maximum: float | None = None
    restart_required: bool = False


CONFIG_DEFINITIONS = {
    item.key: item
    for item in (
        ConfigDefinition("llm_provider", "LLM Provider", "model", str),
        ConfigDefinition("llm_base_url", "LLM Base URL", "model", str),
        ConfigDefinition("llm_model", "LLM Model", "model", str),
        ConfigDefinition("llm_api_key", "LLM API Key", "model", str, secret=True),
        ConfigDefinition("openai_base_url", "Fallback Base URL", "model", str),
        ConfigDefinition("openai_model", "Fallback Model", "model", str),
        ConfigDefinition("openai_api_key", "Fallback API Key", "model", str, secret=True),
        ConfigDefinition("llm_input_cost_per_million", "Input Cost / 1M Tokens", "billing", float, minimum=0, maximum=10000),
        ConfigDefinition("llm_output_cost_per_million", "Output Cost / 1M Tokens", "billing", float, minimum=0, maximum=10000),
        ConfigDefinition("embedding_cost_per_million", "Embedding Cost / 1M Tokens", "billing", float, minimum=0, maximum=10000),
        ConfigDefinition("evaluation_case_min_score", "Evaluation Case Pass Score", "model", float, minimum=0, maximum=1),
        ConfigDefinition("evaluation_min_average", "Evaluation Minimum Average", "model", float, minimum=0, maximum=1),
        ConfigDefinition("embedding_base_url", "Embedding Base URL", "model", str),
        ConfigDefinition("embedding_model", "Embedding Model", "model", str),
        ConfigDefinition("embedding_api_key", "Embedding API Key", "model", str, secret=True),
        ConfigDefinition("embedding_dimensions", "Embedding Dimensions", "model", int, minimum=32, maximum=2048, restart_required=True),
        ConfigDefinition("rag_top_k", "Default Top K", "rag", int, minimum=1, maximum=20),
        ConfigDefinition("rag_min_score", "Minimum Similarity", "rag", float, minimum=0, maximum=1),
        ConfigDefinition("rag_chunk_size", "Chunk Size", "rag", int, minimum=200, maximum=4000),
        ConfigDefinition("rag_chunk_overlap", "Chunk Overlap", "rag", int, minimum=0, maximum=1000),
        ConfigDefinition("rag_child_chunk_tokens", "Child Chunk Tokens", "rag", int, minimum=64, maximum=2000),
        ConfigDefinition("rag_parent_chunk_tokens", "Parent Chunk Tokens", "rag", int, minimum=128, maximum=8000),
        ConfigDefinition("rag_chunk_overlap_tokens", "Chunk Overlap Tokens", "rag", int, minimum=0, maximum=500),
        ConfigDefinition("rag_min_chunk_tokens", "Minimum Chunk Tokens", "rag", int, minimum=1, maximum=500),
        ConfigDefinition("rag_context_max_tokens", "Context Maximum Tokens", "rag", int, minimum=256, maximum=32000),
        ConfigDefinition("rag_min_query_coverage", "Minimum Query Coverage", "rag", float, minimum=0, maximum=1),
        ConfigDefinition("rag_dense_override_score", "Dense Override Score", "rag", float, minimum=0, maximum=1),
        ConfigDefinition("rag_query_rewrite_enabled", "Query Rewrite Enabled", "rag", bool),
        ConfigDefinition("rag_query_rewrite_max_variants", "Query Rewrite Variants", "rag", int, minimum=1, maximum=5),
        ConfigDefinition("reranker_enabled", "Reranker Enabled", "rag", bool),
        ConfigDefinition("reranker_base_url", "Reranker Base URL", "rag", str),
        ConfigDefinition("reranker_api_key", "Reranker API Key", "rag", str, secret=True),
        ConfigDefinition("reranker_model", "Reranker Model", "rag", str),
        ConfigDefinition("reranker_candidate_limit", "Reranker Candidate Limit", "rag", int, minimum=5, maximum=200),
        ConfigDefinition("reranker_timeout_seconds", "Reranker Timeout Seconds", "rag", float, minimum=1, maximum=120),
        ConfigDefinition("reranker_cost_per_million", "Reranker Cost / 1M Tokens", "billing", float, minimum=0, maximum=10000),
        ConfigDefinition("rag_rerank_override_score", "Reranker Override Score", "rag", float, minimum=0, maximum=1),
        ConfigDefinition("rag_fallback_candidate_limit", "Fallback Candidate Limit", "rag", int, minimum=50, maximum=10000),
        ConfigDefinition("rag_parser_backend", "Parser Backend", "rag", str),
        ConfigDefinition("rag_parser_fallback_enabled", "Parser Fallback Enabled", "rag", bool),
        ConfigDefinition("docling_serve_url", "Docling Serve URL", "rag", str),
        ConfigDefinition("docling_serve_api_key", "Docling Serve API Key", "rag", str, secret=True),
        ConfigDefinition("docling_timeout_seconds", "Docling Timeout Seconds", "rag", float, minimum=10, maximum=1800),
        ConfigDefinition("docling_do_ocr", "Docling OCR Enabled", "rag", bool),
        ConfigDefinition("rag_max_uncompressed_mb", "Maximum Uncompressed MB", "rag", int, minimum=10, maximum=2000),
        ConfigDefinition("rag_max_document_chars", "Maximum Document Characters", "rag", int, minimum=10000, maximum=20000000),
        ConfigDefinition("rag_max_pdf_pages", "Maximum PDF Pages", "rag", int, minimum=1, maximum=5000),
        ConfigDefinition("rag_max_elements", "Maximum Document Elements", "rag", int, minimum=100, maximum=500000),
        ConfigDefinition("rag_max_chunks", "Maximum Document Chunks", "rag", int, minimum=10, maximum=100000),
        ConfigDefinition("knowledge_max_attempts", "Index Max Attempts", "rag", int, minimum=1, maximum=10),
        ConfigDefinition("welcome_ai_tokens", "Welcome Tokens", "billing", int, minimum=0, maximum=1_000_000),
        ConfigDefinition("chat_token_cost", "Chat Token Cost", "billing", int, minimum=1, maximum=10_000),
        ConfigDefinition("discussion_token_cost", "Team Discussion Cost", "billing", int, minimum=1, maximum=50_000),
        ConfigDefinition("workflow_token_cost", "Workflow Token Cost", "billing", int, minimum=1, maximum=100_000),
        ConfigDefinition("recharge_tokens_per_yuan", "Tokens Per Yuan", "billing", int, minimum=1, maximum=100_000),
        ConfigDefinition("allow_registration", "Allow Registration", "registration", bool),
        ConfigDefinition("registration_email_domains", "Registration Domains", "registration", list),
        ConfigDefinition("notification_poll_seconds", "Notification Poll Seconds", "notification", int, minimum=1, maximum=300),
        ConfigDefinition("notification_max_attempts", "Notification Max Attempts", "notification", int, minimum=1, maximum=10),
        ConfigDefinition("smtp_host", "SMTP Host", "notification", str),
        ConfigDefinition("smtp_port", "SMTP Port", "notification", int, minimum=1, maximum=65535),
        ConfigDefinition("smtp_username", "SMTP Username", "notification", str),
        ConfigDefinition("smtp_password", "SMTP Password", "notification", str, secret=True),
        ConfigDefinition("smtp_from_email", "SMTP From Email", "notification", str),
        ConfigDefinition("smtp_starttls", "SMTP STARTTLS", "notification", bool),
        ConfigDefinition("agent_concurrency_acquire_timeout", "Agent Acquire Timeout", "runtime", float, minimum=0.1, maximum=30),
        ConfigDefinition("agent_concurrency_lease_seconds", "Agent Lease Seconds", "runtime", int, minimum=30, maximum=900),
        ConfigDefinition("workflow_lease_seconds", "Workflow Lease Seconds", "runtime", int, minimum=60, maximum=7200),
        ConfigDefinition("workflow_max_attempts", "Workflow Max Attempts", "runtime", int, minimum=1, maximum=10),
        ConfigDefinition(
            "workflow_compensation_max_attempts",
            "Workflow Compensation Max Attempts",
            "runtime",
            int,
            minimum=1,
            maximum=10,
        ),
    )
}
BASE_VALUES = {key: getattr(settings, key) for key in CONFIG_DEFINITIONS}
MASKED_SECRET = "********"


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _serialize(definition: ConfigDefinition, value: Any) -> str:
    if definition.secret:
        encrypted = _fernet().encrypt(str(value).encode("utf-8")).decode("ascii")
        return json.dumps({"encrypted": encrypted})
    return json.dumps(value, ensure_ascii=False)


def _deserialize(definition: ConfigDefinition, value_json: str) -> Any:
    value = json.loads(value_json)
    if not definition.secret:
        return value
    try:
        return _fernet().decrypt(value["encrypted"].encode("ascii")).decode("utf-8")
    except (InvalidToken, KeyError, TypeError) as exc:
        raise ValueError(f"Cannot decrypt runtime setting: {definition.key}") from exc


def validate_runtime_value(definition: ConfigDefinition, value: Any) -> Any:
    if definition.value_type is bool:
        if type(value) is not bool:
            raise ValueError("must be true or false")
    elif definition.value_type is int:
        if type(value) is not int:
            raise ValueError("must be an integer")
    elif definition.value_type is float:
        if type(value) not in {int, float}:
            raise ValueError("must be a number")
        value = float(value)
    elif definition.value_type is str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must be a non-empty string")
        value = value.strip()
    elif definition.value_type is list:
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValueError("must be a list of strings")
        value = [item.strip() for item in value if item.strip()]
    if definition.minimum is not None and value < definition.minimum:
        raise ValueError(f"must be at least {definition.minimum}")
    if definition.maximum is not None and value > definition.maximum:
        raise ValueError(f"must be at most {definition.maximum}")
    return value


def restore_runtime_defaults() -> None:
    for key, value in BASE_VALUES.items():
        setattr(settings, key, value)


def apply_runtime_settings(db: Session) -> None:
    restore_runtime_defaults()
    rows = list(db.scalars(select(SystemSettingOverride)))
    for row in rows:
        definition = CONFIG_DEFINITIONS.get(row.key)
        if not definition:
            continue
        try:
            setattr(settings, row.key, _deserialize(definition, row.value_json))
        except Exception:
            logger.exception("Invalid runtime setting ignored: %s", row.key)


def update_runtime_settings(db: Session, values: dict[str, Any], user_id: int) -> list[str]:
    normalized: dict[str, Any] = {}
    for key, value in values.items():
        definition = CONFIG_DEFINITIONS.get(key)
        if not definition:
            raise ValueError(f"Setting is not runtime configurable: {key}")
        if definition.secret and value == MASKED_SECRET:
            continue
        normalized[key] = None if value is None else validate_runtime_value(definition, value)
    chunk_size = normalized.get("rag_chunk_size", settings.rag_chunk_size)
    chunk_overlap = normalized.get("rag_chunk_overlap", settings.rag_chunk_overlap)
    if chunk_size is not None and chunk_overlap is not None and chunk_overlap >= chunk_size:
        raise ValueError("RAG chunk overlap must be smaller than chunk size")
    child_tokens = normalized.get("rag_child_chunk_tokens", settings.rag_child_chunk_tokens)
    parent_tokens = normalized.get("rag_parent_chunk_tokens", settings.rag_parent_chunk_tokens)
    overlap_tokens = normalized.get("rag_chunk_overlap_tokens", settings.rag_chunk_overlap_tokens)
    minimum_tokens = normalized.get("rag_min_chunk_tokens", settings.rag_min_chunk_tokens)
    if parent_tokens < child_tokens:
        raise ValueError("RAG parent token budget must not be smaller than child token budget")
    if overlap_tokens >= child_tokens:
        raise ValueError("RAG token overlap must be smaller than child token budget")
    if minimum_tokens > child_tokens:
        raise ValueError("RAG minimum chunk tokens must not exceed child token budget")
    parser_backend = normalized.get("rag_parser_backend", settings.rag_parser_backend)
    if parser_backend not in {"native", "auto", "docling"}:
        raise ValueError("RAG parser backend must be native, auto or docling")

    changed: list[str] = []
    for key, value in normalized.items():
        definition = CONFIG_DEFINITIONS[key]
        row = db.scalar(select(SystemSettingOverride).where(SystemSettingOverride.key == key))
        if value is None:
            if row:
                db.delete(row)
                changed.append(key)
            continue
        if row is None:
            row = SystemSettingOverride(key=key, value_json="null")
            db.add(row)
        row.value_json = _serialize(definition, value)
        row.is_secret = definition.secret
        row.updated_by_user_id = user_id
        changed.append(key)
    db.flush()
    apply_runtime_settings(db)
    return sorted(changed)


def runtime_setting_items(db: Session) -> list[dict[str, Any]]:
    apply_runtime_settings(db)
    rows = {row.key: row for row in db.scalars(select(SystemSettingOverride))}
    items: list[dict[str, Any]] = []
    for key, definition in CONFIG_DEFINITIONS.items():
        row = rows.get(key)
        effective = getattr(settings, key)
        source = "database" if row else ("environment" if key.upper() in os.environ else "default")
        items.append(
            {
                "key": key,
                "label": definition.label,
                "category": definition.category,
                "value": None if definition.secret else effective,
                "value_type": definition.value_type.__name__,
                "minimum": definition.minimum,
                "maximum": definition.maximum,
                "secret": definition.secret,
                "configured": bool(effective) if definition.secret else True,
                "source": source,
                "restart_required": definition.restart_required,
                "updated_at": row.updated_at if row else None,
            }
        )
    return items


class RuntimeConfigRefresher:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="runtime-config-refresher")

    async def stop(self) -> None:
        if not self._task:
            return
        self._stop.set()
        await self._task
        self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                with SessionLocal() as db:
                    apply_runtime_settings(db)
            except Exception:
                logger.exception("Runtime settings refresh failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=15)
            except TimeoutError:
                pass


runtime_config_refresher = RuntimeConfigRefresher()
