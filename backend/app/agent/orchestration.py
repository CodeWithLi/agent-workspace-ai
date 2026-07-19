import hashlib
import json
import re
from statistics import median
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from app.agent.team_performance import (
    ExecutionPlanPerformanceEvidence,
    TeamPerformanceProfile,
    build_plan_performance_evidence,
)


SpecialistRole = Literal[
    "test_engineer",
    "operations_analyst",
    "knowledge_admin",
    "notification_secretary",
]
ALLOWED_SPECIALIST_ROLES: tuple[SpecialistRole, ...] = (
    "test_engineer",
    "operations_analyst",
    "knowledge_admin",
    "notification_secretary",
)
SpecialistCapability = Literal[
    "quality_assurance",
    "acceptance_evidence",
    "boundary_analysis",
    "test_case_generation",
    "operational_readiness",
    "risk_analysis",
    "observability",
    "release_recovery",
    "project_analytics",
    "delivery_reporting",
    "knowledge_governance",
    "source_traceability",
    "knowledge_retrieval",
    "notification_design",
    "delivery_reliability",
    "audience_governance",
    "notification_delivery",
    "project_context",
]
SPECIALIST_CAPABILITY_LABELS: dict[SpecialistCapability, str] = {
    "quality_assurance": "质量保障",
    "acceptance_evidence": "验收证据",
    "boundary_analysis": "边界分析",
    "test_case_generation": "测试用例生成",
    "operational_readiness": "运营就绪",
    "risk_analysis": "风险分析",
    "observability": "可观测性",
    "release_recovery": "发布与恢复",
    "project_analytics": "项目分析",
    "delivery_reporting": "交付报告",
    "knowledge_governance": "知识治理",
    "source_traceability": "来源追溯",
    "knowledge_retrieval": "知识检索",
    "notification_design": "通知设计",
    "delivery_reliability": "触达可靠性",
    "audience_governance": "受众治理",
    "notification_delivery": "通知投递",
    "project_context": "项目上下文",
}
_SPECIALIST_ROLE_NAMES: dict[SpecialistRole, str] = {
    "test_engineer": "AI测试工程师",
    "operations_analyst": "AI运营分析师",
    "knowledge_admin": "AI知识库管理员",
    "notification_secretary": "AI通知秘书",
}
_SPECIALIST_ROLE_CORE_CAPABILITIES: dict[SpecialistRole, tuple[SpecialistCapability, ...]] = {
    "test_engineer": ("quality_assurance", "acceptance_evidence", "boundary_analysis"),
    "operations_analyst": (
        "operational_readiness",
        "risk_analysis",
        "observability",
        "release_recovery",
    ),
    "knowledge_admin": ("knowledge_governance", "source_traceability"),
    "notification_secretary": (
        "notification_design",
        "delivery_reliability",
        "audience_governance",
    ),
}
_SPECIALIST_ROLE_BASELINE_CAPABILITIES: dict[SpecialistRole, tuple[SpecialistCapability, ...]] = {
    role: capabilities[:2]
    for role, capabilities in _SPECIALIST_ROLE_CORE_CAPABILITIES.items()
}
_SPECIALIST_ROLE_TOOL_CAPABILITIES: dict[
    SpecialistRole, dict[str, tuple[SpecialistCapability, ...]]
] = {
    "test_engineer": {
        "context_search": ("project_context",),
        "testcase_create": ("test_case_generation",),
    },
    "operations_analyst": {
        "context_search": ("project_context",),
        "analytics_report": ("project_analytics",),
        "report_generate": ("delivery_reporting",),
    },
    "knowledge_admin": {
        "context_search": ("project_context",),
        "knowledge_search": ("knowledge_retrieval",),
    },
    "notification_secretary": {
        "context_search": ("project_context",),
        "notification_create": ("notification_delivery",),
    },
}
_SPECIALIST_ROLE_DEFAULT_TOOLS: dict[SpecialistRole, tuple[str, ...]] = {
    role: tuple(tool_capabilities)
    for role, tool_capabilities in _SPECIALIST_ROLE_TOOL_CAPABILITIES.items()
}
ReviewerPanelRole = Literal["test_engineer", "operations_analyst", "architect"]


class ReviewerPanelQuorumError(ValueError):
    def __init__(self, valid_count: int, quorum: int, panel_count: int) -> None:
        self.valid_count = valid_count
        self.quorum = quorum
        self.panel_count = panel_count
        super().__init__(
            f"reviewer panel quorum unavailable: {valid_count}/{quorum} structured outputs"
        )


class SpecialistTeamUnavailableError(ValueError):
    pass


class SpecialistCapabilityProfile(BaseModel):
    role: SpecialistRole
    name: str = Field(min_length=1, max_length=100)
    capabilities: list[SpecialistCapability] = Field(default_factory=list, max_length=18)
    enabled_tools: list[str] = Field(default_factory=list, max_length=10)
    knowledge_access: bool = False
    concurrency_limit: int = Field(default=0, ge=0, le=100)
    eligible: bool = False
    unavailable_reasons: list[str] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def validate_unique_values(self) -> "SpecialistCapabilityProfile":
        if len(self.capabilities) != len(set(self.capabilities)):
            raise ValueError(f"capabilities for {self.role} must be unique")
        if len(self.enabled_tools) != len(set(self.enabled_tools)):
            raise ValueError(f"enabled tools for {self.role} must be unique")
        if self.eligible and self.unavailable_reasons:
            raise ValueError(f"eligible specialist {self.role} cannot have unavailable reasons")
        return self


def build_specialist_capability_catalog(
    agent_snapshot: dict[str, dict[str, Any]],
) -> list[SpecialistCapabilityProfile]:
    catalog: list[SpecialistCapabilityProfile] = []
    for role in ALLOWED_SPECIALIST_ROLES:
        frozen = agent_snapshot.get(role)
        reasons: list[str] = []
        if not isinstance(frozen, dict) or not frozen:
            frozen = {}
            reasons.append("Agent 配置缺失")

        if "enabled_tools" in frozen:
            raw_tools = frozen.get("enabled_tools")
            enabled_tools = (
                sorted(
                    {tool for tool in raw_tools if isinstance(tool, str) and tool}
                    & set(_SPECIALIST_ROLE_TOOL_CAPABILITIES[role])
                )
                if isinstance(raw_tools, list)
                else []
            )
        elif frozen:
            # Older workflow snapshots predate tool freezing; use role defaults when resuming them.
            enabled_tools = list(_SPECIALIST_ROLE_DEFAULT_TOOLS[role])
        else:
            enabled_tools = []

        concurrency_limit = int(frozen.get("concurrency_limit") or 0)
        if frozen and concurrency_limit < 1:
            reasons.append("并发额度不可用")
        if frozen and not enabled_tools:
            reasons.append("没有启用的专业工具")

        knowledge_access = bool(frozen.get("knowledge_access", True)) if frozen else False
        capabilities: list[SpecialistCapability] = []
        if frozen:
            capabilities.extend(_SPECIALIST_ROLE_CORE_CAPABILITIES[role])
            for tool in enabled_tools:
                if tool == "knowledge_search" and not knowledge_access:
                    continue
                capabilities.extend(_SPECIALIST_ROLE_TOOL_CAPABILITIES[role].get(tool, ()))

        catalog.append(
            SpecialistCapabilityProfile(
                role=role,
                name=str(frozen.get("name") or _SPECIALIST_ROLE_NAMES[role]),
                capabilities=list(dict.fromkeys(capabilities)),
                enabled_tools=enabled_tools,
                knowledge_access=knowledge_access,
                concurrency_limit=concurrency_limit,
                eligible=not reasons,
                unavailable_reasons=reasons,
            )
        )
    return catalog


