from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from statistics import median
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Agent, LLMUsage, WorkflowEvent, WorkflowRun, WorkflowStatus


EvidenceLevel = Literal["INSUFFICIENT", "LOW", "MEDIUM", "HIGH"]
ConfigurationScope = Literal["ALL_HISTORY", "CURRENT_CONFIGURATION"]
TERMINAL_WORKFLOW_STATUSES = (
    WorkflowStatus.completed,
    WorkflowStatus.failed,
    WorkflowStatus.cancelled,
    WorkflowStatus.compensation_failed,
)
HISTORY_WORKFLOW_LIMIT = 50
RELIABILITY_PRIOR_MEAN = 0.75
RELIABILITY_PRIOR_STRENGTH = 5


def evidence_level_for_samples(sample_count: int) -> EvidenceLevel:
    if sample_count < 3:
        return "INSUFFICIENT"
    if sample_count < 10:
        return "LOW"
    if sample_count < 30:
        return "MEDIUM"
    return "HIGH"


class RolePerformanceEvidence(BaseModel):
    role: str = Field(min_length=2, max_length=50)
    sample_count: int = Field(ge=0)
    excluded_sample_count: int = Field(default=0, ge=0)
    success_count: int = Field(ge=0)
    failure_count: int = Field(ge=0)
    retry_count: int = Field(ge=0)
    revision_count: int = Field(ge=0)
    quality_failure_count: int = Field(default=0, ge=0)
    success_rate: float = Field(ge=0, le=1)
    retry_rate: float = Field(ge=0, le=1)
    revision_rate: float = Field(ge=0, le=1)
    quality_failure_rate: float = Field(default=0, ge=0, le=1)
    reliability_score: float = Field(ge=0, le=1)
    median_latency_ms: int | None = Field(default=None, ge=0)
    average_cost_micros: int | None = Field(default=None, ge=0)
    evidence_level: EvidenceLevel

    @model_validator(mode="after")
    def validate_counts(self) -> "RolePerformanceEvidence":
        if self.success_count + self.failure_count != self.sample_count:
            raise ValueError("role performance outcomes must equal its sample count")
        if self.evidence_level != evidence_level_for_samples(self.sample_count):
            raise ValueError("role performance evidence level must match its sample count")
        return self


class TeamPerformanceProfile(BaseModel):
    project_id: int = Field(ge=1)
    generated_at: datetime
    workflow_count: int = Field(ge=0)
    branch_sample_count: int = Field(ge=0)
    excluded_branch_sample_count: int = Field(default=0, ge=0)
    observed_role_count: int = Field(ge=0)
    sufficient_role_count: int = Field(ge=0)
    roles: list[RolePerformanceEvidence]
    configuration_scope: ConfigurationScope = "ALL_HISTORY"

    @model_validator(mode="after")
    def validate_summary(self) -> "TeamPerformanceProfile":
        role_names = [item.role for item in self.roles]
        if len(role_names) != len(set(role_names)):
            raise ValueError("team performance roles must be unique")
        if self.branch_sample_count != sum(item.sample_count for item in self.roles):
            raise ValueError("team performance branch samples must match role evidence")
        if self.excluded_branch_sample_count != sum(
            item.excluded_sample_count for item in self.roles
        ):
            raise ValueError("team performance excluded samples must match role evidence")
        if self.observed_role_count != sum(item.sample_count > 0 for item in self.roles):
            raise ValueError("team performance observed role count must match role evidence")
        if self.sufficient_role_count != sum(item.sample_count >= 3 for item in self.roles):
            raise ValueError("team performance sufficient role count must match role evidence")
        return self

    def for_role(self, role: str) -> RolePerformanceEvidence | None:
        return next((item for item in self.roles if item.role == role), None)


