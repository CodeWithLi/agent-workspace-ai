import json

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.agent.service import ensure_default_agents
from app.api.routes.prototypes import (
    activate_prototype_version,
    add_prototype_comment,
    generate_prototype,
    get_prototype,
    list_prototypes,
    list_prototype_comments,
    materialize_prototype,
    regenerate_prototype,
    update_prototype,
    update_prototype_comment,
)
from app.models import (
    ProductPrototype,
    ProductPrototypeMaterialization,
    ProductPrototypeVersion,
    PrototypeReviewComment,
    PrototypeTestCase,
    Project,
    ProjectMember,
    ProjectMemberRole,
    Requirement,
    Task,
    User,
)
from app.prototypes.schemas import (
    PrototypeCommentCreate,
    PrototypeCommentUpdate,
    PrototypeGenerateRequest,
    PrototypeMaterializeRequest,
    PrototypeRegenerateRequest,
    PrototypeSpecification,
    PrototypeUpdateRequest,
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

    stored = db.get(ProductPrototype, created.id)
    assert stored is not None
    stored.status = "APPROVED"
    db.commit()
    restored = activate_prototype_version(
        created.id,
        1,
        http_request(f"/api/v1/prototypes/{created.id}/versions/1/activate"),
        user,
        db,
    )
    assert restored.active_version == 1
    assert restored.current.version == 1
    assert restored.status == "DRAFT"
    assert get_prototype(created.id, user, db).current.version == 1
    assert [item.id for item in list_prototypes(project.id, requirement.id, user, db)] == [created.id]


def test_review_gate_and_materialization_are_traceable_and_idempotent(db: Session) -> None:
    user, project, requirement = prototype_context(db)
    specification = build_fallback_spec("偶像泡泡", "手机号注册登录和邀请链接")
    prototype = ProductPrototype(
        project_id=project.id,
        requirement_id=requirement.id,
        created_by_user_id=user.id,
        title="评审中的产品原型",
        summary=specification.summary,
        status="REVIEW",
        active_version=1,
    )
    db.add(prototype)
    db.flush()
    db.add(
        ProductPrototypeVersion(
            prototype_id=prototype.id,
            version=1,
            source_prompt="生成认证与邀请原型",
            specification_json=specification.model_dump_json(),
            agent_trace_json="[]",
            quality_json=json.dumps({"score": 100, "passed": True, "checks": [], "issues": []}),
            generation_mode="MULTI_AGENT",
            created_by_user_id=user.id,
        )
    )
    db.commit()

    comment = add_prototype_comment(
        prototype.id,
        PrototypeCommentCreate(screen_id="register", body="请补充手机号格式错误状态。"),
        http_request(f"/api/v1/prototypes/{prototype.id}/comments"),
        user,
        db,
    )
    assert comment.status == "OPEN"
    assert [item.id for item in list_prototype_comments(prototype.id, None, user, db)] == [comment.id]

    with pytest.raises(HTTPException) as approval_error:
        update_prototype(
            prototype.id,
            PrototypeUpdateRequest(status="APPROVED"),
            http_request(f"/api/v1/prototypes/{prototype.id}"),
            user,
            db,
        )
    assert approval_error.value.status_code == 409

    resolved = update_prototype_comment(
        prototype.id,
        comment.id,
        PrototypeCommentUpdate(status="RESOLVED"),
        http_request(f"/api/v1/prototypes/{prototype.id}/comments/{comment.id}"),
        user,
        db,
    )
    assert resolved.status == "RESOLVED"
    approved = update_prototype(
        prototype.id,
        PrototypeUpdateRequest(status="APPROVED"),
        http_request(f"/api/v1/prototypes/{prototype.id}"),
        user,
        db,
    )
    assert approved.status == "APPROVED"

    first = materialize_prototype(
        prototype.id,
        PrototypeMaterializeRequest(request_id="prototype-materialize-001"),
        http_request(f"/api/v1/prototypes/{prototype.id}/materialize"),
        user,
        db,
    )
    repeated = materialize_prototype(
        prototype.id,
        PrototypeMaterializeRequest(request_id="prototype-materialize-002"),
        http_request(f"/api/v1/prototypes/{prototype.id}/materialize"),
        user,
        db,
    )

    assert repeated.id == first.id
    assert first.prototype_version == 1
    assert len(first.task_ids) == len(specification.screens)
    assert len(first.test_cases) > len(specification.screens)
    assert db.scalar(select(func.count(Task.id)).where(Task.source_prototype_id == prototype.id)) == len(first.task_ids)
    assert db.scalar(select(func.count(PrototypeTestCase.id)).where(PrototypeTestCase.prototype_id == prototype.id)) == len(first.test_cases)
    assert db.scalar(
        select(func.count(ProductPrototypeMaterialization.id)).where(
            ProductPrototypeMaterialization.prototype_id == prototype.id
        )
    ) == 1
    db.refresh(prototype)
    assert prototype.status == "APPROVED"
    assert db.get(PrototypeReviewComment, comment.id).resolved_by_user_id == user.id


def test_review_writes_require_editor_access_and_reopen_approval(db: Session) -> None:
    user, project, requirement = prototype_context(db)
    specification = build_fallback_spec("评审权限", "手机号注册登录和邀请链接")
    prototype = ProductPrototype(
        project_id=project.id,
        requirement_id=requirement.id,
        created_by_user_id=user.id,
        title="已批准原型",
        summary=specification.summary,
        status="APPROVED",
        active_version=1,
    )
    db.add(prototype)
    db.flush()
    db.add(
        ProductPrototypeVersion(
            prototype_id=prototype.id,
            version=1,
            source_prompt="生成评审权限原型",
            specification_json=specification.model_dump_json(),
            agent_trace_json="[]",
            quality_json=json.dumps({"score": 100, "passed": True, "checks": [], "issues": []}),
            generation_mode="MULTI_AGENT",
            created_by_user_id=user.id,
        )
    )
    viewer = User(
        email="prototype-viewer@example.com",
        name="Prototype Viewer",
        password_hash="hash",
        permissions="projects:write",
    )
    db.add(viewer)
    db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=viewer.id, role=ProjectMemberRole.viewer))
    db.commit()

    with pytest.raises(HTTPException) as viewer_error:
        add_prototype_comment(
            prototype.id,
            PrototypeCommentCreate(body="viewer 不应能写入"),
            http_request(f"/api/v1/prototypes/{prototype.id}/comments"),
            viewer,
            db,
        )
    assert viewer_error.value.status_code == 403

    comment = add_prototype_comment(
        prototype.id,
        PrototypeCommentCreate(screen_id="register", body="补充批准后的边界场景"),
        http_request(f"/api/v1/prototypes/{prototype.id}/comments"),
        user,
        db,
    )
    db.refresh(prototype)
    assert prototype.status == "REVIEW"

    update_prototype_comment(
        prototype.id,
        comment.id,
        PrototypeCommentUpdate(status="RESOLVED"),
        http_request(f"/api/v1/prototypes/{prototype.id}/comments/{comment.id}"),
        user,
        db,
    )
    update_prototype(
        prototype.id,
        PrototypeUpdateRequest(status="APPROVED"),
        http_request(f"/api/v1/prototypes/{prototype.id}"),
        user,
        db,
    )
    update_prototype_comment(
        prototype.id,
        comment.id,
        PrototypeCommentUpdate(status="OPEN"),
        http_request(f"/api/v1/prototypes/{prototype.id}/comments/{comment.id}"),
        user,
        db,
    )
    db.refresh(prototype)
    assert prototype.status == "REVIEW"


