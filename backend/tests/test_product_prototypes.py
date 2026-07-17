import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.agent.service import ensure_default_agents
from app.api.routes.prototypes import (
    activate_prototype_version,
    generate_prototype,
    get_prototype,
    list_prototypes,
    regenerate_prototype,
)
from app.models import ProductPrototypeVersion, Project, ProjectMember, ProjectMemberRole, Requirement, User
from app.prototypes.schemas import (
    PrototypeGenerateRequest,
    PrototypeRegenerateRequest,
    PrototypeSpecification,
)
from app.prototypes.service import build_fallback_spec, evaluate_specification


def http_request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
    )


def prototype_context(db: Session) -> tuple[User, Project, Requirement]:
    ensure_default_agents(db)
    user = User(
        email="prototype@example.com",
        name="Prototype Owner",
        password_hash="hash",
        permissions="agents:read,projects:write",
    )
    db.add(user)
    db.flush()
    project = Project(name="Idol Bubble", owner_id=user.id)
    db.add(project)
    db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role=ProjectMemberRole.owner))
    requirement = Requirement(
        project_id=project.id,
        user_id=user.id,
        title="手机号注册与邀请裂变",
        content="实现手机号注册登录、忘记密码、邀请链接和邀请记录。",
        analysis="需要五个核心界面和完整点击路径。",
        status="ANALYZED",
    )
    db.add(requirement)
    db.commit()
    return user, project, requirement


def test_prototype_schema_rejects_unknown_navigation_target() -> None:
    valid = build_fallback_spec("Test", "手机号注册登录和邀请链接")
    payload = valid.model_dump(mode="json")
    payload["screens"][0]["sections"][0]["components"][-1]["action"]["target"] = "missing"

    with pytest.raises(ValidationError):
        PrototypeSpecification.model_validate(payload)


def test_fallback_auth_prototype_has_complete_reachable_flow() -> None:
    spec = build_fallback_spec("偶像泡泡", "手机号注册登录、忘记密码与邀请裂变链接")
    quality = evaluate_specification(spec)

    assert [screen.id for screen in spec.screens] == [
        "register",
        "login",
        "reset-password",
        "invite",
        "invite-records",
    ]
    assert quality["passed"] is True
    assert quality["checks"][0]["passed"] is True


@pytest.mark.asyncio
async def test_multi_agent_generation_persists_versions_and_allows_restore(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, project, requirement = prototype_context(db)
    calls: list[str] = []

    class FakeLLM:
        async def chat(self, system_prompt: str, prompt: str, *_args) -> str:
            calls.append(system_prompt)
            if "质量评审" in system_prompt:
                return "路径完整，表单标签清晰，建议补充验证码频控说明。"
            if "交互架构师" in system_prompt:
                return "invalid provider JSON triggers validated fallback"
            return "目标用户为粉丝，核心路径覆盖注册、登录、重置密码和邀请裂变。"

    class FakeLease:
        async def release(self) -> None:
            return None

    async def fake_slot(*_args):
        return FakeLease()

    monkeypatch.setattr("app.prototypes.service.get_llm", lambda: FakeLLM())
    monkeypatch.setattr("app.prototypes.service.acquire_agent_slot", fake_slot)
    created = await generate_prototype(
        PrototypeGenerateRequest(
            project_id=project.id,
            requirement_id=requirement.id,
            title="偶像泡泡 - 注册登录与邀请裂变",
            prompt="请生成手机号注册登录、忘记密码与邀请裂变链接的可交互产品原型。",
        ),
        http_request("/api/v1/prototypes/generate"),
        user,
        db,
    )

    assert created.active_version == 1
    assert created.screen_count == 5
    assert created.current.generation_mode == "MULTI_AGENT_TEMPLATE_FALLBACK"
    assert created.current.quality["passed"] is True
    assert len(created.current.agent_trace) == 3
    assert len(calls) == 3

    regenerated = await regenerate_prototype(
        created.id,
        PrototypeRegenerateRequest(feedback="邀请记录增加奖励状态"),
        http_request(f"/api/v1/prototypes/{created.id}/regenerate"),
        user,
        db,
    )
    assert regenerated.active_version == 2
    assert [version.version for version in regenerated.versions] == [2, 1]
    assert "邀请记录增加奖励状态" in regenerated.current.source_prompt
    assert db.scalar(
        select(func.count(ProductPrototypeVersion.id)).where(
            ProductPrototypeVersion.prototype_id == created.id
        )
    ) == 2

    restored = activate_prototype_version(
        created.id,
        1,
        http_request(f"/api/v1/prototypes/{created.id}/versions/1/activate"),
        user,
        db,
    )
    assert restored.active_version == 1
    assert restored.current.version == 1
    assert get_prototype(created.id, user, db).current.version == 1
    assert [item.id for item in list_prototypes(project.id, requirement.id, user, db)] == [created.id]