def default_specialist_capability_catalog() -> list[SpecialistCapabilityProfile]:
    return build_specialist_capability_catalog(
        {
            role: {
                "name": _SPECIALIST_ROLE_NAMES[role],
                "enabled_tools": list(_SPECIALIST_ROLE_DEFAULT_TOOLS[role]),
                "knowledge_access": True,
                "concurrency_limit": 1,
            }
            for role in ALLOWED_SPECIALIST_ROLES
        }
    )


def ensure_specialist_team_ready(
    catalog: list[SpecialistCapabilityProfile],
    minimum: int = 2,
) -> list[SpecialistCapabilityProfile]:
    eligible = [profile for profile in catalog if profile.eligible]
    if len(eligible) >= minimum:
        return eligible
    unavailable = "; ".join(
        f"{profile.role}: {', '.join(profile.unavailable_reasons) or '不可用'}"
        for profile in catalog
        if not profile.eligible
    )
    raise SpecialistTeamUnavailableError(
        f"specialist team requires at least {minimum} eligible roles; "
        f"found {len(eligible)} ({unavailable or 'no specialist profiles'})"
    )


def infer_required_specialist_capabilities(user_input: str) -> set[SpecialistCapability]:
    normalized = user_input.lower()
    required: set[SpecialistCapability] = set()
    if any(
        keyword in normalized
        for keyword in (
            "rag",
            "知识库",
            "知识检索",
            "知识搜索",
            "文档检索",
            "文档搜索",
            "向量检索",
            "数据治理",
            "embedding",
            "knowledge base",
            "knowledge retrieval",
            "document search",
            "document retrieval",
        )
    ):
        required.add("knowledge_retrieval")
    if any(
        keyword in normalized
        for keyword in ("通知", "邮件", "短信", "提醒", "notification", "email")
    ):
        required.add("notification_delivery")
    return required


def ensure_specialist_capabilities_available(
    catalog: list[SpecialistCapabilityProfile],
    required: set[SpecialistCapability],
) -> None:
    available = {
        capability
        for profile in ensure_specialist_team_ready(catalog)
        for capability in profile.capabilities
    }
    missing = required - available
    if missing:
        raise SpecialistTeamUnavailableError(
            "specialist team cannot satisfy required capabilities: "
            f"{', '.join(sorted(missing))}"
        )


class SpecialistAssignment(BaseModel):
    role: SpecialistRole
    objective: str = Field(min_length=4, max_length=500)
    deliverable: str = Field(min_length=2, max_length=200)
    depends_on: list[SpecialistRole] = Field(default_factory=list, max_length=3)
    required_capabilities: list[SpecialistCapability] = Field(default_factory=list, max_length=8)
    selection_reason: str = Field(default="", max_length=500)


class MultiAgentExecutionPlan(BaseModel):
    objective: str = Field(min_length=4, max_length=1000)
    rationale: str = Field(min_length=4, max_length=1000)
    assignments: list[SpecialistAssignment] = Field(min_length=2, max_length=4)
    success_criteria: list[str] = Field(min_length=2, max_length=10)
    team_capabilities: list[SpecialistCapabilityProfile] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def validate_assignment_graph(self) -> "MultiAgentExecutionPlan":
        roles = [assignment.role for assignment in self.assignments]
        if len(roles) != len(set(roles)):
            raise ValueError("specialist assignment roles must be unique")
        role_set = set(roles)
        dependencies: dict[SpecialistRole, set[SpecialistRole]] = {}
        for assignment in self.assignments:
            if len(assignment.depends_on) != len(set(assignment.depends_on)):
                raise ValueError(f"dependencies for {assignment.role} must be unique")
            if assignment.role in assignment.depends_on:
                raise ValueError(f"specialist assignment {assignment.role} cannot depend on itself")
            unknown = set(assignment.depends_on) - role_set
            if unknown:
                raise ValueError(
                    f"dependencies for {assignment.role} are not assigned: {', '.join(sorted(unknown))}"
                )
            dependencies[assignment.role] = set(assignment.depends_on)

        resolved: set[SpecialistRole] = set()
        remaining = set(roles)
        while remaining:
            ready = {role for role in remaining if dependencies[role] <= resolved}
            if not ready:
                raise ValueError("specialist assignment dependencies must form an acyclic graph")
            resolved.update(ready)
            remaining.difference_update(ready)
        if self.team_capabilities:
            profile_roles = [profile.role for profile in self.team_capabilities]
            if len(profile_roles) != len(set(profile_roles)):
                raise ValueError("specialist capability profile roles must be unique")
            if set(profile_roles) != role_set:
                raise ValueError("specialist capability profiles must match assigned roles")
            profiles = {profile.role: profile for profile in self.team_capabilities}
            for assignment in self.assignments:
                profile = profiles[assignment.role]
                if not profile.eligible:
                    raise ValueError(f"specialist assignment {assignment.role} is unavailable")
                unsupported = set(assignment.required_capabilities) - set(profile.capabilities)
                if unsupported:
                    raise ValueError(
                        f"specialist assignment {assignment.role} lacks capabilities: "
                        f"{', '.join(sorted(unsupported))}"
                    )
        return self


class ExecutionPlanCandidateCheck(BaseModel):
    name: Literal[
        "capability_coverage",
        "specialist_fit",
        "success_contract",
        "parallel_efficiency",
        "delivery_balance",
    ]
    label: str = Field(min_length=2, max_length=100)
    score: int = Field(ge=0, le=100)
    max_score: int = Field(ge=1, le=100)
    detail: str = Field(min_length=2, max_length=500)

    @model_validator(mode="after")
    def validate_score_bound(self) -> "ExecutionPlanCandidateCheck":
        if self.score > self.max_score:
            raise ValueError("candidate check score cannot exceed its maximum")
        return self


CommitmentDetail = Annotated[str, Field(min_length=2, max_length=500)]


class SpecialistPlanCommitment(BaseModel):
    role: SpecialistRole
    decision: Literal["ACCEPT", "CHALLENGE", "ABSTAIN"]
    structured: bool
    confidence: float | None = Field(default=None, ge=0, le=1)
    summary: str = Field(min_length=2, max_length=1000)
    missing_inputs: list[CommitmentDetail] = Field(default_factory=list, max_length=5)
    dependency_concerns: list[CommitmentDetail] = Field(default_factory=list, max_length=5)
    proposed_changes: list[CommitmentDetail] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def validate_commitment_contract(self) -> "SpecialistPlanCommitment":
        detail_groups = (
            self.missing_inputs,
            self.dependency_concerns,
            self.proposed_changes,
        )
        if any(len(items) != len(set(items)) for items in detail_groups):
            raise ValueError("specialist commitment details must be unique")
        if self.structured:
            if self.decision == "ABSTAIN" or self.confidence is None:
                raise ValueError("structured commitments require a decision and confidence")
        elif self.decision != "ABSTAIN" or self.confidence is not None:
            raise ValueError("unstructured commitments must abstain without confidence")
        if self.decision == "ACCEPT" and any(detail_groups):
            raise ValueError("accepted commitments cannot contain blockers or proposed changes")
        if self.decision == "CHALLENGE" and not any(detail_groups):
            raise ValueError("challenged commitments require a concrete concern or proposed change")
        return self


