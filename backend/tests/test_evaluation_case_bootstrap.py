import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.api.routes.evaluations import bootstrap_evaluation_cases
from app.models import Agent, AgentRole, AuditLog, EvaluationCase, User, UserRole
from app.services.evaluation_case_bootstrap import BASELINE_CASE_TEMPLATES


def request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/evaluations/cases/bootstrap",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 1234),
        }
    )


def seed_bootstrap(db: Session) -> tuple[User, EvaluationCase]:
    admin = User(
        email="bootstrap-admin@example.com",
        name="Bootstrap Admin",
        password_hash="hash",
        role=UserRole.admin,
    )
    agents = [
        Agent(
            name=f"Bootstrap {role.value}",
            role=role,
            description=f"{role.value} Agent",
            system_prompt=f"{role.value} prompt",
            model="test-model",
            tools="",
            current_version=1,
        )
        for role in (
            AgentRole.product_manager,
            AgentRole.architect,
            AgentRole.test_engineer,
        )
    ]
    custom = EvaluationCase(
        name="Custom architecture regression",
        agent_role=AgentRole.architect.value,
        input_text="Review an existing architecture",
        expected_keywords_json=json.dumps(["architecture"]),
        forbidden_keywords_json="[]",
        rubric="Preserve this administrator-authored case.",
        minimum_score=0.8,
        weight=2,
        enabled=True,
        created_by_user_id=None,
    )
    db.add_all([admin, *agents, custom])
    db.commit()
    return admin, custom


def test_baseline_templates_cover_every_core_role() -> None:
    assert set(BASELINE_CASE_TEMPLATES) == {
        AgentRole.product_manager.value,
        AgentRole.architect.value,
        AgentRole.test_engineer.value,
        AgentRole.operations_analyst.value,
        AgentRole.project_manager.value,
    }
    assert all(template["expected_keywords"] for template in BASELINE_CASE_TEMPLATES.values())
    assert all(template["rubric"] for template in BASELINE_CASE_TEMPLATES.values())


def test_bootstrap_only_creates_missing_roles_and_is_idempotent(db: Session) -> None:
    admin, custom = seed_bootstrap(db)

    first = bootstrap_evaluation_cases(request(), admin, db)
    second = bootstrap_evaluation_cases(request(), admin, db)

    assert set(first.created_roles) == {
        AgentRole.product_manager.value,
        AgentRole.test_engineer.value,
    }
    assert len(first.created_case_ids) == 2
    assert first.coverage.gate_ready is True
    assert first.coverage.covered_roles == [
        AgentRole.product_manager.value,
        AgentRole.architect.value,
        AgentRole.test_engineer.value,
    ]
    assert second.created_roles == []
    assert second.created_case_ids == []
    assert db.get(EvaluationCase, custom.id).name == "Custom architecture regression"
    assert db.scalar(select(func.count(EvaluationCase.id))) == 3
    assert db.scalar(
        select(func.count(AuditLog.id)).where(AuditLog.action == "evaluation.case_bootstrap")
    ) == 1
