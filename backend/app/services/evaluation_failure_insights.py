import hashlib
import re
from collections import Counter
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EvaluationCase
from app.services.evaluation_feedback import list_feedback_candidates


SOURCE_LIMIT = 500
CLUSTER_SIMILARITY_THRESHOLD = 0.35
PARTIAL_COVERAGE_THRESHOLD = 0.30
FULL_COVERAGE_THRESHOLD = 0.65

_TEXT_PARTS = re.compile(r"[a-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", re.IGNORECASE)
_IGNORED_TOKENS = {
    "agent",
    "email_redacted",
    "phone_redacted",
    "id_redacted",
    "bank_card_redacted",
    "ip_redacted",
    "credential_redacted",
    "name_redacted",
    "the",
    "this",
    "that",
    "with",
    "from",
    "用户",
    "回答",
    "这个",
    "一个",
    "需要",
    "进行",
}


def _tokens(value: str) -> set[str]:
    output: set[str] = set()
    for part in _TEXT_PARTS.findall(value.lower()):
        if "\u4e00" <= part[0] <= "\u9fff":
            output.update(part[index : index + 2] for index in range(len(part) - 1))
        else:
            output.add(part)
    return {token for token in output if token not in _IGNORED_TOKENS}


def _feedback_tokens(row: Mapping[str, Any]) -> set[str]:
    return _tokens(f"{row.get('input_text') or ''}\n{row.get('comment') or ''}")


def _case_tokens(case: EvaluationCase) -> set[str]:
    return _tokens(
        "\n".join(
            (
                case.name,
                case.input_text,
                case.expected_keywords_json,
                case.forbidden_keywords_json,
                case.rubric,
            )
        )
    )


def _similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return 2 * len(left & right) / (len(left) + len(right))


