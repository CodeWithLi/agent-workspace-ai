import hashlib
import json
import re
from statistics import median
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator


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
ReviewerPanelRole = Literal["test_engineer", "operations_analyst", "architect"]


class ReviewerPanelQuorumError(ValueError):
    def __init__(self, valid_count: int, quorum: int, panel_count: int) -> None:
        self.valid_count = valid_count
        self.quorum = quorum
        self.panel_count = panel_count
        super().__init__(
            f"reviewer panel quorum unavailable: {valid_count}/{quorum} structured outputs"
        )


class SpecialistAssignment(BaseModel):
    role: SpecialistRole
    objective: str = Field(min_length=4, max_length=500)
    deliverable: str = Field(min_length=2, max_length=200)
    depends_on: list[SpecialistRole] = Field(default_factory=list, max_length=3)


class MultiAgentExecutionPlan(BaseModel):
    objective: str = Field(min_length=4, max_length=1000)
    rationale: str = Field(min_length=4, max_length=1000)
    assignments: list[SpecialistAssignment] = Field(min_length=2, max_length=4)
    success_criteria: list[str] = Field(min_length=2, max_length=10)

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
        return self


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


def build_fallback_plan(user_input: str) -> MultiAgentExecutionPlan:
    normalized = user_input.lower()
    includes_knowledge = any(
        keyword in normalized
        for keyword in (
            "rag",
            "知识",
            "文档",
            "搜索",
            "检索",
            "数据治理",
            "embedding",
        )
    )
    includes_notification = any(
        keyword in normalized
        for keyword in (
            "通知",
            "邮件",
            "短信",
            "提醒",
            "调度",
            "定时",
            "notification",
            "email",
        )
    )
    assignments = [
        SpecialistAssignment(
            role="test_engineer",
            objective="审查核心用户路径、边界状态、安全风险和可验证验收标准",
            deliverable="测试策略、边界场景与验收门禁",
            depends_on=["knowledge_admin"] if includes_knowledge else [],
        ),
        SpecialistAssignment(
            role="operations_analyst",
            objective="审查交付成本、可观测性、灰度发布、故障恢复和运营风险",
            deliverable="发布运行手册与风险缓解方案",
        ),
    ]
    if includes_knowledge:
        assignments.append(
            SpecialistAssignment(
                role="knowledge_admin",
                objective="审查知识来源、索引质量、检索证据、权限边界和内容生命周期",
                deliverable="知识与检索治理方案",
            )
        )
    if includes_notification:
        assignments.append(
            SpecialistAssignment(
                role="notification_secretary",
                objective="审查触达时机、收件人规则、幂等发送、失败重试和用户退订边界",
                deliverable="通知触达与失败恢复方案",
                depends_on=["operations_analyst"],
            )
        )
    return MultiAgentExecutionPlan(
        objective=f"形成可实施、可验收、可发布的项目交付方案：{user_input[:500]}",
        rationale="独立专业角色按依赖波次并行审查质量与交付风险，再由项目经理统一集成。",
        assignments=assignments,
        success_criteria=[
            "需求、架构、任务和验收证据可以相互追溯",
            "关键失败场景具有监控、降级或回滚方案",
            "每个专业结论都有明确交付物和后续负责人",
        ],
    )


def parse_execution_plan(text: str, user_input: str) -> MultiAgentExecutionPlan:
    for candidate in _json_candidates(text):
        try:
            return MultiAgentExecutionPlan.model_validate(json.loads(candidate))
        except (json.JSONDecodeError, ValidationError):
            continue
    return build_fallback_plan(user_input)


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
