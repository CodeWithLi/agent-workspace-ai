from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes import auth
from app.core.database import Base, get_db
from app.models import AuditLog, UserSession


def test_refresh_token_rotation_and_logout_revocation() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(auth.router, prefix="/api/v1/auth")

    def override_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        registered = client.post(
            "/api/v1/auth/register",
            json={"email": "session@example.com", "name": "Session User", "password": "StrongPass123"},
        )
        assert registered.status_code == 200
        assert registered.json()["expires_in"] > 0
        assert "agent_workspace_refresh" in client.cookies

        refreshed = client.post("/api/v1/auth/refresh")
        assert refreshed.status_code == 200
        assert refreshed.json()["access_token"] != registered.json()["access_token"]

        with Session(engine) as db:
            assert db.scalar(select(func.count(UserSession.id))) == 2
            assert db.scalar(select(func.count(UserSession.id)).where(UserSession.revoked_at.is_not(None))) == 1
            assert db.scalar(select(func.count(AuditLog.id)).where(AuditLog.action == "auth.refresh")) == 1

        logged_out = client.post("/api/v1/auth/logout")
        assert logged_out.status_code == 204
        assert client.post("/api/v1/auth/refresh").status_code == 401

    Base.metadata.drop_all(engine)
