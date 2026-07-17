import json
import re
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


class SpecialistAssignment(BaseModel):
    role: SpecialistRole
    objective: str = Field(min_length=4, max_length=500)
    deliverable: str = Field(min_length=2, max_length=200)


class MultiAgentExecutionPlan(BaseModel):
    objective: str = Field(min_length=4, max_length=1000)
    rationale: str = Field(min_length=4, max_length=1000)
    assignments: list[SpecialistAssignment] = Field(min_length=2, max_length=4)
    success_criteria: list[str] = Field(min_length=2, max_length=10)

    @model_validator(mode="after")
    def validate_unique_assignments(self) -> "MultiAgentExecutionPlan":
        roles = [assignment.role for assignment in self.assignments]
        if len(roles) != len(set(roles)):
            raise ValueError("specialist assignment roles must be unique")
        return self


class AgentHandoff(BaseModel):
    role: SpecialistRole
    objective: str = Field(min_length=4, max_length=500)
    deliverable: str = Field(min_length=2, max_length=200)
    content: str = Field(min_length=1, max_length=24000)
    revision_round: int = Field(default=0, ge=0, le=20)


class QualityGateDecision(BaseModel):
    score: float = Field(ge=0, le=100)
    passed: bool
    checks: list[dict[str, Any]] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    revision_roles: list[SpecialistRole] = Field(default_factory=list)
    summary: str = Field(default="", max_length=4000)
    reviewer_summary: str = Field(default="", max_length=8000)


class ReviewerDecision(BaseModel):
    passed: bool
    score: float = Field(ge=0, le=100)
    issues: list[str] = Field(default_factory=list, max_length=20)
    revision_roles: list[SpecialistRole] = Field(default_factory=list, max_length=4)
    summary: str = Field(default="", max_length=4000)


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
    assignments = [
        SpecialistAssignment(
            role="test_engineer",
            objective="审查核心用户路径、边界状态、安全风险和可验证验收标准",
            deliverable="测试策略、边界场景与验收门禁",
        ),
        SpecialistAssignment(
            role="operations_analyst",
            objective="审查交付成本、可观测性、灰度发布、故障恢复和运营风险",
            deliverable="发布运行手册与风险缓解方案",
        ),
    ]
    knowledge_keywords = (
        "rag",
        "知识",
        "文档",
        "搜索",
        "检索",
        "数据治理",
        "embedding",
    )
    notification_keywords = (
        "通知",
        "邮件",
        "短信",
        "提醒",
        "调度",
        "定时",
        "notification",
        "email",
    )
    if any(keyword in normalized for keyword in knowledge_keywords):
        assignments.append(
            SpecialistAssignment(
                role="knowledge_admin",
                objective="审查知识来源、索引质量、检索证据、权限边界和内容生命周期",
                deliverable="知识与检索治理方案",
            )
        )
    if any(keyword in normalized for keyword in notification_keywords):
        assignments.append(
            SpecialistAssignment(
                role="notification_secretary",
                objective="审查触达时机、收件人规则、幂等发送、失败重试和用户退订边界",
                deliverable="通知触达与失败恢复方案",
            )
        )
    return MultiAgentExecutionPlan(
        objective=f"形成可实施、可验收、可发布的项目交付方案：{user_input[:500]}",
        rationale="质量和交付风险需要由独立专业角色并行审查，再由项目经理统一集成。",
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
) -> QualityGateDecision:
    expected_roles = [assignment.role for assignment in plan.assignments]
    handoffs_by_role = {handoff.role: handoff for handoff in handoffs}
    missing_roles = [role for role in expected_roles if role not in handoffs_by_role]
    short_roles = [
        role
        for role in expected_roles
        if role in handoffs_by_role and len(handoffs_by_role[role].content.strip()) < 80
    ]
    checks = [
        {
            "name": "role_coverage",
            "passed": not missing_roles,
            "detail": f"{len(expected_roles) - len(missing_roles)}/{len(expected_roles)} specialist roles completed",
            "weight": 25,
        },
        {
            "name": "substantive_handoffs",
            "passed": not short_roles and not missing_roles,
            "detail": "all handoffs contain substantive evidence" if not short_roles else f"short outputs: {', '.join(short_roles)}",
            "weight": 35,
        },
        {
            "name": "success_contract",
            "passed": len(plan.success_criteria) >= 2,
            "detail": f"{len(plan.success_criteria)} success criteria defined",
            "weight": 20,
        },
        {
            "name": "parallel_breadth",
            "passed": len(expected_roles) >= 2,
            "detail": f"{len(expected_roles)} independent specialist branches",
            "weight": 20,
        },
    ]
    score = float(sum(check["weight"] for check in checks if check["passed"]))
    issues = []
    if missing_roles:
        issues.append(f"缺少专业交接：{', '.join(missing_roles)}")
    if short_roles:
        issues.append(f"交接内容不足：{', '.join(short_roles)}")
    revision_roles = list(dict.fromkeys([*missing_roles, *short_roles]))
    passed = not missing_roles and not short_roles and score >= 80
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
    reviewer: ReviewerDecision | None = None
    for candidate in _json_candidates(reviewer_output):
        try:
            reviewer = ReviewerDecision.model_validate(json.loads(candidate))
            break
        except (json.JSONDecodeError, ValidationError):
            continue
    if reviewer is None:
        return deterministic.model_copy(
            update={"reviewer_summary": reviewer_output[:8000]}
        )

    expected_roles = {assignment.role for assignment in plan.assignments}
    revision_roles = list(
        dict.fromkeys(
            [
                *deterministic.revision_roles,
                *(role for role in reviewer.revision_roles if role in expected_roles),
            ]
        )
    )
    score = min(deterministic.score, reviewer.score)
    passed = deterministic.passed and reviewer.passed and score >= 80
    return deterministic.model_copy(
        update={
            "score": score,
            "passed": passed,
            "issues": list(dict.fromkeys([*deterministic.issues, *reviewer.issues])),
            "revision_roles": revision_roles,
            "summary": reviewer.summary or deterministic.summary,
            "reviewer_summary": reviewer_output[:8000],
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
