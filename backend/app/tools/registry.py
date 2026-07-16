from __future__ import annotations

from typing import Any, Callable

from sqlalchemy.orm import Session

from app.tools.project_tools import (
    analytics_report,
    architecture_generate,
    context_search,
    meeting_summary,
    notification_create,
    report_generate,
    requirement_create,
    task_create,
    testcase_create,
)


ToolHandler = Callable[..., Any]


TOOL_REGISTRY: dict[str, ToolHandler] = {
    "context_search": context_search,
    "knowledge_search": lambda **kwargs: kwargs,
    "task_create": task_create,
    "requirement_create": requirement_create,
    "report_generate": report_generate,
    "notification_create": notification_create,
    "meeting_summary": meeting_summary,
    "architecture_generate": architecture_generate,
    "testcase_create": testcase_create,
    "analytics_report": analytics_report,
}


AGENT_TOOL_ALLOWLIST: dict[str, set[str]] = {
    "product_manager": {"context_search", "knowledge_search", "requirement_create"},
    "project_manager": {"context_search", "task_create", "report_generate", "notification_create"},
    "architect": {"context_search", "knowledge_search", "architecture_generate"},
    "test_engineer": {"context_search", "testcase_create"},
    "meeting_summarizer": {"context_search", "meeting_summary", "notification_create", "requirement_create", "task_create"},
    "knowledge_admin": {"context_search", "knowledge_search"},
    "notification_secretary": {"context_search", "notification_create"},
    "operations_analyst": {"context_search", "analytics_report", "report_generate"},
}


def allowed_tools_for_role(role: str) -> set[str]:
    return AGENT_TOOL_ALLOWLIST.get(role, set())


def list_tools() -> list[dict[str, str]]:
    return [{"name": name, "description": handler.__doc__ or ""} for name, handler in TOOL_REGISTRY.items()]


def run_tool(name: str, db: Session | None = None, **kwargs: Any) -> Any:
    handler = TOOL_REGISTRY[name]
    if name in {"task_create", "analytics_report", "context_search"}:
        if db is None:
            raise ValueError(f"Tool {name} requires database session")
        return handler(db=db, **kwargs)
    return handler(**kwargs)