class ExecutionPlanCandidate(BaseModel):
    candidate_id: str = Field(pattern=r"^[a-z0-9_]{2,40}$")
    perspective: str = Field(min_length=2, max_length=100)
    origin: Literal[
        "independent",
        "negotiated_repair",
        "deterministic_fallback",
    ] = "independent"
    source_candidate_id: str | None = Field(default=None, pattern=r"^[a-z0-9_]{2,40}$")
    plan: MultiAgentExecutionPlan
    score: int = Field(ge=0, le=100)
    checks: list[ExecutionPlanCandidateCheck] = Field(min_length=5, max_length=5)
    performance_evidence: ExecutionPlanPerformanceEvidence | None = None
    plan_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    duplicate_of: str | None = Field(default=None, pattern=r"^[a-z0-9_]{2,40}$")
    commitments: list[SpecialistPlanCommitment] = Field(default_factory=list, max_length=4)
    commitment_status: Literal[
        "NOT_REVIEWED",
        "READY",
        "CHALLENGED",
        "INCOMPLETE",
    ] = "NOT_REVIEWED"
    commitment_valid_count: int = Field(default=0, ge=0, le=4)
    commitment_accept_count: int = Field(default=0, ge=0, le=4)
    commitment_challenge_count: int = Field(default=0, ge=0, le=4)

    @model_validator(mode="after")
    def validate_score_contract(self) -> "ExecutionPlanCandidate":
        names = [check.name for check in self.checks]
        if len(names) != len(set(names)):
            raise ValueError("candidate check names must be unique")
        if sum(check.max_score for check in self.checks) != 100:
            raise ValueError("candidate check maximum scores must total 100")
        if self.score != sum(check.score for check in self.checks):
            raise ValueError("candidate score must equal the sum of its checks")
        if self.performance_evidence is not None:
            assigned_roles = [assignment.role for assignment in self.plan.assignments]
            evidence_roles = [item.role for item in self.performance_evidence.role_evidence]
            if evidence_roles != assigned_roles:
                raise ValueError("candidate performance evidence must follow assigned roles")
            expected_selection_score = max(
                0,
                min(105, self.score + self.performance_evidence.reliability_adjustment),
            )
            if self.performance_evidence.selection_score != expected_selection_score:
                raise ValueError("candidate selection score must include reliability adjustment")
        if self.duplicate_of == self.candidate_id:
            raise ValueError("candidate cannot duplicate itself")
        if self.source_candidate_id == self.candidate_id:
            raise ValueError("candidate cannot be repaired from itself")
        if self.origin == "negotiated_repair" and self.source_candidate_id is None:
            raise ValueError("negotiated repair candidates require a source candidate")
        if self.origin != "negotiated_repair" and self.source_candidate_id is not None:
            raise ValueError("only negotiated repair candidates may reference a source candidate")
        if not self.commitments:
            if (
                self.commitment_status != "NOT_REVIEWED"
                or self.commitment_valid_count
                or self.commitment_accept_count
                or self.commitment_challenge_count
            ):
                raise ValueError("unreviewed candidates cannot contain commitment counts")
            return self
        assigned_roles = {assignment.role for assignment in self.plan.assignments}
        commitment_roles = [commitment.role for commitment in self.commitments]
        if len(commitment_roles) != len(set(commitment_roles)):
            raise ValueError("specialist commitment roles must be unique")
        if set(commitment_roles) != assigned_roles:
            raise ValueError("specialist commitments must cover every assigned role")
        valid_count = sum(commitment.structured for commitment in self.commitments)
        accept_count = sum(
            commitment.decision == "ACCEPT" for commitment in self.commitments
        )
        challenge_count = sum(
            commitment.decision == "CHALLENGE" for commitment in self.commitments
        )
        expected_status = (
            "READY"
            if accept_count == len(self.commitments)
            else "CHALLENGED"
            if challenge_count
            else "INCOMPLETE"
        )
        if (
            self.commitment_valid_count != valid_count
            or self.commitment_accept_count != accept_count
            or self.commitment_challenge_count != challenge_count
            or self.commitment_status != expected_status
        ):
            raise ValueError("specialist commitment summary does not match its evidence")
        return self