class ExecutionPlanPerformanceEvidence(BaseModel):
    evidence_level: EvidenceLevel
    configuration_scope: ConfigurationScope = "ALL_HISTORY"
    assigned_role_count: int = Field(ge=1, le=4)
    observed_role_count: int = Field(ge=0, le=4)
    sufficient_role_count: int = Field(ge=0, le=4)
    excluded_sample_count: int = Field(default=0, ge=0)
    reliability_adjustment: int = Field(ge=-5, le=5)
    selection_score: int = Field(ge=0, le=105)
    projected_cost_micros: int | None = Field(default=None, ge=0)
    projected_critical_path_latency_ms: int | None = Field(default=None, ge=0)
    role_evidence: list[RolePerformanceEvidence] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def validate_summary(self) -> "ExecutionPlanPerformanceEvidence":
        if self.assigned_role_count != len(self.role_evidence):
            raise ValueError("plan performance role count must match its evidence")
        if self.observed_role_count != sum(item.sample_count > 0 for item in self.role_evidence):
            raise ValueError("plan performance observed role count must match its evidence")
        if self.sufficient_role_count != sum(item.sample_count >= 3 for item in self.role_evidence):
            raise ValueError("plan performance sufficient role count must match its evidence")
        if self.excluded_sample_count != sum(
            item.excluded_sample_count for item in self.role_evidence
        ):
            raise ValueError("plan performance excluded sample count must match its evidence")
        return self


def _empty_role_evidence(role: str, excluded_sample_count: int = 0) -> RolePerformanceEvidence:
    return RolePerformanceEvidence(
        role=role,
        sample_count=0,
        excluded_sample_count=excluded_sample_count,
        success_count=0,
        failure_count=0,
        retry_count=0,
        revision_count=0,
        success_rate=0,
        retry_rate=0,
        revision_rate=0,
        reliability_score=RELIABILITY_PRIOR_MEAN,
        evidence_level="INSUFFICIENT",
    )


