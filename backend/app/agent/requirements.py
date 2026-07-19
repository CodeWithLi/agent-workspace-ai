import hashlib
import json
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.models import AgentRole


RequirementItem = Annotated[str, Field(min_length=2, max_length=500)]


class RequirementAcceptanceCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion_id: str = Field(pattern=r"^AC-[0-9]{2}$")
    description: str = Field(min_length=4, max_length=500)
    evidence: str = Field(min_length=4, max_length=500)
    priority: Literal["MUST", "SHOULD", "COULD"]


class RequirementContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: str = Field(min_length=4, max_length=1000)
    target_users: list[RequirementItem] = Field(min_length=1, max_length=8)
    in_scope: list[RequirementItem] = Field(min_length=2, max_length=10)
    out_of_scope: list[RequirementItem] = Field(default_factory=list, max_length=8)
    constraints: list[RequirementItem] = Field(default_factory=list, max_length=8)
    assumptions: list[RequirementItem] = Field(default_factory=list, max_length=8)
    acceptance_criteria: list[RequirementAcceptanceCriterion] = Field(min_length=2, max_length=10)

    @model_validator(mode="after")
    def validate_contract(self) -> "RequirementContract":
        groups = (
            self.target_users,
            self.in_scope,
            self.out_of_scope,
            self.constraints,
            self.assumptions,
        )
        if any(len(items) != len(set(items)) for items in groups):
            raise ValueError("requirement contract list items must be unique")
        expected_ids = [f"AC-{index:02d}" for index in range(1, len(self.acceptance_criteria) + 1)]
        actual_ids = [criterion.criterion_id for criterion in self.acceptance_criteria]
        if actual_ids != expected_ids:
            raise ValueError("acceptance criterion ids must be sequential and stable")
        descriptions = [criterion.description for criterion in self.acceptance_criteria]
        if len(descriptions) != len(set(descriptions)):
            raise ValueError("acceptance criterion descriptions must be unique")
        return self


class _RequirementAcceptanceCriterionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=4, max_length=500)
    evidence: str = Field(min_length=4, max_length=500)
    priority: Literal["MUST", "SHOULD", "COULD"]


class _RequirementContractResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: str = Field(min_length=4, max_length=1000)
    target_users: list[RequirementItem] = Field(min_length=1, max_length=8)
    in_scope: list[RequirementItem] = Field(min_length=2, max_length=10)
    out_of_scope: list[RequirementItem] = Field(default_factory=list, max_length=8)
    constraints: list[RequirementItem] = Field(default_factory=list, max_length=8)
    assumptions: list[RequirementItem] = Field(default_factory=list, max_length=8)
    acceptance_criteria: list[_RequirementAcceptanceCriterionResponse] = Field(
        min_length=2,
        max_length=10,
    )


RequirementReviewRole = Literal["architect", "test_engineer"]


class RequirementReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: RequirementReviewRole
    decision: Literal["ACCEPT", "CHALLENGE", "ABSTAIN"]
    structured: bool
    confidence: float | None = Field(default=None, ge=0, le=1)
    summary: str = Field(min_length=2, max_length=1000)
    concerns: list[RequirementItem] = Field(default_factory=list, max_length=6)
    proposed_changes: list[RequirementItem] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def validate_review(self) -> "RequirementReview":
        if len(self.concerns) != len(set(self.concerns)):
            raise ValueError("requirement review concerns must be unique")
        if len(self.proposed_changes) != len(set(self.proposed_changes)):
            raise ValueError("requirement review changes must be unique")
        if self.structured:
            if self.decision == "ABSTAIN" or self.confidence is None:
                raise ValueError("structured requirement reviews require a decision and confidence")
        elif self.decision != "ABSTAIN" or self.confidence is not None:
            raise ValueError("unstructured requirement reviews must abstain without confidence")
        if self.decision == "ACCEPT" and (self.concerns or self.proposed_changes):
            raise ValueError("accepted requirement reviews cannot contain unresolved concerns")
        if self.decision == "CHALLENGE" and not (self.concerns or self.proposed_changes):
            raise ValueError("challenged requirement reviews require concrete evidence")
        return self


class RequirementConsensus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract: RequirementContract
    contract_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    origin: Literal["model_draft", "negotiated_revision", "deterministic_baseline"]
    source_contract_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    reviews: list[RequirementReview] = Field(min_length=2, max_length=2)
    revision_challenges: list[RequirementReview] = Field(default_factory=list, max_length=2)
    status: Literal["READY", "CHALLENGED", "INCOMPLETE"]
    reviewer_valid_count: int = Field(ge=0, le=2)
    reviewer_accept_count: int = Field(ge=0, le=2)
    reviewer_challenge_count: int = Field(ge=0, le=2)
    revision_attempted: bool = False
    revision_valid: bool = False

    @model_validator(mode="after")
    def validate_consensus(self) -> "RequirementConsensus":
        roles = [review.role for review in self.reviews]
        if set(roles) != {"architect", "test_engineer"} or len(roles) != len(set(roles)):
            raise ValueError("requirement consensus requires architect and test reviewer evidence")
        if any(
            review.decision != "CHALLENGE" or not review.structured
            for review in self.revision_challenges
        ):
            raise ValueError("requirement revision evidence must contain structured challenges")
        valid_count = sum(review.structured for review in self.reviews)
        accept_count = sum(review.decision == "ACCEPT" for review in self.reviews)
        challenge_count = sum(review.decision == "CHALLENGE" for review in self.reviews)
        expected_status = (
            "READY"
            if accept_count == len(self.reviews)
            else "CHALLENGED"
            if challenge_count
            else "INCOMPLETE"
        )
        if (
            self.reviewer_valid_count != valid_count
            or self.reviewer_accept_count != accept_count
            or self.reviewer_challenge_count != challenge_count
            or self.status != expected_status
        ):
            raise ValueError("requirement consensus summary does not match reviewer evidence")
        if self.revision_valid and not self.revision_attempted:
            raise ValueError("valid requirement revisions must be attempted")
        if self.origin == "negotiated_revision":
            if not self.revision_valid or self.source_contract_fingerprint is None:
                raise ValueError("negotiated requirements require valid source evidence")
        elif self.source_contract_fingerprint is not None:
            raise ValueError("only negotiated requirements may reference a source fingerprint")
        return self


