import logging
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response

from app.agent.service import ensure_default_agents
from app.api import api_router
from app.core.config import get_settings
from app.core.database import SessionLocal, init_db
from app.core.logging import configure_logging
from app.core.llm import LLMGatewayError
from app.services.notifications import notification_dispatcher
from app.services.prototype_generations import prototype_generation_dispatcher
from app.admin import router as admin_router
from app.services.agent_run_reaper import agent_run_reaper
from app.services.workflows import workflow_dispatcher
from app.core.runtime_config import apply_runtime_settings, runtime_config_refresher
from app.services.knowledge import knowledge_dispatcher
from app.core.health import is_ready, readiness_components
from app.core.metrics import (
    HTTP_DURATION,
    HTTP_IN_PROGRESS,
    HTTP_REQUESTS,
    KNOWLEDGE_QUEUE,
    NOTIFICATION_QUEUE,
    PROTOTYPE_GENERATION_QUEUE,
    SAGA_STEP_GAUGE,
    WORKFLOW_QUEUE,
    render_metrics,
)
from app.core.request_context import request_id_context
from app.models import (
    KnowledgeDocument,
    Notification,
    PrototypeGenerationJob,
    WorkflowRun,
    WorkflowSagaStep,
)
from sqlalchemy import func, select


settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    if settings.auto_create_schema:
        init_db()
    with SessionLocal() as db:
        apply_runtime_settings(db)
        ensure_default_agents(db)
    logger.info("Application started")
    await notification_dispatcher.start()
    await agent_run_reaper.start()
    await workflow_dispatcher.start()
    await prototype_generation_dispatcher.start()
    await runtime_config_refresher.start()
    await knowledge_dispatcher.start()
    try:
        yield
    finally:
        await knowledge_dispatcher.stop()
        await runtime_config_refresher.stop()
        await prototype_generation_dispatcher.stop()
        await workflow_dispatcher.stop()
        await notification_dispatcher.stop()
        await agent_run_reaper.stop()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

if settings.environment == "production":
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_observability(request: Request, call_next):
    request_id = request.headers.get("x-request-id", "").strip()[:64] or str(uuid4())
    token = request_id_context.set(request_id)
    method = request.method
    started = perf_counter()
    status_code = 500
    HTTP_IN_PROGRESS.labels(method=method).inc()
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        duration = perf_counter() - started
        route = getattr(request.scope.get("route"), "path", "unmatched")
        HTTP_IN_PROGRESS.labels(method=method).dec()
        HTTP_REQUESTS.labels(method=method, route=route, status=str(status_code)).inc()
        HTTP_DURATION.labels(method=method, route=route).observe(duration)
        logger.info(
            "request.completed",
            extra={
                "method": method,
                "path": route,
                "status_code": status_code,
                "duration_ms": round(duration * 1000, 2),
            },
        )
        request_id_context.reset(token)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if settings.environment == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.exception_handler(LLMGatewayError)
async def llm_exception_handler(_: Request, exc: LLMGatewayError) -> JSONResponse:
    logger.warning("LLM provider unavailable: %s", exc)
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/live")
def liveness() -> dict[str, str]:
    return {"status": "alive"}


@app.get("/health/ready")
def readiness() -> JSONResponse:
    components = readiness_components()
    ready = is_ready(components)
    return JSONResponse(status_code=200 if ready else 503, content={"status": "ready" if ready else "not_ready", "components": components})


@app.get("/metrics")
def metrics() -> Response:
    if not settings.metrics_enabled:
        return Response(status_code=404)
    with SessionLocal() as db:
        for status_value, count in db.execute(select(WorkflowRun.status, func.count()).group_by(WorkflowRun.status)):
            label = status_value.value if hasattr(status_value, "value") else str(status_value)
            WORKFLOW_QUEUE.labels(status=label).set(count)
        for status_value, count in db.execute(select(KnowledgeDocument.status, func.count()).group_by(KnowledgeDocument.status)):
            KNOWLEDGE_QUEUE.labels(status=str(status_value)).set(count)
        for status_value, count in db.execute(select(Notification.status, func.count()).group_by(Notification.status)):
            NOTIFICATION_QUEUE.labels(status=str(status_value)).set(count)
        for status_value, count in db.execute(
            select(PrototypeGenerationJob.status, func.count()).group_by(
                PrototypeGenerationJob.status
            )
        ):
            label = status_value.value if hasattr(status_value, "value") else str(status_value)
            PROTOTYPE_GENERATION_QUEUE.labels(status=label).set(count)
        for status_value, count in db.execute(
            select(WorkflowSagaStep.status, func.count()).group_by(WorkflowSagaStep.status)
        ):
            label = status_value.value if hasattr(status_value, "value") else str(status_value)
            SAGA_STEP_GAUGE.labels(status=label).set(count)
    content, content_type = render_metrics()
    return Response(content=content, media_type=content_type)


app.include_router(api_router, prefix=settings.api_prefix)
app.include_router(admin_router)
