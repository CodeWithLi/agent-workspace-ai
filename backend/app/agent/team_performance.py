from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Agent, LLMUsage, WorkflowEvent, WorkflowRun, WorkflowStatus


EvidenceLevel = Literal["INSUFFICIENT", "LOW", "MEDIUM", "HIGH"]
ConfigurationScope = Literal["ALL_HISTORY", "CURRENT_CONFIGURATION"]
CapabilityContextMatch = Literal["ROLE_AGGREGATE", "EXACT", "NONE"]
TERMINAL_WORKFLOW_STATUSES = (
    WorkflowStatus.completed,
    WorkflowStatus.failed,
    WorkflowStatus.cancelled,
    WorkflowStatus.compensation_failed,
)
HISTORY_WORKFLOW_LIMIT = 50
RELIABILITY_PRIOR_MEAN = 0.75
RELIABILITY_PRIOR_STRENGTH = 5
MAX_CAPABILITY_CONTEXTS_PER_ROLE = 10


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
    required_capabilities: list[str] = Field(default_factory=list, max_length=8)
    context_match: CapabilityContextMatch = "ROLE_AGGREGATE"
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

    @field_validator("required_capabilities", mode="before")
    @classmethod
    def normalize_required_capabilities(cls, value: Any) -> Any:
        if isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value):
            return sorted({item.strip() for item in value if item.strip()})
        return value

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
    capability_contexts: list[RolePerformanceEvidence] = Field(default_factory=list)
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
        context_keys = [
            (item.role, tuple(item.required_capabilities))
            for item in self.capability_contexts
        ]
        if len(context_keys) != len(set(context_keys)):
            raise ValueError("team performance capability contexts must be unique")
        contexts_per_role: dict[str, int] = defaultdict(int)
        for item in self.capability_contexts:
            if item.role not in role_names:
                raise ValueError("team performance capability context role must be observed")
            if item.context_match != "EXACT":
                raise ValueError("team performance capability contexts must be exact")
            contexts_per_role[item.role] += 1
            if contexts_per_role[item.role] > MAX_CAPABILITY_CONTEXTS_PER_ROLE:
                raise ValueError("team performance capability contexts exceed the per-role limit")
        return self

    def for_role(self, role: str) -> RolePerformanceEvidence | None:
        return next((item for item in self.roles if item.role == role), None)

    def for_context(
        self,
        role: str,
        required_capabilities: list[str],
    ) -> RolePerformanceEvidence | None:
        signature = tuple(sorted(set(required_capabilities)))
        return next(
            (
                item
                for item in self.capability_contexts
                if item.role == role
                and tuple(item.required_capabilities) == signature
            ),
            None,
        )


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


@dataclass(frozen=True)
class BranchPerformanceSample:
    role: str
    succeeded: bool
    retry_count: int
    revision_count: int
    quality_failure_count: int
    retried: bool
    revised: bool
    quality_failed: bool
    latency_ms: int | None
    cost_micros: int | None
    required_capabilities: tuple[str, ...] | None