def test_materialization_request_id_cannot_be_reused_for_another_version(db: Session) -> None:
    user, project, requirement = prototype_context(db)
    specification = build_fallback_spec("交付幂等", "手机号注册登录和邀请链接")
    prototype = ProductPrototype(
        project_id=project.id,
        requirement_id=requirement.id,
        created_by_user_id=user.id,
        title="多版本交付原型",
        summary=specification.summary,
        status="APPROVED",
        active_version=1,
    )
    db.add(prototype)
    db.flush()
    for version in (1, 2):
        db.add(
            ProductPrototypeVersion(
                prototype_id=prototype.id,
                version=version,
                source_prompt=f"生成交付原型 v{version}",
                specification_json=specification.model_dump_json(),
                agent_trace_json="[]",
                quality_json=json.dumps({"score": 100, "passed": True, "checks": [], "issues": []}),
                generation_mode="MULTI_AGENT",
                created_by_user_id=user.id,
            )
        )
    db.commit()

    materialize_prototype(
        prototype.id,
        PrototypeMaterializeRequest(request_id="prototype-version-request"),
        http_request(f"/api/v1/prototypes/{prototype.id}/materialize"),
        user,
        db,
    )
    prototype.active_version = 2
    prototype.status = "APPROVED"
    db.commit()

    with pytest.raises(HTTPException) as request_error:
        materialize_prototype(
            prototype.id,
            PrototypeMaterializeRequest(request_id="prototype-version-request"),
            http_request(f"/api/v1/prototypes/{prototype.id}/materialize"),
            user,
            db,
        )
    assert request_error.value.status_code == 409


def test_list_prototypes_fetches_all_active_versions_without_n_plus_one(db: Session) -> None:
    user, project, requirement = prototype_context(db)
    specification = build_fallback_spec("列表性能", "手机号注册登录和邀请链接")
    for index in range(5):
        prototype = ProductPrototype(
            project_id=project.id,
            requirement_id=requirement.id,
            created_by_user_id=user.id,
            title=f"列表原型 {index}",
            summary=specification.summary,
            status="DRAFT",
            active_version=1,
        )
        db.add(prototype)
        db.flush()
        db.add(
            ProductPrototypeVersion(
                prototype_id=prototype.id,
                version=1,
                source_prompt="生成列表性能原型",
                specification_json=specification.model_dump_json(),
                agent_trace_json="[]",
                quality_json=json.dumps({"score": 100, "passed": True, "checks": [], "issues": []}),
                generation_mode="MULTI_AGENT",
                created_by_user_id=user.id,
            )
        )
    db.commit()
    user_id = user.id
    assert user_id > 0

    statement_count = 0

    def count_statement(*_args) -> None:
        nonlocal statement_count
        statement_count += 1

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", count_statement)
    try:
        items = list_prototypes(None, None, user, db)
    finally:
        event.remove(engine, "before_cursor_execute", count_statement)

    assert len(items) == 5
    assert statement_count == 2
