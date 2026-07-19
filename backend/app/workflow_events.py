from typing import Any


PUBLIC_WORKFLOW_EVENT_PAYLOAD_FIELDS = frozenset(
    {
        "approval_required",
        "approval_gate",
        "branch_count",
        "branch_attempt",
        "candidate_count",
        "completed_count",
        "commitment_abstain_count",
        "commitment_accept_count",
        "commitment_challenge_count",
        "commitment_count",
        "decision",
        "decision_count",
        "dependency_count",
        "depends_on",
        "distinct_candidate_count",
        "conflict_count",
        "failed_count",
        "invalid_candidate_count",
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
        "repair_attempted",
        "repair_candidate_id",
        "repair_valid",
        "ready_candidate_count",
        "reviewer_count",
        "reviewer_disagreement_count",
        "reviewer_pass_count",
        "reviewer_quorum",
        "reviewer_valid_count",
        "role",
        "roles",
        "selected_candidate_id",
        "score",
        "source_plan_version",
        "source_candidate_id",
        "success_criteria_count",
        "upstream_count",
        "wave",
        "wave_count",
        "workflow_attempt",
        "will_retry",
        "arbitration_mode",
    }
)


def public_workflow_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key in PUBLIC_WORKFLOW_EVENT_PAYLOAD_FIELDS
    }