def _cluster_rows(rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    clusters: list[list[dict[str, Any]]] = []
    cluster_tokens: list[list[set[str]]] = []
    for row in sorted(rows, key=lambda item: (str(item["agent_role"]), int(item["feedback_id"]))):
        tokens = _feedback_tokens(row)
        best_index = -1
        best_score = 0.0
        for index, members in enumerate(clusters):
            if members[0]["agent_role"] != row["agent_role"]:
                continue
            score = max((_similarity(tokens, item) for item in cluster_tokens[index]), default=0.0)
            if score > best_score:
                best_index = index
                best_score = score
        if best_index >= 0 and best_score >= CLUSTER_SIMILARITY_THRESHOLD:
            clusters[best_index].append(row)
            cluster_tokens[best_index].append(tokens)
        else:
            clusters.append([row])
            cluster_tokens.append([tokens])
    return clusters


def _cluster_id(role: str, members: list[dict[str, Any]]) -> str:
    signature = "\n".join(
        sorted(token for member in members for token in _feedback_tokens(member))
    )
    feedback_ids = ",".join(str(member["feedback_id"]) for member in members)
    digest = hashlib.sha256(
        f"{role}\n{signature}\n{feedback_ids}".encode("utf-8")
    ).hexdigest()[:12]
    return f"{role}-{digest}"


def _representative(members: list[dict[str, Any]]) -> dict[str, Any]:
    pending = [member for member in members if member["status"] == "PENDING"]
    candidates = pending or members
    return max(candidates, key=lambda item: int(item["feedback_id"]))


def _cluster_label(representative: Mapping[str, Any]) -> str:
    value = str(representative.get("comment") or representative.get("input_text") or "未命名失败模式")
    return value if len(value) <= 120 else f"{value[:119]}…"


def _coverage(
    members: list[dict[str, Any]],
    member_tokens: set[str],
    cases: list[EvaluationCase],
    case_tokens: dict[int, set[str]],
) -> tuple[str, float, list[int]]:
    direct_case_ids = {
        int(member["evaluation_case_id"])
        for member in members
        if member.get("evaluation_case_id") is not None
    }
    scored = sorted(
        (
            (1.0 if case.id in direct_case_ids else _similarity(member_tokens, case_tokens[case.id]), case.id)
            for case in cases
            if case.agent_role == members[0]["agent_role"]
        ),
        key=lambda item: (-item[0], item[1]),
    )
    best_score = scored[0][0] if scored else 0.0
    matching_ids = [case_id for score, case_id in scored if score >= PARTIAL_COVERAGE_THRESHOLD][:5]
    if best_score >= FULL_COVERAGE_THRESHOLD:
        return "COVERED", round(best_score, 4), matching_ids
    if best_score >= PARTIAL_COVERAGE_THRESHOLD:
        return "PARTIAL", round(best_score, 4), matching_ids
    return "GAP", round(best_score, 4), []


def _recommended_action(status: str, pending_count: int) -> str:
    if status == "GAP":
        return "CREATE_CASE"
    if status == "PARTIAL":
        return "STRENGTHEN_CASE"
    return "REVIEW_PENDING" if pending_count else "MONITOR"


def _priority(status: str, pending_count: int, failure_count: int) -> str:
    if status == "GAP" and (pending_count >= 2 or failure_count >= 3):
        return "HIGH"
    if status in {"GAP", "PARTIAL"} or pending_count >= 3:
        return "MEDIUM"
    return "LOW"


def build_failure_insights(db: Session) -> dict[str, Any]:
    pending_rows = list_feedback_candidates(db, "PENDING", limit=SOURCE_LIMIT + 1)
    converted_rows = list_feedback_candidates(db, "CONVERTED", limit=SOURCE_LIMIT + 1)
    source_limit_reached = len(pending_rows) > SOURCE_LIMIT or len(converted_rows) > SOURCE_LIMIT
    rows = [*pending_rows[:SOURCE_LIMIT], *converted_rows[:SOURCE_LIMIT]]
    cases = list(
        db.scalars(
            select(EvaluationCase)
            .where(EvaluationCase.enabled.is_(True))
            .order_by(EvaluationCase.id)
        )
    )
    case_tokens = {case.id: _case_tokens(case) for case in cases}
    clusters: list[dict[str, Any]] = []
    for members in _cluster_rows(rows):
        representative = _representative(members)
        tokens = set().union(*(_feedback_tokens(member) for member in members))
        token_counts = Counter(token for member in members for token in _feedback_tokens(member))
        signature_terms = [
            token for token, _ in sorted(token_counts.items(), key=lambda item: (-item[1], item[0]))[:8]
        ]
        coverage_status, coverage_score, matching_case_ids = _coverage(
            members,
            tokens,
            cases,
            case_tokens,
        )
        pending_count = sum(member["status"] == "PENDING" for member in members)
        converted_count = sum(member["status"] == "CONVERTED" for member in members)
        clusters.append(
            {
                "cluster_id": _cluster_id(str(representative["agent_role"]), members),
                "agent_role": str(representative["agent_role"]),
                "label": _cluster_label(representative),
                "failure_count": len(members),
                "pending_count": pending_count,
                "converted_count": converted_count,
                "redacted_value_count": sum(int(member.get("redaction_count") or 0) for member in members),
                "signature_terms": signature_terms,
                "coverage_status": coverage_status,
                "coverage_score": coverage_score,
                "matching_case_ids": matching_case_ids,
                "priority": _priority(coverage_status, pending_count, len(members)),
                "recommended_action": _recommended_action(coverage_status, pending_count),
                "feedback_ids": sorted(int(member["feedback_id"]) for member in members),
                "representative": representative,
            }
        )
    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    clusters.sort(
        key=lambda cluster: (
            priority_order[cluster["priority"]],
            -int(cluster["failure_count"]),
            str(cluster["agent_role"]),
            str(cluster["cluster_id"]),
        )
    )
    covered_count = sum(cluster["coverage_status"] == "COVERED" for cluster in clusters)
    partial_count = sum(cluster["coverage_status"] == "PARTIAL" for cluster in clusters)
    gap_count = sum(cluster["coverage_status"] == "GAP" for cluster in clusters)
    total_clusters = len(clusters)
    return {
        "source_feedback_count": len(rows),
        "pending_feedback_count": len(pending_rows[:SOURCE_LIMIT]),
        "converted_feedback_count": len(converted_rows[:SOURCE_LIMIT]),
        "redacted_value_count": sum(int(row.get("redaction_count") or 0) for row in rows),
        "total_cluster_count": total_clusters,
        "covered_cluster_count": covered_count,
        "partial_cluster_count": partial_count,
        "gap_cluster_count": gap_count,
        "coverage_percent": round(covered_count / total_clusters, 4) if total_clusters else 1.0,
        "source_limit_reached": source_limit_reached,
        "clusters": clusters,
    }
