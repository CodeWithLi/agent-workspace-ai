import logging
from contextlib import asynccontextmanager

import redis
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.agent.service import ensure_default_agents
from app.api import api_router
from app.core.config import get_settings
from app.core.database import SessionLocal, engine, init_db
from app.core.logging import configure_logging
from app.core.llm import LLMGatewayError
from app.services.notifications import notification_dispatcher
from app.admin import router as admin_router
from app.services.agent_run_reaper import agent_run_reaper


settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    if settings.auto_create_schema:
        init_db()
    with SessionLocal() as db:
        ensure_default_agents(db)
    logger.info("Application started")
    await notification_dispatcher.start()
    await agent_run_reaper.start()
    try:
        yield
    finally:
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


@app.get("/health/ready")
def readiness() -> JSONResponse:
    components: dict[str, str] = {}
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        components["database"] = "ok"
    except Exception:
        components["database"] = "unavailable"
    try:
        redis.from_url(settings.redis_url).ping()
        components["redis"] = "ok"
    except Exception:
        components["redis"] = "unavailable"
    ready = all(value == "ok" for value in components.values())
    return JSONResponse(status_code=200 if ready else 503, content={"status": "ready" if ready else "not_ready", "components": components})


app.include_router(api_router, prefix=settings.api_prefix)
app.include_router(admin_router)