def _empty_role_evidence(
    role: str,
    excluded_sample_count: int = 0,
    *,
    required_capabilities: tuple[str, ...] = (),
    context_match: CapabilityContextMatch = "ROLE_AGGREGATE",
) -> RolePerformanceEvidence:
    return RolePerformanceEvidence(
        role=role,
        required_capabilities=list(required_capabilities),
        context_match=context_match,
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


def _build_role_evidence(
    role: str,
    samples: list[BranchPerformanceSample],
    excluded_sample_count: int = 0,
    *,
    required_capabilities: tuple[str, ...] = (),
    context_match: CapabilityContextMatch = "ROLE_AGGREGATE",
) -> RolePerformanceEvidence:
    sample_count = len(samples)
    if not sample_count:
        return _empty_role_evidence(
            role,
            excluded_sample_count,
            required_capabilities=required_capabilities,
            context_match=context_match,
        )
    success_count = sum(sample.succeeded for sample in samples)
    retry_samples = sum(sample.retried for sample in samples)
    revision_samples = sum(sample.revised for sample in samples)
    quality_failure_samples = sum(sample.quality_failed for sample in samples)
    effective_successes = max(
        0.0,
        success_count
        - 0.25 * retry_samples
        - 0.20 * revision_samples
        - 0.50 * quality_failure_samples,
    )
    reliability = (
        effective_successes + RELIABILITY_PRIOR_MEAN * RELIABILITY_PRIOR_STRENGTH
    ) / (sample_count + RELIABILITY_PRIOR_STRENGTH)
    latency_samples = [
        sample.latency_ms for sample in samples if sample.latency_ms is not None
    ]
    cost_samples = [
        sample.cost_micros for sample in samples if sample.cost_micros is not None
    ]
    return RolePerformanceEvidence(
        role=role,
        required_capabilities=list(required_capabilities),
        context_match=context_match,
        sample_count=sample_count,
        excluded_sample_count=excluded_sample_count,
        success_count=success_count,
        failure_count=sample_count - success_count,
        retry_count=sum(sample.retry_count for sample in samples),
        revision_count=sum(sample.revision_count for sample in samples),
        quality_failure_count=sum(sample.quality_failure_count for sample in samples),
        success_rate=round(success_count / sample_count, 4),
        retry_rate=round(retry_samples / sample_count, 4),
        revision_rate=round(revision_samples / sample_count, 4),
        quality_failure_rate=round(quality_failure_samples / sample_count, 4),
        reliability_score=round(reliability, 4),
        median_latency_ms=(round(median(latency_samples)) if latency_samples else None),
        average_cost_micros=(
            round(sum(cost_samples) / len(cost_samples)) if cost_samples else None
        ),
        evidence_level=evidence_level_for_samples(sample_count),
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


def _workflow_state(workflow: WorkflowRun) -> dict[str, Any]:
    try:
        state = json.loads(workflow.state_json or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    return state if isinstance(state, dict) else {}


def _workflow_agent_snapshot(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    snapshot = state.get("agent_snapshot") if isinstance(state, dict) else None
    if not isinstance(snapshot, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for role, config in snapshot.items():
        if isinstance(config, dict):
            normalized[str(role)] = config
    return normalized


def _workflow_capability_contracts(
    state: dict[str, Any],
) -> dict[str, tuple[str, ...]]:
    execution_plan = state.get("execution_plan")
    if not isinstance(execution_plan, dict):
        return {}
    assignments = execution_plan.get("assignments")
    if not isinstance(assignments, list):
        return {}
    contracts: dict[str, tuple[str, ...]] = {}
    for assignment in assignments:
        if not isinstance(assignment, dict):
            continue
        role = assignment.get("role")
        capabilities = assignment.get("required_capabilities")
        if (
            not isinstance(role, str)
            or not isinstance(capabilities, list)
            or not all(isinstance(item, str) for item in capabilities)
        ):
            continue
        contracts[role] = tuple(
            sorted({item.strip() for item in capabilities if item.strip()})
        )
    return contracts


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
    samples_by_role: dict[str, list[BranchPerformanceSample]] = defaultdict(list)
    samples_by_context: dict[
        tuple[str, tuple[str, ...]], list[BranchPerformanceSample]
    ] = defaultdict(list)
    excluded_sample_counts: dict[str, int] = defaultdict(int)
    excluded_context_counts: dict[tuple[str, tuple[str, ...]], int] = defaultdict(int)

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

        state = _workflow_state(workflow)
        historical_snapshot = _workflow_agent_snapshot(state)
        capability_contracts = _workflow_capability_contracts(state)
        agent_roles = {**persisted_agent_roles, **_agent_roles(historical_snapshot)}
        for role, succeeded in final_outcome.items():
            if role not in role_names:
                continue
            required_capabilities = capability_contracts.get(role)
            current_signature = current_signatures.get(role)
            if current_agent_snapshot is not None and (
                current_signature is None
                or _agent_configuration_signature(historical_snapshot.get(role))
                != current_signature
            ):
                excluded_sample_counts[role] += 1
                if required_capabilities is not None:
                    excluded_context_counts[(role, required_capabilities)] += 1
                continue
            role_windows = windows.get(role, [])
            latency_ms = None
            cost_micros = None
            if role_windows:
                latency_ms = round(
                    sum(
                        (ended - started).total_seconds() * 1000
                        for started, ended in role_windows
                    )
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
                    cost_micros = sum(
                        usage.estimated_cost_micros for usage in matching_usage
                    )
            sample = BranchPerformanceSample(
                role=role,
                succeeded=succeeded,
                retry_count=workflow_retry_counts[role],
                revision_count=workflow_revision_counts[role],
                quality_failure_count=workflow_quality_failure_counts[role],
                retried=role in retried_roles,
                revised=role in revised_roles,
                quality_failed=role in quality_failed_roles,
                latency_ms=latency_ms,
                cost_micros=cost_micros,
                required_capabilities=required_capabilities,
            )
            samples_by_role[role].append(sample)
            if required_capabilities is not None:
                samples_by_context[(role, required_capabilities)].append(sample)

    role_evidence = [
        _build_role_evidence(
            role,
            samples_by_role[role],
            excluded_sample_counts[role],
        )
        for role in role_names
    ]
    capability_contexts: list[RolePerformanceEvidence] = []
    context_keys = set(samples_by_context) | set(excluded_context_counts)
    for role in role_names:
        role_contexts = [
            _build_role_evidence(
                role,
                samples_by_context[(role, capabilities)],
                excluded_context_counts[(role, capabilities)],
                required_capabilities=capabilities,
                context_match="EXACT",
            )
            for context_role, capabilities in context_keys
            if context_role == role
        ]
        capability_contexts.extend(
            sorted(
                role_contexts,
                key=lambda item: (-item.sample_count, tuple(item.required_capabilities)),
            )[:MAX_CAPABILITY_CONTEXTS_PER_ROLE]
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
        capability_contexts=capability_contexts,
        configuration_scope=(
            "CURRENT_CONFIGURATION"
            if current_agent_snapshot is not None
            else "ALL_HISTORY"
        ),
    )


def build_plan_performance_evidence(
    structural_score: int,
    assigned_roles: list[str],
    required_capabilities_by_role: dict[str, list[str]],
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
    role_evidence: list[RolePerformanceEvidence] = []
    for role in assigned_roles:
        required_capabilities = tuple(
            sorted(set(required_capabilities_by_role.get(role, [])))
        )
        exact = (
            parsed_profile.for_context(role, list(required_capabilities))
            if parsed_profile
            else None
        )
        if exact:
            role_evidence.append(exact)
            continue
        aggregate = parsed_profile.for_role(role) if parsed_profile else None
        role_evidence.append(
            _empty_role_evidence(
                role,
                aggregate.excluded_sample_count if aggregate else 0,
                required_capabilities=required_capabilities,
                context_match="NONE",
            )
        )
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
