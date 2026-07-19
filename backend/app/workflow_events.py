from typing import Any


PUBLIC_WORKFLOW_EVENT_PAYLOAD_FIELDS = frozenset(
    {
        "approval_required",
        "approval_gate",
        "branch_count",
        "branch_attempt",
        "completed_count",
        "decision",
        "decision_count",
        "dependency_count",
        "depends_on",
        "conflict_count",
        "failed_count",
        "lineage_sealed",
        "next_node",
        "next_branch_attempt",
        "open_blocker_count",
        "output_chars",
        "plan_version",
        "revision_roles",
        "revision_round",
        "revision_count",
        "retry_delay_seconds",
        "retryable",
        "retrying_count",
        "retryable_count",
        "recovery_count",
        "reviewer_count",
        "reviewer_disagreement_count",
        "reviewer_pass_count",
        "reviewer_quorum",
        "reviewer_valid_count",
        "role",
        "roles",
        "score",
        "source_plan_version",
        "success_criteria_count",
        "upstream_count",
        "wave",
        "wave_count",
        "workflow_attempt",
        "will_retry",
    }
)


def public_workflow_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key in PUBLIC_WORKFLOW_EVENT_PAYLOAD_FIELDS
    }
