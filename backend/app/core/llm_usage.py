import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import LLMUsage


logger = logging.getLogger(__name__)
settings = get_settings()
_usage_context: ContextVar[dict[str, Any]] = ContextVar("llm_usage_context", default={})


def estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def calculate_cost_micros(
    input_tokens: int,
    output_tokens: int,
    *,
    input_rate: float,
    output_rate: float,
) -> int:
    return int(round(input_tokens * input_rate + output_tokens * output_rate))


@contextmanager
def bind_llm_usage(**values: Any) -> Iterator[None]:
    token = _usage_context.set({**_usage_context.get(), **values})
    try:
        yield
    finally:
        _usage_context.reset(token)


def record_llm_usage(
    operation: str,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
    *,
    usage_source: str,
) -> None:
    if operation == "embedding":
        cost = calculate_cost_micros(
            input_tokens,
            0,
            input_rate=settings.embedding_cost_per_million,
            output_rate=0,
        )
    elif operation == "rerank":
        cost = calculate_cost_micros(
            input_tokens,
            0,
            input_rate=settings.reranker_cost_per_million,
            output_rate=0,
        )
    else:
        cost = calculate_cost_micros(
            input_tokens,
            output_tokens,
            input_rate=settings.llm_input_cost_per_million,
            output_rate=settings.llm_output_cost_per_million,
        )
    context: dict[str, Any] = _usage_context.get()
    if not context:
        return
    item = LLMUsage(
        user_id=context.get("user_id"),
        project_id=context.get("project_id"),
        agent_id=context.get("agent_id"),
        workflow_id=context.get("workflow_id"),
        agent_run_id=context.get("agent_run_id"),
        operation=operation,
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        estimated_cost_micros=cost,
        latency_ms=max(0, latency_ms),
        usage_source=usage_source,
    )
    try:
        bound_db = context.get("db")
        if bound_db is not None:
            bound_db.add(item)
            bound_db.flush()
        else:
            with SessionLocal() as db:
                db.add(item)
                db.commit()
    except Exception:
        logger.exception("Failed to persist LLM usage")
