from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Agent, EvaluationCase


CORE_EVALUATION_ROLES = (
    "product_manager",
    "architect",
    "test_engineer",
    "operations_analyst",
    "project_manager",
)


def _role_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def evaluation_suite_coverage(
    db: Session,
    case_snapshots: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    configured_roles = {_role_value(role) for role in db.scalars(select(Agent.role))}
    required_roles = [role for role in CORE_EVALUATION_ROLES if role in configured_roles]
    if case_snapshots is None:
        rows = db.execute(
            select(EvaluationCase.agent_role, func.count(EvaluationCase.id))
            .where(EvaluationCase.enabled.is_(True))
            .group_by(EvaluationCase.agent_role)
        )
        case_counts = Counter({_role_value(role): int(count) for role, count in rows})
    else:
        case_counts = Counter(
            str(snapshot.get("agent_role") or "")
            for snapshot in case_snapshots
            if snapshot.get("agent_role")
        )
    covered_roles = [role for role in required_roles if case_counts[role] > 0]
    missing_roles = [role for role in required_roles if case_counts[role] == 0]
    coverage_percent = round(len(covered_roles) / len(required_roles), 4) if required_roles else 1.0
    return {
        "required_roles": required_roles,
        "covered_roles": covered_roles,
        "missing_roles": missing_roles,
        "case_counts": {role: case_counts[role] for role in required_roles},
        "total_enabled_cases": sum(case_counts.values()),
        "coverage_percent": coverage_percent,
        "gate_ready": not missing_roles,
    }


def coverage_failure_message(coverage: Mapping[str, Any]) -> str:
    missing = ", ".join(str(role) for role in coverage.get("missing_roles", []))
    return f"Evaluation suite is missing enabled cases for required multi-Agent roles: {missing}"
