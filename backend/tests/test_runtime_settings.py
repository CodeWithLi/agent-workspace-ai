import json

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.api.routes.settings import get_system_settings, test_system_connection as check_system_connection, update_system_settings
from app.core.config import get_settings
from app.core.runtime_config import restore_runtime_defaults
from app.models import AuditLog, SystemSettingOverride, User, UserRole
from app.schemas import SettingConnectionTestRequest, SettingUpdate


def request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "PATCH",
            "path": "/api/v1/settings",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 1234),
        }
    )


def test_runtime_settings_are_validated_masked_encrypted_and_audited(db: Session) -> None:
    admin = User(email="settings@example.com", name="Settings", password_hash="hash", role=UserRole.admin)
    db.add(admin)
    db.commit()
    try:
        result = update_system_settings(
            SettingUpdate(
                values={
                    "llm_model": "glm-settings-test",
                    "chat_token_cost": 17,
                    "rag_top_k": 8,
                    "llm_api_key": "runtime-secret-value",
                }
            ),
            request(),
            admin,
            db,
        )
        items = {item.key: item for item in result.items}
        assert items["llm_model"].value == "glm-settings-test"
        assert items["chat_token_cost"].value == 17
        assert items["llm_api_key"].value is None
        assert items["llm_api_key"].configured is True
        assert get_settings().llm_model == "glm-settings-test"
        assert get_settings().chat_token_cost == 17

        secret_row = db.scalar(select(SystemSettingOverride).where(SystemSettingOverride.key == "llm_api_key"))
        assert "runtime-secret-value" not in secret_row.value_json
        assert json.loads(secret_row.value_json)["encrypted"].startswith("gAAAA")
        audit = db.scalar(select(AuditLog).where(AuditLog.action == "settings.update"))
        assert set(json.loads(audit.details)["keys"]) == {
            "chat_token_cost",
            "llm_api_key",
            "llm_model",
            "rag_top_k",
        }

        preserved = update_system_settings(
            SettingUpdate(values={"llm_api_key": "********"}),
            request(),
            admin,
            db,
        )
        assert {item.key: item for item in preserved.items}["llm_api_key"].configured is True

        with pytest.raises(HTTPException) as error:
            update_system_settings(SettingUpdate(values={"database_url": "sqlite:///unsafe"}), request(), admin, db)
        assert error.value.status_code == 400

        with pytest.raises(HTTPException) as invalid_strategy:
            update_system_settings(SettingUpdate(values={"rag_chunk_strategy": "unknown"}), request(), admin, db)
        assert invalid_strategy.value.status_code == 400
    finally:
        restore_runtime_defaults()


@pytest.mark.asyncio
async def test_llm_connection_check_uses_effective_runtime_settings(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = User(email="connection@example.com", name="Connection", password_hash="hash", role=UserRole.admin)
    db.add(admin)
    db.commit()

    async def fake_chat(_system: str, _prompt: str, *_args) -> str:
        return "connection-ok"

    monkeypatch.setattr(
        "app.api.routes.settings.get_llm",
        lambda: type("Gateway", (), {"api_key": "test-key", "chat": fake_chat})(),
    )
    result = await check_system_connection(SettingConnectionTestRequest(target="llm"), admin, db)
    assert result.ok is True
    assert result.target == "llm"


def test_settings_get_returns_categories_and_sources(db: Session) -> None:
    admin = User(email="settings-list@example.com", name="Settings List", password_hash="hash", role=UserRole.admin)
    db.add(admin)
    db.commit()
    result = get_system_settings(admin, db)
    items = {item.key: item for item in result.items}
    assert items["llm_model"].category == "model"
    assert items["workflow_max_attempts"].category == "runtime"
    assert items["smtp_password"].secret is True
