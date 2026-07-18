import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Agent,
    AgentEvaluationRelease,
    AgentPromptVersion,
    EvaluationRun,
    EvaluationSuiteRevision,
)
from app.services.agent_versions import VERSION_FIELDS, activate_version, rollback_to_version
from app.services.evaluation_coverage import coverage_failure_message, evaluation_suite_coverage


class EvaluationReleaseConflict(RuntimeError):
    pass


def _json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(value: str) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []
    return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []


def _candidate_snapshot(run: EvaluationRun) -> dict[str, Any]:
    for snapshot in _json_object(run.agent_snapshot_json).values():
        if isinstance(snapshot, dict) and snapshot.get("id") == run.candidate_agent_id:
            return snapshot
    return {}


def _validate_release_evidence(
    db: Session,
    run: EvaluationRun,
) -> tuple[Agent, AgentPromptVersion]:
    if run.status != "COMPLETED" or run.gate_passed is not True:
        raise EvaluationReleaseConflict("Evaluation release gate has not passed")
    if (
        run.baseline_run_id is None
        or run.candidate_agent_id is None
        or run.candidate_version_id is None
        or run.candidate_version is None
        or run.expected_current_version is None
    ):
        raise EvaluationReleaseConflict("Evaluation run is not a Challenger release evaluation")
    baseline = db.get(EvaluationRun, run.baseline_run_id)
    if (
        not baseline
        or baseline.status != "COMPLETED"
        or baseline.gate_passed is not True
        or baseline.suite_revision_id != run.suite_revision_id
    ):
        raise EvaluationReleaseConflict("Production baseline evidence is no longer valid")
    revision = db.get(EvaluationSuiteRevision, run.suite_revision_id) if run.suite_revision_id else None
    if not revision:
        raise EvaluationReleaseConflict("Evaluation suite revision evidence is no longer available")
    coverage = evaluation_suite_coverage(db, _json_list(revision.cases_snapshot_json))
    if not coverage["gate_ready"]:
        raise EvaluationReleaseConflict(coverage_failure_message(coverage))
    agent = db.scalar(
        select(Agent).where(Agent.id == run.candidate_agent_id).with_for_update()
    )
    version = db.scalar(
        select(AgentPromptVersion)
        .where(AgentPromptVersion.id == run.candidate_version_id)
        .with_for_update()
    )
    if not agent or not version or version.agent_id != agent.id:
        raise EvaluationReleaseConflict("Evaluated Agent version no longer exists")
    if agent.current_version != run.expected_current_version:
        raise EvaluationReleaseConflict(
            "Production Agent version changed after evaluation; run a new baseline and Challenger evaluation"
        )
    if version.status != "DRAFT" or version.version != run.candidate_version:
        raise EvaluationReleaseConflict("Evaluated Agent version is no longer an unpublished draft")
    snapshot = _candidate_snapshot(run)
    if snapshot.get("version") != version.version or any(
        snapshot.get(field) != getattr(version, field) for field in VERSION_FIELDS
    ):
        raise EvaluationReleaseConflict("Evaluated Agent version no longer matches frozen evidence")
    return agent, version


def publish_candidate_release(
    db: Session,
    *,
    run_id: int,
    request_id: str,
    user_id: int,
) -> tuple[AgentEvaluationRelease, bool]:
    request_id = request_id.strip()[:64]
    existing_request = db.scalar(
        select(AgentEvaluationRelease).where(AgentEvaluationRelease.request_id == request_id)
    )
    if existing_request:
        if existing_request.evaluation_run_id != run_id:
            raise EvaluationReleaseConflict("Release request ID is already in use")
        return existing_request, False
    existing_run = db.scalar(
        select(AgentEvaluationRelease).where(
            AgentEvaluationRelease.evaluation_run_id == run_id
        )
    )
    if existing_run:
        raise EvaluationReleaseConflict("Evaluation run has already been published")
    run = db.scalar(
        select(EvaluationRun).where(EvaluationRun.id == run_id).with_for_update()
    )
    if not run:
        raise EvaluationReleaseConflict("Evaluation run not found")
    agent, version = _validate_release_evidence(db, run)
    previous_version = agent.current_version
    activate_version(db, agent, version)
    release = AgentEvaluationRelease(
        request_id=request_id,
        evaluation_run_id=run.id,
        agent_id=agent.id,
        candidate_version_id=version.id,
        candidate_version=version.version,
        previous_version=previous_version,
        expected_current_version=run.expected_current_version,
        status="PUBLISHED",
        published_by_user_id=user_id,
        published_at=datetime.now(timezone.utc),
    )
    db.add(release)
    db.flush()
    return release, True


def rollback_candidate_release(
    db: Session,
    *,
    release_id: int,
    request_id: str,
    user_id: int,
) -> tuple[AgentEvaluationRelease, bool]:
    request_id = request_id.strip()[:64]
    duplicate_request = db.scalar(
        select(AgentEvaluationRelease).where(
            AgentEvaluationRelease.rollback_request_id == request_id
        )
    )
    if duplicate_request:
        if duplicate_request.id != release_id:
            raise EvaluationReleaseConflict("Rollback request ID is already in use")
        return duplicate_request, False
    release = db.scalar(
        select(AgentEvaluationRelease)
        .where(AgentEvaluationRelease.id == release_id)
        .with_for_update()
    )
    if not release:
        raise EvaluationReleaseConflict("Evaluation release not found")
    if release.status != "PUBLISHED":
        raise EvaluationReleaseConflict("Evaluation release has already been rolled back")
    agent = db.scalar(
        select(Agent).where(Agent.id == release.agent_id).with_for_update()
    )
    if not agent:
        raise EvaluationReleaseConflict("Released Agent no longer exists")
    if agent.current_version != release.candidate_version:
        raise EvaluationReleaseConflict(
            "Production Agent version changed after this release; automatic rollback is no longer safe"
        )
    target = db.scalar(
        select(AgentPromptVersion).where(
            AgentPromptVersion.agent_id == agent.id,
            AgentPromptVersion.version == release.previous_version,
        )
    )
    if not target:
        raise EvaluationReleaseConflict("Previous production Agent version no longer exists")
    rollback_version = rollback_to_version(db, agent, target, user_id)
    release.status = "ROLLED_BACK"
    release.rollback_request_id = request_id
    release.rollback_created_version_id = rollback_version.id
    release.rollback_version = rollback_version.version
    release.rolled_back_by_user_id = user_id
    release.rolled_back_at = datetime.now(timezone.utc)
    db.flush()
    return release, True
