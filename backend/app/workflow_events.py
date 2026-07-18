from typing import Any


PUBLIC_WORKFLOW_EVENT_PAYLOAD_FIELDS = frozenset(
    {
        "approval_required",
        "approval_gate",
        "branch_count",
        "completed_count",
        "decision",
        "dependency_count",
        "depends_on",
        "failed_count",
        "next_node",
        "output_chars",
        "plan_version",
        "revision_roles",
        "revision_round",
        "revision_count",
        "role",
        "roles",
        "score",
        "source_plan_version",
        "success_criteria_count",
        "wave",
        "wave_count",
        "workflow_attempt",
    }
)


def public_workflow_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key in PUBLIC_WORKFLOW_EVENT_PAYLOAD_FIELDS
    }