def _payload(event: WorkflowEvent) -> dict[str, Any]:
    try:
        value = json.loads(event.payload_json or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _event_key(payload: dict[str, Any]) -> tuple[Any, ...]:
    return (
        payload.get("role"),
        payload.get("wave", 0),
        payload.get("revision_round", 0),
        payload.get("workflow_attempt", 0),
        payload.get("branch_attempt", 0),
    )


def _agent_roles(snapshot: dict[str, dict[str, Any]]) -> dict[int, str]:
    roles: dict[int, str] = {}
    for role, config in snapshot.items():
        agent_id = config.get("agent_id")
        if isinstance(agent_id, int):
            roles[agent_id] = role
    return roles


def _workflow_agent_snapshot(workflow: WorkflowRun) -> dict[str, dict[str, Any]]:
    try:
        state = json.loads(workflow.state_json or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    snapshot = state.get("agent_snapshot") if isinstance(state, dict) else None
    if not isinstance(snapshot, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for role, config in snapshot.items():
        if isinstance(config, dict):
            normalized[str(role)] = config
    return normalized


def _agent_configuration_signature(config: Any) -> tuple[Any, ...] | None:
    if not isinstance(config, dict):
        return None
    agent_id = config.get("agent_id")
    prompt_version = config.get("prompt_version")
    model = config.get("model")
    system_prompt = config.get("system_prompt")
    enabled_tools = config.get("enabled_tools")
    knowledge_access = config.get("knowledge_access")
    memory_enable = config.get("memory_enable")
    concurrency_limit = config.get("concurrency_limit")
    if (
        not isinstance(agent_id, int)
        or not isinstance(prompt_version, int)
        or not isinstance(model, str)
        or not isinstance(system_prompt, str)
        or not isinstance(enabled_tools, list)
        or not all(isinstance(tool, str) for tool in enabled_tools)
        or not isinstance(knowledge_access, bool)
        or not isinstance(memory_enable, bool)
        or not isinstance(concurrency_limit, int)
    ):
        return None
    return (
        agent_id,
        prompt_version,
        model,
        hashlib.sha256(system_prompt.encode("utf-8")).hexdigest(),
        tuple(sorted(enabled_tools)),
        knowledge_access,
        memory_enable,
        concurrency_limit,
    )


def build_team_performance_profile(
    db: Session,
    project_id: int,
    roles: list[str],
    *,
    current_agent_snapshot: dict[str, dict[str, Any]] | None = None,
    now: datetime | None = None,
    workflow_limit: int = HISTORY_WORKFLOW_LIMIT,
) -> TeamPerformanceProfile:
    role_names = sorted(set(roles))
    current_signatures = (
        {
            role: _agent_configuration_signature(current_agent_snapshot.get(role))
            for role in role_names
        }
        if current_agent_snapshot is not None
        else {}
    )
    workflows = list(
        db.scalars(
            select(WorkflowRun)
            .where(
                WorkflowRun.project_id == project_id,
                WorkflowRun.status.in_(TERMINAL_WORKFLOW_STATUSES),
            )
            .order_by(
                func.coalesce(
                    WorkflowRun.finished_at,
                    WorkflowRun.updated_at,
                    WorkflowRun.created_at,
                ).desc(),
                WorkflowRun.id.desc(),
            )
            .limit(workflow_limit)
        )
    )
    workflow_ids = [workflow.id for workflow in workflows]
    events = (
        list(
            db.scalars(
                select(WorkflowEvent)
                .where(
                    WorkflowEvent.workflow_id.in_(workflow_ids),
                    WorkflowEvent.event_type.in_(
                        (
                            "BRANCH_STARTED",
                            "BRANCH_COMPLETED",
                            "BRANCH_FAILED",
                            "BRANCH_RETRY_SCHEDULED",
                            "REVISION_REQUESTED",
                            "QUALITY_GATE_FAILED",
                        )
                    ),
                )
                .order_by(WorkflowEvent.workflow_id, WorkflowEvent.id)
            )
        )
        if workflow_ids
        else []
    )
    usages = (
        list(
            db.scalars(
                select(LLMUsage)
                .where(LLMUsage.workflow_id.in_(workflow_ids))
                .order_by(LLMUsage.workflow_id, LLMUsage.id)
            )
        )
        if workflow_ids
        else []
    )
    events_by_workflow: dict[int, list[WorkflowEvent]] = defaultdict(list)
    usages_by_workflow: dict[int, list[LLMUsage]] = defaultdict(list)
    for event in events:
        events_by_workflow[event.workflow_id].append(event)
    for usage in usages:
        if usage.workflow_id is not None:
            usages_by_workflow[usage.workflow_id].append(usage)

    agent_ids = {usage.agent_id for usage in usages if usage.agent_id is not None}
    persisted_agent_roles = {
        agent.id: agent.role.value
        for agent in db.scalars(select(Agent).where(Agent.id.in_(agent_ids)))
    } if agent_ids else {}
    outcomes: dict[str, list[bool]] = defaultdict(list)
    retry_counts: dict[str, int] = defaultdict(int)
    revision_counts: dict[str, int] = defaultdict(int)
    quality_failure_counts: dict[str, int] = defaultdict(int)
    retry_samples: dict[str, int] = defaultdict(int)
    revision_samples: dict[str, int] = defaultdict(int)
    quality_failure_samples: dict[str, int] = defaultdict(int)
    excluded_sample_counts: dict[str, int] = defaultdict(int)
    latency_samples: dict[str, list[int]] = defaultdict(list)
    cost_samples: dict[str, list[int]] = defaultdict(list)

    for workflow in workflows:
        starts: dict[tuple[Any, ...], list[datetime]] = defaultdict(list)
        windows: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
        final_outcome: dict[str, bool] = {}
        retried_roles: set[str] = set()
        revised_roles: set[str] = set()
        quality_failed_roles: set[str] = set()
        workflow_retry_counts: dict[str, int] = defaultdict(int)
        workflow_revision_counts: dict[str, int] = defaultdict(int)
        workflow_quality_failure_counts: dict[str, int] = defaultdict(int)
        for event in events_by_workflow[workflow.id]:
            payload = _payload(event)
            if event.event_type in {"REVISION_REQUESTED", "QUALITY_GATE_FAILED"}:
                revisions = payload.get("revision_roles")
                if isinstance(revisions, list):
                    for role in revisions:
                        if isinstance(role, str):
                            if event.event_type == "REVISION_REQUESTED":
                                workflow_revision_counts[role] += 1
                                revised_roles.add(role)
                            else:
                                workflow_quality_failure_counts[role] += 1
                                quality_failed_roles.add(role)
                continue
            role = payload.get("role")
            if not isinstance(role, str):
                continue
            key = _event_key(payload)
            timestamp = _utc(event.created_at)
            if event.event_type == "BRANCH_STARTED":
                starts[key].append(timestamp)
            elif event.event_type in {"BRANCH_COMPLETED", "BRANCH_FAILED"}:
                if starts[key]:
                    started_at = starts[key].pop()
                    if timestamp >= started_at:
                        windows[role].append((started_at, timestamp))
                final_outcome[role] = event.event_type == "BRANCH_COMPLETED"
            elif event.event_type == "BRANCH_RETRY_SCHEDULED":
                workflow_retry_counts[role] += 1
                retried_roles.add(role)

        historical_snapshot = _workflow_agent_snapshot(workflow)
        agent_roles = {**persisted_agent_roles, **_agent_roles(historical_snapshot)}
        for role, succeeded in final_outcome.items():
            if role not in role_names:
                continue
            current_signature = current_signatures.get(role)
            if current_agent_snapshot is not None and (
                current_signature is None
                or _agent_configuration_signature(historical_snapshot.get(role))
                != current_signature
            ):
                excluded_sample_counts[role] += 1
                continue
            outcomes[role].append(succeeded)
            retry_counts[role] += workflow_retry_counts[role]
            revision_counts[role] += workflow_revision_counts[role]
            quality_failure_counts[role] += workflow_quality_failure_counts[role]
            retry_samples[role] += role in retried_roles
            revision_samples[role] += role in revised_roles
            quality_failure_samples[role] += role in quality_failed_roles
            role_windows = windows.get(role, [])
            if role_windows:
                latency_samples[role].append(
                    round(sum((ended - started).total_seconds() * 1000 for started, ended in role_windows))
                )
                matching_usage = [
                    usage
                    for usage in usages_by_workflow[workflow.id]
                    if usage.agent_id is not None
                    and agent_roles.get(usage.agent_id) == role
                    and any(
                        started <= _utc(usage.created_at) <= ended
                        for started, ended in role_windows
                    )
                ]
                if matching_usage:
                    cost_samples[role].append(
                        sum(usage.estimated_cost_micros for usage in matching_usage)
                    )

    role_evidence: list[RolePerformanceEvidence] = []
    for role in role_names:
        role_outcomes = outcomes[role]
        sample_count = len(role_outcomes)
        if not sample_count:
            role_evidence.append(_empty_role_evidence(role, excluded_sample_counts[role]))
            continue
        success_count = sum(role_outcomes)
        failure_count = sample_count - success_count
        effective_successes = max(
            0.0,
            success_count
            - 0.25 * retry_samples[role]
            - 0.20 * revision_samples[role]
            - 0.50 * quality_failure_samples[role],
        )
        reliability = (
            effective_successes + RELIABILITY_PRIOR_MEAN * RELIABILITY_PRIOR_STRENGTH
        ) / (sample_count + RELIABILITY_PRIOR_STRENGTH)
        role_evidence.append(
            RolePerformanceEvidence(
                role=role,
                sample_count=sample_count,
                excluded_sample_count=excluded_sample_counts[role],
                success_count=success_count,
                failure_count=failure_count,
                retry_count=retry_counts[role],
                revision_count=revision_counts[role],
                quality_failure_count=quality_failure_counts[role],
                success_rate=round(success_count / sample_count, 4),
                retry_rate=round(retry_samples[role] / sample_count, 4),
                revision_rate=round(revision_samples[role] / sample_count, 4),
                quality_failure_rate=round(
                    quality_failure_samples[role] / sample_count,
                    4,
                ),
                reliability_score=round(reliability, 4),
                median_latency_ms=(
                    round(median(latency_samples[role])) if latency_samples[role] else None
                ),
                average_cost_micros=(
                    round(sum(cost_samples[role]) / len(cost_samples[role]))
                    if cost_samples[role]
                    else None
                ),
                evidence_level=evidence_level_for_samples(sample_count),
            )
        )

    return TeamPerformanceProfile(
        project_id=project_id,
        generated_at=now or datetime.now(timezone.utc),
        workflow_count=len(workflows),
        branch_sample_count=sum(item.sample_count for item in role_evidence),
        excluded_branch_sample_count=sum(
            item.excluded_sample_count for item in role_evidence
        ),
        observed_role_count=sum(item.sample_count > 0 for item in role_evidence),
        sufficient_role_count=sum(item.sample_count >= 3 for item in role_evidence),
        roles=role_evidence,
        configuration_scope=(
            "CURRENT_CONFIGURATION"
            if current_agent_snapshot is not None
            else "ALL_HISTORY"
        ),
    )


def build_plan_performance_evidence(
    structural_score: int,
    assigned_roles: list[str],
    execution_waves: list[list[str]],
    profile: TeamPerformanceProfile | dict[str, Any] | None,
) -> ExecutionPlanPerformanceEvidence:
    parsed_profile = (
        profile
        if isinstance(profile, TeamPerformanceProfile)
        else TeamPerformanceProfile.model_validate(profile)
        if profile
        else None
    )
    role_evidence = [
        parsed_profile.for_role(role) or _empty_role_evidence(role)
        if parsed_profile
        else _empty_role_evidence(role)
        for role in assigned_roles
    ]
    sufficient = [item for item in role_evidence if item.sample_count >= 3]
    adjustment = 0
    if sufficient:
        adjustment = round(
            sum((item.reliability_score - RELIABILITY_PRIOR_MEAN) * 20 for item in sufficient)
            / len(sufficient)
        )
        adjustment = max(-5, min(5, adjustment))
    level_order = {"INSUFFICIENT": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}
    evidence_level = min(role_evidence, key=lambda item: level_order[item.evidence_level]).evidence_level
    role_map = {item.role: item for item in role_evidence}
    complete_cost = all(item.average_cost_micros is not None for item in role_evidence)
    complete_latency = all(item.median_latency_ms is not None for item in role_evidence)
    projected_latency = None
    if complete_latency:
        projected_latency = sum(
            max(role_map[role].median_latency_ms or 0 for role in wave)
            for wave in execution_waves
        )
    return ExecutionPlanPerformanceEvidence(
        evidence_level=evidence_level,
        configuration_scope=(
            parsed_profile.configuration_scope
            if parsed_profile
            else "ALL_HISTORY"
        ),
        assigned_role_count=len(role_evidence),
        observed_role_count=sum(item.sample_count > 0 for item in role_evidence),
        sufficient_role_count=len(sufficient),
        excluded_sample_count=sum(
            item.excluded_sample_count for item in role_evidence
        ),
        reliability_adjustment=adjustment,
        selection_score=max(0, min(105, structural_score + adjustment)),
        projected_cost_micros=(
            sum(item.average_cost_micros or 0 for item in role_evidence)
            if complete_cost
            else None
        ),
        projected_critical_path_latency_ms=projected_latency,
        role_evidence=role_evidence,
    )