class ExecutionPlanDeliberation(BaseModel):
    selected_candidate_id: str = Field(pattern=r"^[a-z0-9_]{2,40}$")
    selection_reason: str = Field(min_length=4, max_length=2000)
    arbitration_mode: Literal["independent_arbiter", "deterministic_fallback"]
    arbiter_role: Literal["architect"] = "architect"
    candidates: list[ExecutionPlanCandidate] = Field(min_length=1, max_length=4)
    dissenting_candidate_ids: list[str] = Field(default_factory=list, max_length=3)
    dissent_summary: str = Field(default="", max_length=2000)
    invalid_candidate_count: int = Field(default=0, ge=0, le=3)
    distinct_candidate_count: int = Field(ge=1, le=4)

    @model_validator(mode="after")
    def validate_candidate_references(self) -> "ExecutionPlanDeliberation":
        candidate_ids = [candidate.candidate_id for candidate in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("execution plan candidate ids must be unique")
        if self.selected_candidate_id not in candidate_ids:
            raise ValueError("selected execution plan candidate was not assessed")
        if len(self.dissenting_candidate_ids) != len(set(self.dissenting_candidate_ids)):
            raise ValueError("dissenting execution plan candidate ids must be unique")
        invalid_dissent = set(self.dissenting_candidate_ids) - set(candidate_ids)
        if invalid_dissent or self.selected_candidate_id in self.dissenting_candidate_ids:
            raise ValueError("dissenting candidates must be assessed and unselected")
        invalid_sources = {
            candidate.source_candidate_id
            for candidate in self.candidates
            if candidate.source_candidate_id is not None
        } - set(candidate_ids)
        if invalid_sources:
            raise ValueError("negotiated repair sources must reference assessed candidates")
        distinct_count = len({candidate.plan_fingerprint for candidate in self.candidates})
        if self.distinct_candidate_count != distinct_count:
            raise ValueError("distinct candidate count must match plan fingerprints")
        return self

    @property
    def selected_plan(self) -> MultiAgentExecutionPlan:
        return next(
            candidate.plan
            for candidate in self.candidates
            if candidate.candidate_id == self.selected_candidate_id
        )

    @property
    def selected_candidate(self) -> ExecutionPlanCandidate:
        return next(
            candidate
            for candidate in self.candidates
            if candidate.candidate_id == self.selected_candidate_id
        )


def bind_execution_plan_capabilities(
    plan: MultiAgentExecutionPlan,
    catalog: list[SpecialistCapabilityProfile],
) -> MultiAgentExecutionPlan:
    ensure_specialist_team_ready(catalog)
    profiles = {profile.role: profile for profile in catalog}
    assignments: list[dict[str, Any]] = []
    selected_profiles: list[SpecialistCapabilityProfile] = []
    for assignment in plan.assignments:
        profile = profiles.get(assignment.role)
        if not profile or not profile.eligible:
            reasons = ", ".join(profile.unavailable_reasons) if profile else "配置缺失"
            raise ValueError(f"specialist assignment {assignment.role} is unavailable: {reasons}")
        required = list(
            dict.fromkeys(
                assignment.required_capabilities
                or _SPECIALIST_ROLE_BASELINE_CAPABILITIES[assignment.role]
            )
        )
        unsupported = set(required) - set(profile.capabilities)
        if unsupported:
            raise ValueError(
                f"specialist assignment {assignment.role} lacks capabilities: "
                f"{', '.join(sorted(unsupported))}"
            )
        reason = assignment.selection_reason.strip() or (
            f"该分支需要{'、'.join(SPECIALIST_CAPABILITY_LABELS[item] for item in required)}，"
            f"{profile.name}的冻结能力与当前工具权限匹配。"
        )
        assignments.append(
            {
                **assignment.model_dump(mode="json"),
                "required_capabilities": required,
                "selection_reason": reason,
            }
        )
        selected_profiles.append(profile)
    return MultiAgentExecutionPlan.model_validate(
        {
            **plan.model_dump(mode="json", exclude={"assignments", "team_capabilities"}),
            "assignments": assignments,
            "team_capabilities": [profile.model_dump(mode="json") for profile in selected_profiles],
        }
    )


def validate_execution_plan_capabilities(
    plan: MultiAgentExecutionPlan,
    catalog: list[SpecialistCapabilityProfile],
    required_capabilities: set[SpecialistCapability] | None = None,
) -> MultiAgentExecutionPlan:
    bound = bind_execution_plan_capabilities(plan, catalog)
    required = required_capabilities or set()
    covered = {
        capability
        for assignment in bound.assignments
        for capability in assignment.required_capabilities
    }
    missing = required - covered
    if missing:
        raise ValueError(
            "execution plan does not cover required capabilities: "
            f"{', '.join(sorted(missing))}"
        )
    return bound


def build_execution_waves(plan: MultiAgentExecutionPlan) -> list[list[SpecialistAssignment]]:
    remaining = list(plan.assignments)
    resolved: set[SpecialistRole] = set()
    waves: list[list[SpecialistAssignment]] = []
    while remaining:
        wave = [assignment for assignment in remaining if set(assignment.depends_on) <= resolved]
        if not wave:
            raise ValueError("specialist assignment dependencies must form an acyclic graph")
        waves.append(wave)
        wave_roles = {assignment.role for assignment in wave}
        resolved.update(wave_roles)
        remaining = [assignment for assignment in remaining if assignment.role not in wave_roles]
    return waves


def assess_execution_plan_candidate(
    candidate_id: str,
    perspective: str,
    plan: MultiAgentExecutionPlan,
    user_input: str,
    *,
    duplicate_of: str | None = None,
    origin: Literal[
        "independent",
        "negotiated_repair",
        "deterministic_fallback",
    ] = "independent",
    source_candidate_id: str | None = None,
    team_performance_profile: TeamPerformanceProfile | dict[str, Any] | None = None,
) -> ExecutionPlanCandidate:
    required = infer_required_specialist_capabilities(user_input)
    covered = {
        capability
        for assignment in plan.assignments
        for capability in assignment.required_capabilities
    }
    covered_required = required & covered
    capability_score = (
        round(30 * len(covered_required) / len(required))
        if required
        else 30
    )

    fit_points = []
    for assignment in plan.assignments:
        points = 0
        if assignment.required_capabilities:
            points += 8
        if len(assignment.selection_reason.strip()) >= 12:
            points += 6
        if len(assignment.objective.strip()) >= 8 and len(assignment.deliverable.strip()) >= 4:
            points += 6
        fit_points.append(points)
    specialist_score = round(sum(fit_points) / len(fit_points))

    criteria = list(dict.fromkeys(item.strip() for item in plan.success_criteria if item.strip()))
    specificity_markers = (
        "验收",
        "证据",
        "负责人",
        "阈值",
        "指标",
        "时限",
        "回滚",
        "恢复",
        "审计",
        "measurable",
        "evidence",
        "owner",
        "threshold",
        "rollback",
        "deadline",
    )
    specific_count = sum(
        1
        for criterion in criteria
        if len(criterion) >= 16
        or any(marker in criterion.lower() for marker in specificity_markers)
    )
    criterion_count_score = min(12, len(criteria) * 4)
    criterion_specificity_score = round(13 * specific_count / len(criteria)) if criteria else 0
    success_score = criterion_count_score + criterion_specificity_score

    waves = build_execution_waves(plan)
    branch_count = len(plan.assignments)
    parallel_ratio = (
        (branch_count - len(waves)) / (branch_count - 1)
        if branch_count > 1
        else 0
    )
    parallel_score = 8 + round(7 * parallel_ratio)

    roles = {assignment.role for assignment in plan.assignments}
    balance_score = 4 * int("test_engineer" in roles) + 4 * int("operations_analyst" in roles)
    if not required or required <= covered:
        balance_score += 2

    checks = [
        ExecutionPlanCandidateCheck(
            name="capability_coverage",
            label="显式能力覆盖",
            score=capability_score,
            max_score=30,
            detail=(
                f"覆盖 {len(covered_required)}/{len(required)} 项目标显式要求能力"
                if required
                else "目标未声明额外领域能力，基础能力合同完整"
            ),
        ),
        ExecutionPlanCandidateCheck(
            name="specialist_fit",
            label="专业角色匹配",
            score=specialist_score,
            max_score=20,
            detail=f"{branch_count}/{branch_count} 个分支已绑定能力、交付物和组队依据",
        ),
        ExecutionPlanCandidateCheck(
            name="success_contract",
            label="成功标准质量",
            score=success_score,
            max_score=25,
            detail=f"{specific_count}/{len(criteria)} 项标准包含可执行或可审计约束",
        ),
        ExecutionPlanCandidateCheck(
            name="parallel_efficiency",
            label="依赖并行效率",
            score=parallel_score,
            max_score=15,
            detail=f"{branch_count} 个分支编排为 {len(waves)} 个执行波次",
        ),
        ExecutionPlanCandidateCheck(
            name="delivery_balance",
            label="交付防线完整性",
            score=balance_score,
            max_score=10,
            detail=(
                "质量、运营与目标显式领域能力均有责任分支"
                if balance_score == 10
                else "质量或运营基础防线仍可加强"
            ),
        ),
    ]
    fingerprint = hashlib.sha256(
        json.dumps(
            plan.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    score = sum(check.score for check in checks)
    performance_evidence = build_plan_performance_evidence(
        score,
        [assignment.role for assignment in plan.assignments],
        [[assignment.role for assignment in wave] for wave in waves],
        team_performance_profile,
    )
    return ExecutionPlanCandidate(
        candidate_id=candidate_id,
        perspective=perspective,
        origin=origin,
        source_candidate_id=source_candidate_id,
        plan=plan,
        score=score,
        checks=checks,
        performance_evidence=performance_evidence,
        plan_fingerprint=fingerprint,
        duplicate_of=duplicate_of,
    )


def attach_execution_plan_commitments(
    candidate: ExecutionPlanCandidate,
    commitments: list[SpecialistPlanCommitment],
) -> ExecutionPlanCandidate:
    valid_count = sum(commitment.structured for commitment in commitments)
    accept_count = sum(commitment.decision == "ACCEPT" for commitment in commitments)
    challenge_count = sum(
        commitment.decision == "CHALLENGE" for commitment in commitments
    )
    status = (
        "READY"
        if commitments and accept_count == len(commitments)
        else "CHALLENGED"
        if challenge_count
        else "INCOMPLETE"
    )
    return ExecutionPlanCandidate.model_validate(
        {
            **candidate.model_dump(mode="json", exclude={
                "commitments",
                "commitment_status",
                "commitment_valid_count",
                "commitment_accept_count",
                "commitment_challenge_count",
            }),
            "commitments": [commitment.model_dump(mode="json") for commitment in commitments],
            "commitment_status": status,
            "commitment_valid_count": valid_count,
            "commitment_accept_count": accept_count,
            "commitment_challenge_count": challenge_count,
        }
    )


def expand_revision_roles(
    plan: MultiAgentExecutionPlan,
    requested_roles: set[str],
) -> set[SpecialistRole]:
    expanded: set[SpecialistRole] = {
        assignment.role for assignment in plan.assignments if assignment.role in requested_roles
    }
    changed = True
    while changed:
        changed = False
        for assignment in plan.assignments:
            if assignment.role not in expanded and any(role in expanded for role in assignment.depends_on):
                expanded.add(assignment.role)
                changed = True
    return expanded


class AgentHandoff(BaseModel):
    role: SpecialistRole
    objective: str = Field(min_length=4, max_length=500)
    deliverable: str = Field(min_length=2, max_length=200)
    content: str = Field(min_length=1, max_length=24000)
    revision_round: int = Field(default=0, ge=0, le=20)
    plan_version: int = Field(default=0, ge=0)
    upstream_fingerprints: dict[SpecialistRole, str] = Field(default_factory=dict)
    input_fingerprint: str = Field(default="", pattern=r"^(?:|[0-9a-f]{64})$")
    output_fingerprint: str = Field(default="", pattern=r"^(?:|[0-9a-f]{64})$")

    @property
    def is_sealed(self) -> bool:
        return bool(
            self.plan_version
            or self.upstream_fingerprints
            or self.input_fingerprint
            or self.output_fingerprint
        )

    @model_validator(mode="after")
    def validate_lineage_contract(self) -> "AgentHandoff":
        if not self.is_sealed:
            return self
        if self.plan_version < 1 or not self.input_fingerprint or not self.output_fingerprint:
            raise ValueError("sealed handoffs require plan version and input/output fingerprints")
        if len(self.upstream_fingerprints) > 3:
            raise ValueError("handoff lineage cannot contain more than three upstream roles")
        if self.role in self.upstream_fingerprints:
            raise ValueError("handoff lineage cannot reference its own role")
        if any(
            re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None
            for fingerprint in self.upstream_fingerprints.values()
        ):
            raise ValueError("handoff upstream fingerprints must be lowercase SHA-256 values")
        return self


def _stable_fingerprint(value: Any) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _legacy_handoff_fingerprint(handoff: AgentHandoff) -> str:
    return _stable_fingerprint(
        {
            "contract": "legacy-agent-handoff",
            "role": handoff.role,
            "objective": handoff.objective,
            "deliverable": handoff.deliverable,
            "content": handoff.content,
            "revision_round": handoff.revision_round,
        }
    )


def _handoff_input_fingerprint(
    plan: MultiAgentExecutionPlan,
    assignment: SpecialistAssignment,
    *,
    plan_version: int,
    revision_round: int,
    upstream_fingerprints: dict[SpecialistRole, str],
) -> str:
    return _stable_fingerprint(
        {
            "contract": "agent-handoff-input-v1",
            "plan": plan.model_dump(mode="json"),
            "plan_version": plan_version,
            "assignment": assignment.model_dump(mode="json"),
            "revision_round": revision_round,
            "upstream_fingerprints": upstream_fingerprints,
        }
    )


def _handoff_output_fingerprint(
    *,
    role: SpecialistRole,
    objective: str,
    deliverable: str,
    content: str,
    input_fingerprint: str,
) -> str:
    return _stable_fingerprint(
        {
            "contract": "agent-handoff-output-v1",
            "role": role,
            "objective": objective,
            "deliverable": deliverable,
            "content": content,
            "input_fingerprint": input_fingerprint,
        }
    )


def seal_handoff(
    plan: MultiAgentExecutionPlan,
    assignment: SpecialistAssignment,
    content: str,
    *,
    plan_version: int,
    revision_round: int,
    upstream_handoffs: dict[SpecialistRole, AgentHandoff],
) -> AgentHandoff:
    missing_roles = [
        role for role in assignment.depends_on if role not in upstream_handoffs
    ]
    if missing_roles:
        raise ValueError(
            f"cannot seal {assignment.role} handoff without upstream roles: "
            f"{', '.join(missing_roles)}"
        )
    upstream_fingerprints = {
        role: (
            upstream_handoffs[role].output_fingerprint
            or _legacy_handoff_fingerprint(upstream_handoffs[role])
        )
        for role in assignment.depends_on
    }
    input_fingerprint = _handoff_input_fingerprint(
        plan,
        assignment,
        plan_version=plan_version,
        revision_round=revision_round,
        upstream_fingerprints=upstream_fingerprints,
    )
    output_fingerprint = _handoff_output_fingerprint(
        role=assignment.role,
        objective=assignment.objective,
        deliverable=assignment.deliverable,
        content=content,
        input_fingerprint=input_fingerprint,
    )
    return AgentHandoff(
        role=assignment.role,
        objective=assignment.objective,
        deliverable=assignment.deliverable,
        content=content,
        revision_round=revision_round,
        plan_version=plan_version,
        upstream_fingerprints=upstream_fingerprints,
        input_fingerprint=input_fingerprint,
        output_fingerprint=output_fingerprint,
    )


def _lineage_invalid_roles(
    plan: MultiAgentExecutionPlan,
    handoffs: list[AgentHandoff],
    plan_version: int | None,
) -> tuple[list[SpecialistRole], int]:
    handoffs_by_role = {handoff.role: handoff for handoff in handoffs}
    invalid_roles: list[SpecialistRole] = []
    sealed_count = 0
    effective_outputs: dict[SpecialistRole, str] = {}

    for wave in build_execution_waves(plan):
        for assignment in wave:
            handoff = handoffs_by_role.get(assignment.role)
            if handoff is None:
                continue
            if not handoff.is_sealed:
                effective_outputs[handoff.role] = _legacy_handoff_fingerprint(handoff)
                continue
            sealed_count += 1
            upstream_fingerprints = {
                role: effective_outputs[role]
                for role in assignment.depends_on
                if role in effective_outputs
            }
            expected_input = _handoff_input_fingerprint(
                plan,
                assignment,
                plan_version=handoff.plan_version,
                revision_round=handoff.revision_round,
                upstream_fingerprints=upstream_fingerprints,
            )
            expected_output = _handoff_output_fingerprint(
                role=handoff.role,
                objective=handoff.objective,
                deliverable=handoff.deliverable,
                content=handoff.content,
                input_fingerprint=expected_input,
            )
            valid = (
                set(handoff.upstream_fingerprints) == set(assignment.depends_on)
                and handoff.upstream_fingerprints == upstream_fingerprints
                and handoff.objective == assignment.objective
                and handoff.deliverable == assignment.deliverable
                and handoff.input_fingerprint == expected_input
                and handoff.output_fingerprint == expected_output
                and (plan_version is None or handoff.plan_version == plan_version)
            )
            if not valid:
                invalid_roles.append(handoff.role)
            effective_outputs[handoff.role] = expected_output
    return invalid_roles, sealed_count


class CollaborationDecision(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    outcome: str = Field(min_length=2, max_length=2000)
    rationale: str = Field(min_length=2, max_length=2000)
    source_roles: list[SpecialistRole] = Field(min_length=1, max_length=4)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_source_roles(self) -> "CollaborationDecision":
        if len(self.source_roles) != len(set(self.source_roles)):
            raise ValueError("decision source roles must be unique")
        return self


class ConflictPosition(BaseModel):
    role: SpecialistRole
    position: str = Field(min_length=2, max_length=2000)


class CollaborationConflict(BaseModel):
    topic: str = Field(min_length=2, max_length=200)
    positions: list[ConflictPosition] = Field(min_length=2, max_length=4)
    status: Literal["OPEN", "RESOLVED"]
    resolution: str = Field(default="", max_length=2000)
    blocking: bool = True
    revision_roles: list[SpecialistRole] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def validate_conflict(self) -> "CollaborationConflict":
        roles = [position.role for position in self.positions]
        if len(roles) != len(set(roles)):
            raise ValueError("conflict position roles must be unique")
        if self.status == "RESOLVED" and not self.resolution.strip():
            raise ValueError("resolved conflicts require a resolution")
        if len(self.revision_roles) != len(set(self.revision_roles)):
            raise ValueError("conflict revision roles must be unique")
        return self


class CollaborationQuestion(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    owner_role: SpecialistRole
    blocking: bool = False


class ReviewerDecision(BaseModel):
    passed: bool
    score: float = Field(ge=0, le=100)
    issues: list[str] = Field(default_factory=list, max_length=20)
    revision_roles: list[SpecialistRole] = Field(default_factory=list, max_length=4)
    summary: str = Field(default="", max_length=4000)
    decisions: list[CollaborationDecision] = Field(default_factory=list, max_length=20)
    conflicts: list[CollaborationConflict] = Field(default_factory=list, max_length=20)
    open_questions: list[CollaborationQuestion] = Field(default_factory=list, max_length=20)


class ReviewerAssessment(BaseModel):
    role: ReviewerPanelRole
    structured: bool
    passed: bool
    score: float | None = Field(default=None, ge=0, le=100)
    summary: str = Field(default="", max_length=4000)
    issues: list[str] = Field(default_factory=list, max_length=20)


class QualityGateDecision(BaseModel):
    score: float = Field(ge=0, le=100)
    passed: bool
    checks: list[dict[str, Any]] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    revision_roles: list[SpecialistRole] = Field(default_factory=list)
    summary: str = Field(default="", max_length=4000)
    reviewer_summary: str = Field(default="", max_length=8000)
    reviewers: list[ReviewerAssessment] = Field(default_factory=list, max_length=3)
    reviewer_quorum: int = Field(default=0, ge=0, le=3)
    reviewer_valid_count: int = Field(default=0, ge=0, le=3)
    reviewer_pass_count: int = Field(default=0, ge=0, le=3)
    reviewer_disagreement_count: int = Field(default=0, ge=0, le=3)
    decisions: list[CollaborationDecision] = Field(default_factory=list, max_length=20)
    conflicts: list[CollaborationConflict] = Field(default_factory=list, max_length=20)
    open_questions: list[CollaborationQuestion] = Field(default_factory=list, max_length=20)


def _json_candidates(text: str) -> list[str]:
    candidates = [text.strip()]
    candidates.extend(
        re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    )
    first = text.find("{")
    last = text.rfind("}")
    if first >= 0 and last > first:
        candidates.append(text[first : last + 1])
    return list(dict.fromkeys(candidate for candidate in candidates if candidate))


class _SpecialistPlanCommitmentResponse(BaseModel):
    decision: Literal["ACCEPT", "CHALLENGE"]
    confidence: float = Field(ge=0, le=1)
    summary: str = Field(min_length=2, max_length=1000)
    missing_inputs: list[CommitmentDetail] = Field(default_factory=list, max_length=5)
    dependency_concerns: list[CommitmentDetail] = Field(default_factory=list, max_length=5)
    proposed_changes: list[CommitmentDetail] = Field(default_factory=list, max_length=5)


def parse_specialist_plan_commitment(
    text: str,
    role: SpecialistRole,
) -> SpecialistPlanCommitment:
    for candidate in _json_candidates(text):
        try:
            response = _SpecialistPlanCommitmentResponse.model_validate(json.loads(candidate))
            return SpecialistPlanCommitment(
                role=role,
                structured=True,
                **response.model_dump(mode="json"),
            )
        except (json.JSONDecodeError, ValidationError, ValueError):
            continue
    return SpecialistPlanCommitment(
        role=role,
        decision="ABSTAIN",
        structured=False,
        summary="Agent 未返回有效的结构化执行承诺，已记为弃权。",
    )


class _ExecutionPlanArbiterDecision(BaseModel):
    selected_candidate_id: str = Field(pattern=r"^[a-z0-9_]{2,40}$")
    selection_reason: str = Field(min_length=4, max_length=2000)
    dissenting_candidate_ids: list[str] = Field(default_factory=list, max_length=3)
    dissent_summary: str = Field(default="", max_length=2000)


def arbitrate_execution_plan_candidates(
    text: str,
    candidates: list[ExecutionPlanCandidate],
    *,
    invalid_candidate_count: int = 0,
) -> ExecutionPlanDeliberation:
    if not candidates:
        raise ValueError("execution plan arbitration requires at least one valid candidate")
    candidate_ids = {candidate.candidate_id for candidate in candidates}
    ready_candidate_ids = {
        candidate.candidate_id
        for candidate in candidates
        if candidate.commitment_status == "READY"
    }
    distinct_candidate_count = len({candidate.plan_fingerprint for candidate in candidates})
    for raw_decision in _json_candidates(text):
        try:
            decision = _ExecutionPlanArbiterDecision.model_validate(json.loads(raw_decision))
        except (json.JSONDecodeError, ValidationError):
            continue
        if decision.selected_candidate_id not in candidate_ids:
            continue
        if ready_candidate_ids and decision.selected_candidate_id not in ready_candidate_ids:
            continue
        dissenting_ids = list(dict.fromkeys(decision.dissenting_candidate_ids))
        if (
            set(dissenting_ids) - candidate_ids
            or decision.selected_candidate_id in dissenting_ids
        ):
            continue
        return ExecutionPlanDeliberation(
            selected_candidate_id=decision.selected_candidate_id,
            selection_reason=decision.selection_reason,
            arbitration_mode="independent_arbiter",
            candidates=candidates,
            dissenting_candidate_ids=dissenting_ids,
            dissent_summary=decision.dissent_summary,
            invalid_candidate_count=invalid_candidate_count,
            distinct_candidate_count=distinct_candidate_count,
        )

    commitment_rank = {
        "READY": 2,
        "NOT_REVIEWED": 1,
        "INCOMPLETE": 1,
        "CHALLENGED": 0,
    }
    selected = max(
        candidates,
        key=lambda candidate: (
            commitment_rank[candidate.commitment_status],
            (
                candidate.performance_evidence.selection_score
                if candidate.performance_evidence
                else candidate.score
            ),
            candidate.score,
            candidate.candidate_id,
        ),
    )
    alternatives = [
        candidate.candidate_id
        for candidate in candidates
        if candidate.candidate_id != selected.candidate_id
    ]
    return ExecutionPlanDeliberation(
        selected_candidate_id=selected.candidate_id,
        selection_reason=(
            f"独立仲裁未遵守执行者承诺门禁，已优先选择全员接受的"
            f"{selected.perspective}方案（结构 {selected.score}/100，可靠性调整 "
            f"{(selected.performance_evidence.reliability_adjustment if selected.performance_evidence else 0):+d}）。"
            if ready_candidate_ids
            else f"独立仲裁输出不可用，已按确定性评分与历史可靠性选择 {selected.perspective}方案"
            f"（结构 {selected.score}/100，可靠性调整 "
            f"{(selected.performance_evidence.reliability_adjustment if selected.performance_evidence else 0):+d}）。"
            + (
                "该方案仍有执行者质疑，必须经过人工审批。"
                if selected.commitment_status == "CHALLENGED"
                else ""
            )
        ),
        arbitration_mode="deterministic_fallback",
        candidates=candidates,
        dissenting_candidate_ids=alternatives,
        dissent_summary=(
            "其余已验证候选作为少数方案保留，未覆盖选中方案的综合评分优势。"
            if alternatives
            else "本轮只有一个候选通过完整合同校验。"
        ),
        invalid_candidate_count=invalid_candidate_count,
        distinct_candidate_count=distinct_candidate_count,
    )


def parse_execution_plan_candidate(
    text: str,
    user_input: str,
    capability_catalog: list[SpecialistCapabilityProfile] | None = None,
) -> MultiAgentExecutionPlan | None:
    catalog = capability_catalog or default_specialist_capability_catalog()
    required_capabilities = infer_required_specialist_capabilities(user_input)
    ensure_specialist_capabilities_available(catalog, required_capabilities)
    for candidate in _json_candidates(text):
        try:
            plan = MultiAgentExecutionPlan.model_validate(json.loads(candidate))
            return validate_execution_plan_capabilities(plan, catalog, required_capabilities)
        except (json.JSONDecodeError, ValidationError, ValueError):
            continue
    return None


def build_fallback_plan(
    user_input: str,
    capability_catalog: list[SpecialistCapabilityProfile] | None = None,
) -> MultiAgentExecutionPlan:
    catalog = capability_catalog or default_specialist_capability_catalog()
    eligible = ensure_specialist_team_ready(catalog)
    profiles = {profile.role: profile for profile in eligible}
    required_capabilities = infer_required_specialist_capabilities(user_input)
    ensure_specialist_capabilities_available(catalog, required_capabilities)
    includes_knowledge = "knowledge_retrieval" in required_capabilities
    includes_notification = "notification_delivery" in required_capabilities
    selected_roles: list[SpecialistRole] = [
        role
        for role in ("test_engineer", "operations_analyst")
        if role in profiles
    ]
    if (
        includes_knowledge
        and "knowledge_admin" in profiles
        and "knowledge_retrieval" in profiles["knowledge_admin"].capabilities
    ):
        selected_roles.append("knowledge_admin")
    if (
        includes_notification
        and "notification_secretary" in profiles
        and "notification_delivery" in profiles["notification_secretary"].capabilities
    ):
        selected_roles.append("notification_secretary")
    for profile in eligible:
        if len(selected_roles) >= 2:
            break
        if profile.role not in selected_roles:
            selected_roles.append(profile.role)

    templates: dict[SpecialistRole, tuple[str, str]] = {
        "test_engineer": (
            "审查核心用户路径、边界状态、安全风险和可验证验收标准",
            "测试策略、边界场景与验收门禁",
        ),
        "operations_analyst": (
            "审查交付成本、可观测性、灰度发布、故障恢复和运营风险",
            "发布运行手册与风险缓解方案",
        ),
        "knowledge_admin": (
            "审查知识来源、索引质量、检索证据、权限边界和内容生命周期",
            "知识与检索治理方案",
        ),
        "notification_secretary": (
            "审查触达时机、收件人规则、幂等发送、失败重试和用户退订边界",
            "通知触达与失败恢复方案",
        ),
    }
    assignments: list[SpecialistAssignment] = []
    for role in selected_roles[:4]:
        objective, deliverable = templates[role]
        required = list(_SPECIALIST_ROLE_BASELINE_CAPABILITIES[role])
        if role == "knowledge_admin" and includes_knowledge:
            required.append("knowledge_retrieval")
        if role == "notification_secretary" and includes_notification:
            required.append("notification_delivery")
        dependencies: list[SpecialistRole] = []
        if role == "test_engineer" and includes_knowledge and "knowledge_admin" in selected_roles:
            dependencies.append("knowledge_admin")
        if role == "notification_secretary" and "operations_analyst" in selected_roles:
            dependencies.append("operations_analyst")
        assignments.append(
            SpecialistAssignment(
                role=role,
                objective=objective,
                deliverable=deliverable,
                depends_on=dependencies,
                required_capabilities=required,
            )
        )
    plan = MultiAgentExecutionPlan(
        objective=f"形成可实施、可验收、可发布的项目交付方案：{user_input[:500]}",
        rationale="独立专业角色按依赖波次并行审查质量与交付风险，再由项目经理统一集成。",
        assignments=assignments,
        success_criteria=[
            "需求、架构、任务和验收证据可以相互追溯",
            "关键失败场景具有监控、降级或回滚方案",
            "每个专业结论都有明确交付物和后续负责人",
        ],
    )
    return validate_execution_plan_capabilities(plan, catalog, required_capabilities)


def parse_execution_plan(
    text: str,
    user_input: str,
    capability_catalog: list[SpecialistCapabilityProfile] | None = None,
) -> MultiAgentExecutionPlan:
    catalog = capability_catalog or default_specialist_capability_catalog()
    plan = parse_execution_plan_candidate(text, user_input, catalog)
    if plan is not None:
        return plan
    return build_fallback_plan(user_input, catalog)


def evaluate_handoffs(
    plan: MultiAgentExecutionPlan,
    handoffs: list[AgentHandoff],
    *,
    plan_version: int | None = None,
) -> QualityGateDecision:
    expected_roles = [assignment.role for assignment in plan.assignments]
    handoffs_by_role = {handoff.role: handoff for handoff in handoffs}
    missing_roles = [role for role in expected_roles if role not in handoffs_by_role]
    short_roles = [
        role
        for role in expected_roles
        if role in handoffs_by_role and len(handoffs_by_role[role].content.strip()) < 80
    ]
    lineage_invalid_roles, sealed_count = _lineage_invalid_roles(
        plan,
        handoffs,
        plan_version,
    )
    checks = [
        {
            "name": "role_coverage",
            "passed": not missing_roles,
            "detail": f"{len(expected_roles) - len(missing_roles)}/{len(expected_roles)} specialist roles completed",
            "weight": 20,
        },
        {
            "name": "substantive_handoffs",
            "passed": not short_roles and not missing_roles,
            "detail": "all handoffs contain substantive evidence" if not short_roles else f"short outputs: {', '.join(short_roles)}",
            "weight": 25,
        },
        {
            "name": "handoff_lineage",
            "passed": not lineage_invalid_roles,
            "detail": (
                f"{sealed_count} sealed handoffs preserve current upstream lineage"
                if not lineage_invalid_roles
                else f"invalid or stale lineage: {', '.join(lineage_invalid_roles)}"
            ),
            "weight": 20,
        },
        {
            "name": "success_contract",
            "passed": len(plan.success_criteria) >= 2,
            "detail": f"{len(plan.success_criteria)} success criteria defined",
            "weight": 20,
        },
        {
            "name": "specialist_breadth",
            "passed": len(expected_roles) >= 2,
            "detail": f"{len(expected_roles)} specialist branches across {len(build_execution_waves(plan))} execution waves",
            "weight": 15,
        },
    ]
    score = float(sum(check["weight"] for check in checks if check["passed"]))
    issues = []
    if missing_roles:
        issues.append(f"缺少专业交接：{', '.join(missing_roles)}")
    if short_roles:
        issues.append(f"交接内容不足：{', '.join(short_roles)}")
    if lineage_invalid_roles:
        issues.append(f"交接证据链失效：{', '.join(lineage_invalid_roles)}")
    revision_roles = list(
        dict.fromkeys([*missing_roles, *short_roles, *lineage_invalid_roles])
    )
    passed = (
        not missing_roles
        and not short_roles
        and not lineage_invalid_roles
        and score >= 80
    )
    return QualityGateDecision(
        score=score,
        passed=passed,
        checks=checks,
        issues=issues,
        revision_roles=revision_roles,
        summary="所有专业交接满足结构和内容门禁。" if passed else "专业交接尚未满足继续交付的最低门禁。",
    )


def merge_reviewer_decision(
    deterministic: QualityGateDecision,
    reviewer_output: str,
    plan: MultiAgentExecutionPlan,
) -> QualityGateDecision:
    reviewer = _parse_reviewer_decision(reviewer_output)
    if reviewer is None:
        return deterministic.model_copy(
            update={"reviewer_summary": reviewer_output[:8000]}
        )

    expected_roles = {assignment.role for assignment in plan.assignments}
    decisions = []
    for decision in reviewer.decisions:
        source_roles = [role for role in decision.source_roles if role in expected_roles]
        if source_roles:
            decisions.append(decision.model_copy(update={"source_roles": source_roles}))
    conflicts = []
    for conflict in reviewer.conflicts:
        positions = [
            position for position in conflict.positions if position.role in expected_roles
        ]
        if len(positions) < 2:
            continue
        revision_roles = [
            role for role in conflict.revision_roles if role in expected_roles
        ]
        if conflict.status == "OPEN" and conflict.blocking and not revision_roles:
            revision_roles = [position.role for position in positions]
        conflicts.append(
            conflict.model_copy(
                update={"positions": positions, "revision_roles": revision_roles}
            )
        )
    open_questions = [
        question
        for question in reviewer.open_questions
        if question.owner_role in expected_roles
    ]
    blocking_conflicts = [
        conflict
        for conflict in conflicts
        if conflict.status == "OPEN" and conflict.blocking
    ]
    blocking_questions = [question for question in open_questions if question.blocking]
    ledger_revision_roles = [
        role
        for conflict in blocking_conflicts
        for role in (
            conflict.revision_roles
            or [position.role for position in conflict.positions]
        )
    ]
    ledger_revision_roles.extend(question.owner_role for question in blocking_questions)
    revision_roles = list(
        dict.fromkeys(
            [
                *deterministic.revision_roles,
                *(role for role in reviewer.revision_roles if role in expected_roles),
                *ledger_revision_roles,
            ]
        )
    )
    score = min(deterministic.score, reviewer.score)
    if blocking_conflicts or blocking_questions:
        score = min(score, 79.0)
    passed = (
        deterministic.passed
        and reviewer.passed
        and score >= 80
        and not blocking_conflicts
        and not blocking_questions
    )
    ledger_issues = [
        *(f"未解决阻塞冲突：{conflict.topic}" for conflict in blocking_conflicts),
        *(f"未解决阻塞问题：{question.question}" for question in blocking_questions),
    ]
    return deterministic.model_copy(
        update={
            "score": score,
            "passed": passed,
            "issues": list(
                dict.fromkeys(
                    [*deterministic.issues, *reviewer.issues, *ledger_issues]
                )
            ),
            "revision_roles": revision_roles,
            "summary": reviewer.summary or deterministic.summary,
            "reviewer_summary": reviewer_output[:8000],
            "decisions": decisions,
            "conflicts": conflicts,
            "open_questions": open_questions,
        }
    )


def _parse_reviewer_decision(reviewer_output: str) -> ReviewerDecision | None:
    for candidate in _json_candidates(reviewer_output):
        try:
            return ReviewerDecision.model_validate(json.loads(candidate))
        except (json.JSONDecodeError, ValidationError):
            continue
    return None


def _unique_models(items: list[Any], limit: int = 20) -> list[Any]:
    unique: list[Any] = []
    seen: set[str] = set()
    for item in items:
        key = item.model_dump_json()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
        if len(unique) == limit:
            break
    return unique


def merge_reviewer_panel(
    deterministic: QualityGateDecision,
    reviewer_outputs: dict[ReviewerPanelRole, str],
    plan: MultiAgentExecutionPlan,
    *,
    quorum: int = 2,
) -> QualityGateDecision:
    if not 1 <= quorum <= len(reviewer_outputs):
        raise ValueError("reviewer quorum must fit the configured panel")

    assessments: list[ReviewerAssessment] = []
    valid_scores: list[float] = []
    merged_reviews: list[QualityGateDecision] = []
    summaries: list[str] = []
    for role, output in reviewer_outputs.items():
        reviewer = _parse_reviewer_decision(output)
        if reviewer is None:
            assessments.append(
                ReviewerAssessment(
                    role=role,
                    structured=False,
                    passed=False,
                    summary="Reviewer 未返回有效结构化结论，已弃权。",
                    issues=["结构化评审不可用"],
                )
            )
            continue
        merged = merge_reviewer_decision(deterministic, output, plan)
        merged_reviews.append(merged)
        valid_scores.append(reviewer.score)
        summary = reviewer.summary or "Reviewer 未提供摘要。"
        summaries.append(f"{role}: {summary}")
        reviewer_blocked = any(
            conflict.status == "OPEN" and conflict.blocking
            for conflict in merged.conflicts
        ) or any(question.blocking for question in merged.open_questions)
        assessments.append(
            ReviewerAssessment(
                role=role,
                structured=True,
                passed=reviewer.passed and reviewer.score >= 80 and not reviewer_blocked,
                score=reviewer.score,
                summary=summary,
                issues=merged.issues,
            )
        )

    valid_count = len(merged_reviews)
    if valid_count < quorum:
        raise ReviewerPanelQuorumError(valid_count, quorum, len(reviewer_outputs))

    pass_count = sum(assessment.passed for assessment in assessments)
    conflicts = _unique_models(
        [conflict for review in merged_reviews for conflict in review.conflicts]
    )
    open_questions = _unique_models(
        [question for review in merged_reviews for question in review.open_questions]
    )
    decisions = _unique_models(
        [decision for review in merged_reviews for decision in review.decisions]
    )
    blocking_conflicts = [
        conflict
        for conflict in conflicts
        if conflict.status == "OPEN" and conflict.blocking
    ]
    blocking_questions = [question for question in open_questions if question.blocking]
    score = min(deterministic.score, float(median(valid_scores)))
    if blocking_conflicts or blocking_questions:
        score = min(score, 79.0)
    passed = (
        deterministic.passed
        and pass_count >= quorum
        and score >= 80
        and not blocking_conflicts
        and not blocking_questions
    )
    issues = list(
        dict.fromkeys(
            issue
            for review in merged_reviews
            for issue in review.issues
        )
    )
    revision_roles = list(
        dict.fromkeys(
            role
            for review in merged_reviews
            for role in review.revision_roles
        )
    )
    disagreement_count = min(pass_count, valid_count - pass_count)
    return deterministic.model_copy(
        update={
            "score": score,
            "passed": passed,
            "issues": issues,
            "revision_roles": [] if passed else revision_roles,
            "summary": (
                f"评审团 {pass_count}/{valid_count} 票通过，仲裁放行。"
                if passed
                else f"评审团 {pass_count}/{valid_count} 票通过，未满足放行条件。"
            ),
            "reviewer_summary": "\n".join(summaries)[:8000],
            "reviewers": assessments,
            "reviewer_quorum": quorum,
            "reviewer_valid_count": valid_count,
            "reviewer_pass_count": pass_count,
            "reviewer_disagreement_count": disagreement_count,
            "decisions": decisions,
            "conflicts": conflicts,
            "open_questions": open_questions,
        }
    )


def build_task_blueprints(plan: MultiAgentExecutionPlan) -> list[dict[str, str]]:
    role_labels = {
        "test_engineer": "质量",
        "operations_analyst": "运营",
        "knowledge_admin": "知识",
        "notification_secretary": "通知",
    }
    tasks = [
        {
            "title": f"{role_labels[assignment.role]}交付：{assignment.deliverable}"[:100],
            "description": assignment.objective,
            "priority": "HIGH" if assignment.role == "test_engineer" else "MEDIUM",
        }
        for assignment in plan.assignments
    ]
    tasks.extend(
        [
            {
                "title": "跨专业方案集成评审",
                "description": "解决专业交接之间的冲突，并确认需求、架构和交付计划可追溯。",
                "priority": "HIGH",
            },
            {
                "title": "发布验收与回滚演练",
                "description": "验证成功标准、可观测信号、发布门禁和故障回滚路径。",
                "priority": "HIGH",
            },
        ]
    )
    return tasks
