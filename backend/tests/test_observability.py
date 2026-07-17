import json
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.health import is_ready
from app.core.logging import JsonFormatter
from app.core.metrics import render_metrics
from app.core.request_context import request_id_context
from app.main import request_observability


def test_json_logging_contains_request_context() -> None:
    token = request_id_context.set("request-test-id")
    try:
        record = logging.LogRecord("test", logging.INFO, __file__, 1, "completed", (), None)
        record.status_code = 200
        payload = json.loads(JsonFormatter().format(record))
    finally:
        request_id_context.reset(token)
    assert payload["request_id"] == "request-test-id"
    assert payload["status_code"] == 200
    assert payload["message"] == "completed"


def test_request_middleware_returns_and_preserves_request_id() -> None:
    app = FastAPI()
    app.middleware("http")(request_observability)

    @app.get("/probe")
    def probe():
        return {"ok": True}

    with TestClient(app) as client:
        response = client.get("/probe", headers={"X-Request-ID": "trace-123"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "trace-123"


def test_readiness_policy_and_prometheus_output() -> None:
    assert is_ready({"database": "ok", "redis": "ok", "minio": "ok", "milvus": "fallback", "llm": "ok"})
    assert not is_ready({"database": "ok", "redis": "unavailable", "minio": "ok", "milvus": "ok", "llm": "ok"})
    content, content_type = render_metrics()
    assert b"agent_workspace_http_requests_total" in content
    assert b"agent_workspace_rag_search_duration_seconds" in content
    assert b"agent_workspace_rag_index_duration_seconds" in content
    assert b"agent_workspace_rag_embedding_chunks_total" in content
    assert "text/plain" in content_type