class _RequirementReviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["ACCEPT", "CHALLENGE"]
    confidence: float = Field(ge=0, le=1)
    summary: str = Field(min_length=2, max_length=1000)
    concerns: list[RequirementItem] = Field(default_factory=list, max_length=6)
    proposed_changes: list[RequirementItem] = Field(default_factory=list, max_length=6)


def _json_candidates(text: str) -> list[str]:
    candidates = [text.strip()]
    candidates.extend(
        match.strip()
        for match in re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    )
    first = text.find("{")
    last = text.rfind("}")
    if first >= 0 and last > first:
        candidates.append(text[first : last + 1])
    return list(dict.fromkeys(candidate for candidate in candidates if candidate))


def requirement_contract_fingerprint(contract: RequirementContract) -> str:
    return hashlib.sha256(
        json.dumps(
            contract.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def parse_requirement_contract(text: str, user_input: str) -> RequirementContract | None:
    del user_input
    for candidate in _json_candidates(text):
        try:
            payload = json.loads(candidate)
            try:
                return RequirementContract.model_validate(payload)
            except ValidationError:
                response = _RequirementContractResponse.model_validate(payload)
                return RequirementContract(
                    **response.model_dump(mode="json", exclude={"acceptance_criteria"}),
                    acceptance_criteria=[
                        RequirementAcceptanceCriterion(
                            criterion_id=f"AC-{index:02d}",
                            **criterion.model_dump(mode="json"),
                        )
                        for index, criterion in enumerate(response.acceptance_criteria, start=1)
                    ],
                )
        except (json.JSONDecodeError, ValidationError, ValueError):
            continue
    return None


def build_fallback_requirement_contract(user_input: str) -> RequirementContract:
    objective = user_input.strip()[:800] or "形成可实施、可验证的项目交付目标"
    objective_item = objective[:360]
    return RequirementContract(
        objective=f"围绕「{objective}」形成可实施、可验证的需求合同",
        target_users=["业务负责人", "目标用户", "项目交付团队"],
        in_scope=[
            f"完成用户明确目标：{objective_item}",
            "形成端到端核心路径、异常边界与可审计交付证据",
        ],
        out_of_scope=["用户目标未明确授权的外部系统改造与数据迁移"],
        constraints=["不得虚构外部服务、权限、数据或生产环境条件"],
        assumptions=["未明确的业务边界需要在执行前由负责人确认"],
        acceptance_criteria=[
            RequirementAcceptanceCriterion(
                criterion_id="AC-01",
                description=f"用户目标「{objective_item}」的核心路径能够端到端完成",
                evidence="可复现步骤、预期结果、实际结果与负责人记录",
                priority="MUST",
            ),
            RequirementAcceptanceCriterion(
                criterion_id="AC-02",
                description="关键失败场景具有明确提示、恢复路径和责任边界",
                evidence="边界用例、失败信号、恢复结果和审计记录",
                priority="MUST",
            ),
        ],
    )


def parse_requirement_review(text: str, role: RequirementReviewRole) -> RequirementReview:
    for candidate in _json_candidates(text):
        try:
            response = _RequirementReviewResponse.model_validate(json.loads(candidate))
            return RequirementReview(
                role=role,
                structured=True,
                **response.model_dump(mode="json"),
            )
        except (json.JSONDecodeError, ValidationError, ValueError):
            continue
    return RequirementReview(
        role=role,
        decision="ABSTAIN",
        structured=False,
        summary="Agent 未返回有效的结构化需求评审，已记为弃权。",
    )


def build_requirement_consensus(
    contract: RequirementContract,
    reviews: list[RequirementReview],
    *,
    origin: Literal["model_draft", "negotiated_revision", "deterministic_baseline"],
    source_contract_fingerprint: str | None = None,
    revision_challenges: list[RequirementReview] | None = None,
    revision_attempted: bool = False,
    revision_valid: bool = False,
) -> RequirementConsensus:
    valid_count = sum(review.structured for review in reviews)
    accept_count = sum(review.decision == "ACCEPT" for review in reviews)
    challenge_count = sum(review.decision == "CHALLENGE" for review in reviews)
    status = (
        "READY"
        if reviews and accept_count == len(reviews)
        else "CHALLENGED"
        if challenge_count
        else "INCOMPLETE"
    )
    return RequirementConsensus(
        contract=contract,
        contract_fingerprint=requirement_contract_fingerprint(contract),
        origin=origin,
        source_contract_fingerprint=source_contract_fingerprint,
        reviews=reviews,
        revision_challenges=revision_challenges or [],
        status=status,
        reviewer_valid_count=valid_count,
        reviewer_accept_count=accept_count,
        reviewer_challenge_count=challenge_count,
        revision_attempted=revision_attempted,
        revision_valid=revision_valid,
    )


REQUIREMENT_REVIEW_ROLES: tuple[tuple[AgentRole, RequirementReviewRole], ...] = (
    (AgentRole.architect, "architect"),
    (AgentRole.test_engineer, "test_engineer"),
)
