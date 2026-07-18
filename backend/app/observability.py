from __future__ import annotations

import json
import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.config import get_settings
from app.models import (
    Agent,
    LLMUsage,
    Notification,
    Project,
    ProjectMember,
    TraceAlert,
    TraceAlertStatus,
    User,
    UserRole,
    WorkflowEvent,
    WorkflowRun,
    WorkflowStatus,
)
from app.schemas import (
    TraceAgentMetricOut,
    TraceAlertCollectionOut,
    TraceAlertOut,
    TraceAlertSummaryOut,
    TraceAnomalyOut,
    TraceBottleneckOut,
    TraceComparisonAgentOut,
    TraceComparisonMetricOut,
    TraceComparisonOut,
    TraceComparisonSpanOut,
    TraceComparisonSummaryOut,
    TraceDetailMetricsOut,
    TraceDetailOut,
    TraceEventDetailOut,
    TraceHealthOut,
    TraceHealthSummaryOut,
    TraceMetricSummaryOut,
    TraceModelCallOut,
    TraceOverviewOut,
    TraceProjectOptionOut,
    TraceRunOut,
    TraceSLOMetricOut,
    TraceSLOTargetsOut,
    TraceSpanOut,
    TraceTrendPointOut,
    TraceWindowOut,
)


RUN_ANALYSIS_LIMIT = 2_000
USAGE_ANALYSIS_LIMIT = 50_000
BOTTLENECK_RUN_LIMIT = 500
RECENT_RUN_LIMIT = 100
ANOMALY_LIMIT = 20
ALERT_LIST_LIMIT = 200
ALERT_SYNC_CREATE_LIMIT = 100
settings = get_settings()

ACTIVE_STATUSES = {
    WorkflowStatus.queued,
    WorkflowStatus.running,
    WorkflowStatus.cancelling,
    WorkflowStatus.compensating,
}
FAILED_STATUSES = {WorkflowStatus.failed, WorkflowStatus.compensation_failed}
HEALTH_STATUSES = {WorkflowStatus.completed, *FAILED_STATUSES}

NODE_LABELS = {
    "requirement": "需求分析",
    "product": "产品方案",
    "architect": "架构设计",
    "planning": "动态规划",
    "plan_review": "计划审批",
    "specialists": "专业分支",
    "quality_gate": "质量门禁",
    "quality_review": "人工修订",
    "project_manager": "项目计划",
    "tester": "测试方案",
    "report": "项目报告",
    "completed": "完成",
}

NODE_AGENT_ROLES = {
    "requirement": "product_manager",
    "product": "product_manager",
    "architect": "architect",
    "planning": "project_manager",
    "quality_gate": "test_engineer",
    "project_manager": "project_manager",
    "tester": "test_engineer",
    "report": "operations_analyst",
}

ROLE_LABELS = {
    "product_manager": "AI产品经理",
    "project_manager": "AI项目经理",
    "architect": "AI架构师",
    "test_engineer": "AI测试工程师",
    "meeting_secretary": "AI会议纪要员",
    "knowledge_admin": "AI知识库管理员",
    "notification_secretary": "AI通知秘书",
    "operations_analyst": "AI运营分析师",
}

PUBLIC_EVENT_PAYLOAD_FIELDS = {
    "approval_required",
    "approval_gate",
    "branch_count",
    "decision",
    "next_node",
    "output_chars",
    "plan_version",
    "revision_roles",
    "revision_round",
    "revision_count",
    "role",
    "roles",
    "score",
    "success_criteria_count",
    "source_plan_version",
}


@dataclass
class _SpanDraft:
    span_id: str
    kind: str
    node: str
    label: str
    agent_role: str
    status: str
    attempt: int
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int
    payload: dict[str, Any] = field(default_factory=dict)
    usages: list[LLMUsage] = field(default_factory=list)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _duration_ms(start: datetime | None, end: datetime | None) -> int:
    if not start or not end:
        return 0
    return max(0, int((_utc(end) - _utc(start)).total_seconds() * 1000))


def _percentile(values: list[int], quantile: float = 0.95) -> int:
    if not values:
        return 0
    ordered = sorted(max(0, value) for value in values)
    return ordered[max(0, math.ceil(len(ordered) * quantile) - 1)]


def _payload(event: WorkflowEvent) -> dict[str, Any]:
    try:
        value = json.loads(event.payload_json or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _public_payload(event: WorkflowEvent) -> dict[str, Any]:
    return {
        key: value
        for key, value in _payload(event).items()
        if key in PUBLIC_EVENT_PAYLOAD_FIELDS
    }


def _status_value(value: WorkflowStatus | str) -> str:
    return value.value if isinstance(value, WorkflowStatus) else str(value)


def _project_accessible(project_id: int, user: User, db: Session) -> bool:
    project = db.get(Project, project_id)
    if not project:
        return False
    if user.role == UserRole.admin or project.owner_id == user.id:
        return True
    return db.scalar(
        select(ProjectMember.id).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user.id,
        )
    ) is not None


def _ensure_project_filter(project_id: int | None, user: User, db: Session) -> None:
    if project_id is not None and not _project_accessible(project_id, user, db):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")


def _scope_conditions(
    current_user: User,
    start_at: datetime,
    *,
    project_id: int | None,
    workflow_status: WorkflowStatus | None,
) -> list[Any]:
    conditions: list[Any] = [WorkflowRun.created_at >= start_at]
    if current_user.role != UserRole.admin:
        conditions.append(WorkflowRun.user_id == current_user.id)
    if project_id is not None:
        conditions.append(WorkflowRun.project_id == project_id)
    if workflow_status is not None:
        conditions.append(WorkflowRun.status == workflow_status)
    return conditions


def _accessible_project_ids(user: User):
    return (
        select(Project.id)
        .outerjoin(
            ProjectMember,
            (ProjectMember.project_id == Project.id) & (ProjectMember.user_id == user.id),
        )
        .where(or_(Project.owner_id == user.id, ProjectMember.user_id == user.id))
    )


def _span_terminal_status(workflow: WorkflowRun) -> str:
    if workflow.status in FAILED_STATUSES:
        return "FAILED"
    if workflow.status == WorkflowStatus.cancelled:
        return "CANCELLED"
    if workflow.status == WorkflowStatus.paused:
        return "PAUSED"
    if workflow.status in ACTIVE_STATUSES:
        return "ACTIVE"
    return "INCOMPLETE"


def _agent_role_value(agent: Agent | None) -> str:
    if not agent:
        return ""
    return agent.role.value if hasattr(agent.role, "value") else str(agent.role)


def _pair_event_spans(
    workflow: WorkflowRun,
    events: list[WorkflowEvent],
    *,
    now: datetime,
) -> list[_SpanDraft]:
    spans: list[_SpanDraft] = []
    node_attempts: dict[str, int] = defaultdict(int)
    open_nodes: dict[str, deque[tuple[WorkflowEvent, int]]] = defaultdict(deque)
    open_branches: dict[tuple[str, int], deque[WorkflowEvent]] = defaultdict(deque)
    open_pause: WorkflowEvent | None = None

    if workflow.created_at:
        queue_end = workflow.started_at
        queue_status = "COMPLETED" if queue_end else _span_terminal_status(workflow)
        if not queue_end and workflow.finished_at:
            queue_end = workflow.finished_at
        spans.append(
            _SpanDraft(
                span_id=f"queue-{workflow.id}",
                kind="queue",
                node="queue",
                label="队列等待",
                agent_role="",
                status=queue_status,
                attempt=1,
                started_at=workflow.created_at,
                finished_at=queue_end,
                duration_ms=_duration_ms(workflow.created_at, queue_end or now),
            )
        )

    for event in events:
        payload = _payload(event)
        if event.event_type == "NODE_STARTED":
            node_attempts[event.node] += 1
            open_nodes[event.node].append((event, node_attempts[event.node]))
        elif event.event_type == "NODE_COMPLETED" and open_nodes[event.node]:
            started, attempt = open_nodes[event.node].popleft()
            spans.append(
                _SpanDraft(
                    span_id=f"node-{started.id}",
                    kind="node",
                    node=event.node,
                    label=NODE_LABELS.get(event.node, event.node or "工作流节点"),
                    agent_role=NODE_AGENT_ROLES.get(event.node, ""),
                    status="COMPLETED",
                    attempt=attempt,
                    started_at=started.created_at,
                    finished_at=event.created_at,
                    duration_ms=_duration_ms(started.created_at, event.created_at),
                    payload=_public_payload(event),
                )
            )
        elif event.event_type == "BRANCH_STARTED":
            role = str(payload.get("role") or "specialist")
            revision_round = int(payload.get("revision_round") or 0)
            open_branches[(role, revision_round)].append(event)
        elif event.event_type == "BRANCH_COMPLETED":
            role = str(payload.get("role") or "specialist")
            revision_round = int(payload.get("revision_round") or 0)
            key = (role, revision_round)
            if open_branches[key]:
                started = open_branches[key].popleft()
                spans.append(
                    _SpanDraft(
                        span_id=f"branch-{started.id}",
                        kind="branch",
                        node="specialists",
                        label=ROLE_LABELS.get(role, role),
                        agent_role=role,
                        status="COMPLETED",
                        attempt=revision_round + 1,
                        started_at=started.created_at,
                        finished_at=event.created_at,
                        duration_ms=_duration_ms(started.created_at, event.created_at),
                        payload=_public_payload(event),
                    )
                )

        if event.event_type == "PAUSED":
            open_pause = event
        elif open_pause and event.event_type in {
            "QUEUED",
            "CONTINUED",
            "STARTED",
            "CANCEL_REQUESTED",
        }:
            pause_payload = _public_payload(open_pause)
            spans.append(
                _SpanDraft(
                    span_id=f"wait-{open_pause.id}",
                    kind="wait",
                    node=open_pause.node,
                    label="人工干预等待" if pause_payload.get("approval_gate") == "operator" else "人工确认等待",
                    agent_role="",
                    status="COMPLETED",
                    attempt=1,
                    started_at=open_pause.created_at,
                    finished_at=event.created_at,
                    duration_ms=_duration_ms(open_pause.created_at, event.created_at),
                    payload=pause_payload,
                )
            )
            open_pause = None

    open_end = workflow.finished_at or now
    open_status = _span_terminal_status(workflow)
    for node, started_events in open_nodes.items():
        while started_events:
            started, attempt = started_events.popleft()
            spans.append(
                _SpanDraft(
                    span_id=f"node-{started.id}",
                    kind="node",
                    node=node,
                    label=NODE_LABELS.get(node, node or "工作流节点"),
                    agent_role=NODE_AGENT_ROLES.get(node, ""),
                    status=open_status,
                    attempt=attempt,
                    started_at=started.created_at,
                    finished_at=workflow.finished_at,
                    duration_ms=_duration_ms(started.created_at, open_end),
                )
            )
    for (role, revision_round), started_events in open_branches.items():
        while started_events:
            started = started_events.popleft()
            spans.append(
                _SpanDraft(
                    span_id=f"branch-{started.id}",
                    kind="branch",
                    node="specialists",
                    label=ROLE_LABELS.get(role, role),
                    agent_role=role,
                    status=open_status,
                    attempt=revision_round + 1,
                    started_at=started.created_at,
                    finished_at=workflow.finished_at,
                    duration_ms=_duration_ms(started.created_at, open_end),
                    payload=_public_payload(started),
                )
            )
    if open_pause:
        pause_payload = _public_payload(open_pause)
        spans.append(
            _SpanDraft(
                span_id=f"wait-{open_pause.id}",
                kind="wait",
                node=open_pause.node,
                label="人工干预等待" if pause_payload.get("approval_gate") == "operator" else "人工确认等待",
                agent_role="",
                status="PAUSED" if workflow.status == WorkflowStatus.paused else open_status,
                attempt=1,
                started_at=open_pause.created_at,
                finished_at=workflow.finished_at,
                duration_ms=_duration_ms(open_pause.created_at, open_end),
                payload=pause_payload,
            )
        )
    return sorted(spans, key=lambda item: (_utc(item.started_at), item.kind != "node", item.span_id))


def _assign_usage_to_spans(
    spans: list[_SpanDraft],
    usages: list[LLMUsage],
    agents_by_id: dict[int, Agent],
    now: datetime,
) -> None:
    execution_spans = [span for span in spans if span.kind in {"branch", "node"}]
    for usage in usages:
        usage_at = _utc(usage.created_at)
        candidates = [
            span
            for span in execution_spans
            if _utc(span.started_at) <= usage_at <= _utc(span.finished_at or now) + timedelta(seconds=1)
        ]
        if not candidates:
            continue
        agent = agents_by_id.get(usage.agent_id) if usage.agent_id is not None else None
        agent_role = _agent_role_value(agent)
        candidates.sort(
            key=lambda span: (
                span.agent_role != agent_role if agent_role else True,
                span.kind != "branch",
                span.duration_ms,
                span.span_id,
            )
        )
        candidates[0].usages.append(usage)


def _span_out(span: _SpanDraft, agents_by_role: dict[str, Agent]) -> TraceSpanOut:
    agent = agents_by_role.get(span.agent_role)
    return TraceSpanOut(
        span_id=span.span_id,
        kind=span.kind,
        node=span.node,
        label=span.label,
        agent_role=span.agent_role,
        agent_name=agent.name if agent else ROLE_LABELS.get(span.agent_role, ""),
        status=span.status,
        attempt=span.attempt,
        started_at=span.started_at,
        finished_at=span.finished_at,
        duration_ms=span.duration_ms,
        llm_call_count=len(span.usages),
        total_tokens=sum(item.total_tokens for item in span.usages),
        total_cost_micros=sum(item.estimated_cost_micros for item in span.usages),
        model_latency_ms=sum(item.latency_ms for item in span.usages),
        payload=span.payload,
    )


def _usage_totals(usages: list[LLMUsage]) -> dict[str, int]:
    return {
        "calls": len(usages),
        "tokens": sum(item.total_tokens for item in usages),
        "cost": sum(item.estimated_cost_micros for item in usages),
        "agents": len({item.agent_id for item in usages if item.agent_id is not None}),
    }


def _run_out(
    workflow: WorkflowRun,
    *,
    project: Project | None,
    owner: User | None,
    usages: list[LLMUsage],
    event_count: int,
    now: datetime,
) -> TraceRunOut:
    totals = _usage_totals(usages)
    return TraceRunOut(
        workflow_id=workflow.id,
        project_id=workflow.project_id,
        parent_workflow_id=workflow.parent_workflow_id,
        retry_from_node=workflow.retry_from_node,
        retry_sequence=workflow.retry_sequence,
        intervention_count=workflow.intervention_count,
        project_name=project.name if project else f"Project #{workflow.project_id}",
        owner_id=workflow.user_id,
        owner_name=owner.name if owner else f"User #{workflow.user_id}",
        status=workflow.status,
        current_node=workflow.current_node,
        duration_ms=_duration_ms(workflow.created_at, workflow.finished_at or now),
        queue_ms=_duration_ms(workflow.created_at, workflow.started_at or workflow.finished_at),
        total_tokens=totals["tokens"],
        total_cost_micros=totals["cost"],
        llm_call_count=totals["calls"],
        agent_count=totals["agents"],
        event_count=event_count,
        error=workflow.error,
        created_at=workflow.created_at,
        started_at=workflow.started_at,
        finished_at=workflow.finished_at,
    )


def _agent_metrics(usages: list[LLMUsage], agents: dict[int, Agent]) -> list[TraceAgentMetricOut]:
    groups: dict[int | None, list[LLMUsage]] = defaultdict(list)
    for usage in usages:
        groups[usage.agent_id].append(usage)
    rows: list[TraceAgentMetricOut] = []
    for agent_id, items in groups.items():
        agent = agents.get(agent_id) if agent_id is not None else None
        role = _agent_role_value(agent)
        latencies = [item.latency_ms for item in items]
        rows.append(
            TraceAgentMetricOut(
                agent_id=agent_id,
                agent_name=agent.name if agent else "未归属 Agent",
                agent_role=role,
                providers=sorted({item.provider for item in items}),
                models=sorted({item.model for item in items}),
                workflow_count=len({item.workflow_id for item in items if item.workflow_id is not None}),
                call_count=len(items),
                input_tokens=sum(item.input_tokens for item in items),
                output_tokens=sum(item.output_tokens for item in items),
                total_tokens=sum(item.total_tokens for item in items),
                total_cost_micros=sum(item.estimated_cost_micros for item in items),
                average_latency_ms=round(sum(latencies) / len(latencies)) if latencies else 0,
                p95_latency_ms=_percentile(latencies),
                max_latency_ms=max(latencies, default=0),
            )
        )
    return sorted(rows, key=lambda item: (-item.total_cost_micros, -item.total_tokens, item.agent_name))


def _bottlenecks(
    workflows: list[WorkflowRun],
    events_by_workflow: dict[int, list[WorkflowEvent]],
    now: datetime,
) -> list[TraceBottleneckOut]:
    samples: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for workflow in workflows:
        spans = _pair_event_spans(workflow, events_by_workflow.get(workflow.id, []), now=now)
        for span in spans:
            if span.kind not in {"node", "branch"} or span.status != "COMPLETED":
                continue
            key = span.agent_role if span.kind == "branch" else span.node
            samples[(span.kind, key, span.label)].append(span.duration_ms)
    averages = {key: round(sum(values) / len(values)) for key, values in samples.items() if values}
    total_average = sum(averages.values()) or 1
    rows = [
        TraceBottleneckOut(
            key=f"{kind}:{node}",
            node=node,
            label=label,
            kind=kind,
            execution_count=len(samples[(kind, node, label)]),
            average_duration_ms=averages[(kind, node, label)],
            p95_duration_ms=_percentile(samples[(kind, node, label)]),
            max_duration_ms=max(samples[(kind, node, label)]),
            compute_share_percent=round(averages[(kind, node, label)] / total_average * 100, 1),
        )
        for kind, node, label in samples
    ]
    return sorted(rows, key=lambda item: (-item.p95_duration_ms, -item.average_duration_ms))[:10]


def _upper_anomaly_threshold(values: list[int], sensitivity: float, *, floor: int) -> int:
    center = float(median(values))
    deviation = float(median(abs(value - center) for value in values))
    scale = max(deviation * 1.4826, abs(center) * 0.05, float(floor))
    return round(center + sensitivity * scale)


def _trace_anomalies(
    workflows: list[WorkflowRun],
    *,
    costs: dict[int, int],
    projects: dict[int, Project],
    limit: int | None = ANOMALY_LIMIT,
) -> list[TraceAnomalyOut]:
    grouped: dict[int, list[WorkflowRun]] = defaultdict(list)
    for workflow in workflows:
        grouped[workflow.project_id].append(workflow)

    rows: list[TraceAnomalyOut] = []
    for project_id, project_runs in grouped.items():
        project_runs.sort(key=lambda item: (_utc(item.created_at), item.id), reverse=True)
        for index, workflow in enumerate(project_runs):
            duration = _duration_ms(workflow.created_at, workflow.finished_at)
            cost = costs.get(workflow.id, 0)
            signals: list[str] = []
            if workflow.status in FAILED_STATUSES:
                signals.append("运行失败")
            if duration > settings.observability_slo_p95_duration_ms:
                signals.append("耗时超过 SLO")
            if cost > settings.observability_slo_average_cost_micros:
                signals.append("单次成本超过 SLO")

            older_runs = project_runs[index + 1 :]
            if len(older_runs) >= settings.observability_slo_min_runs:
                duration_threshold = _upper_anomaly_threshold(
                    [_duration_ms(item.created_at, item.finished_at) for item in older_runs],
                    settings.observability_anomaly_sensitivity,
                    floor=10_000,
                )
                cost_threshold = _upper_anomaly_threshold(
                    [costs.get(item.id, 0) for item in older_runs],
                    settings.observability_anomaly_sensitivity,
                    floor=500,
                )
                if duration > duration_threshold:
                    signals.append("耗时偏离历史基线")
                if cost > cost_threshold:
                    signals.append("成本偏离历史基线")
            if not signals:
                continue
            rows.append(
                TraceAnomalyOut(
                    workflow_id=workflow.id,
                    project_id=project_id,
                    project_name=projects.get(project_id).name if projects.get(project_id) else f"Project #{project_id}",
                    status=workflow.status,
                    severity="CRITICAL" if workflow.status in FAILED_STATUSES else "WARNING",
                    signals=list(dict.fromkeys(signals)),
                    duration_ms=duration,
                    total_cost_micros=cost,
                    detected_at=workflow.finished_at or workflow.created_at,
                )
            )
    ordered = sorted(rows, key=lambda item: (_utc(item.detected_at), item.workflow_id), reverse=True)
    return ordered[:limit] if limit is not None else ordered


def _terminal_workflows(
    db: Session,
    current_user: User | None,
    *,
    days: int,
    project_id: int | None,
) -> list[WorkflowRun]:
    start_at = _utc_now() - timedelta(days=days)
    if current_user is not None:
        _ensure_project_filter(project_id, current_user, db)
        conditions = _scope_conditions(
            current_user,
            start_at,
            project_id=project_id,
            workflow_status=None,
        )
        if current_user.role != UserRole.admin:
            conditions.append(WorkflowRun.project_id.in_(_accessible_project_ids(current_user)))
    else:
        conditions = [WorkflowRun.created_at >= start_at]
        if project_id is not None:
            conditions.append(WorkflowRun.project_id == project_id)
    return list(
        db.scalars(
            select(WorkflowRun)
            .where(
                *conditions,
                WorkflowRun.finished_at.is_not(None),
                WorkflowRun.status.in_(HEALTH_STATUSES),
            )
            .order_by(WorkflowRun.created_at.desc(), WorkflowRun.id.desc())
            .limit(RUN_ANALYSIS_LIMIT)
        )
    )


def _workflow_costs(db: Session, workflow_ids: list[int]) -> dict[int, int]:
    if not workflow_ids:
        return {}
    return {
        workflow_id: int(cost)
        for workflow_id, cost in db.execute(
            select(
                LLMUsage.workflow_id,
                func.coalesce(func.sum(LLMUsage.estimated_cost_micros), 0),
            )
            .where(LLMUsage.workflow_id.in_(workflow_ids))
            .group_by(LLMUsage.workflow_id)
        ).all()
        if workflow_id is not None
    }


def _project_map(db: Session, project_ids: set[int]) -> dict[int, Project]:
    if not project_ids:
        return {}
    return {
        item.id: item
        for item in db.scalars(select(Project).where(Project.id.in_(project_ids)))
    }


def _alert_notifications(
    db: Session,
    *,
    alert: TraceAlert,
    workflow: WorkflowRun,
    project: Project | None,
    signals: list[str],
    now: datetime,
) -> None:
    user = db.get(User, workflow.user_id)
    project_name = project.name if project else f"Project #{workflow.project_id}"
    severity_label = "严重" if alert.severity == "CRITICAL" else "警告"
    title = f"[{severity_label}] 工作流 #{workflow.id} 运行告警"
    content = f"项目：{project_name}\n运行：#{workflow.id}\n信号：{'、'.join(signals)}"
    db.add(
        Notification(
            project_id=workflow.project_id,
            user_id=workflow.user_id,
            recipient_user_id=workflow.user_id,
            recipient_email=user.email if user else "",
            title=title,
            content=content,
            channel="in_app",
            status="SENT",
            sent_at=now,
        )
    )
    if settings.observability_alert_email_enabled and user and user.email:
        db.add(
            Notification(
                project_id=workflow.project_id,
                user_id=workflow.user_id,
                recipient_user_id=workflow.user_id,
                recipient_email=user.email,
                title=title,
                content=content,
                channel="email",
                schedule_at=now.isoformat(),
                scheduled_for=now,
                status="SCHEDULED",
            )
        )


def sync_trace_alerts(
    db: Session,
    current_user: User | None,
    *,
    days: int,
    project_id: int | None,
) -> int:
    now = _utc_now()
    workflows = _terminal_workflows(
        db,
        current_user,
        days=days,
        project_id=project_id,
    )
    workflow_ids = [item.id for item in workflows]
    costs = _workflow_costs(db, workflow_ids)
    projects = _project_map(db, {item.project_id for item in workflows})
    anomalies = _trace_anomalies(workflows, costs=costs, projects=projects, limit=None)
    existing_ids = set(
        db.scalars(select(TraceAlert.workflow_id).where(TraceAlert.workflow_id.in_([item.workflow_id for item in anomalies])))
    ) if anomalies else set()
    workflows_by_id = {item.id: item for item in workflows}
    created_count = 0
    pending_anomalies = [item for item in anomalies if item.workflow_id not in existing_ids][:ALERT_SYNC_CREATE_LIMIT]
    for anomaly in pending_anomalies:
        workflow = workflows_by_id[anomaly.workflow_id]
        try:
            with db.begin_nested():
                alert = TraceAlert(
                    workflow_id=workflow.id,
                    project_id=workflow.project_id,
                    user_id=workflow.user_id,
                    severity=anomaly.severity,
                    status=TraceAlertStatus.open,
                    signals_json=json.dumps(anomaly.signals, ensure_ascii=False),
                    duration_ms=anomaly.duration_ms,
                    total_cost_micros=anomaly.total_cost_micros,
                    detected_at=anomaly.detected_at,
                    last_seen_at=now,
                )
                db.add(alert)
                db.flush()
                _alert_notifications(
                    db,
                    alert=alert,
                    workflow=workflow,
                    project=projects.get(workflow.project_id),
                    signals=anomaly.signals,
                    now=now,
                )
                record_audit(
                    db,
                    "trace_alert.created",
                    project_id=workflow.project_id,
                    resource_type="trace_alert",
                    resource_id=alert.id,
                    details={"workflow_id": workflow.id, "severity": alert.severity},
                )
            created_count += 1
        except IntegrityError:
            continue
    return created_count


def _alert_accessible(alert: TraceAlert, user: User, db: Session) -> bool:
    if user.role == UserRole.admin:
        return True
    return alert.user_id == user.id and _project_accessible(alert.project_id, user, db)


def _alert_signals(alert: TraceAlert) -> list[str]:
    try:
        value = json.loads(alert.signals_json or "[]")
    except (json.JSONDecodeError, TypeError):
        return []
    return [str(item) for item in value] if isinstance(value, list) else []


def _alert_out(alert: TraceAlert, projects: dict[int, Project]) -> TraceAlertOut:
    project = projects.get(alert.project_id)
    return TraceAlertOut(
        id=alert.id,
        workflow_id=alert.workflow_id,
        project_id=alert.project_id,
        project_name=project.name if project else f"Project #{alert.project_id}",
        severity=alert.severity,
        status=alert.status,
        signals=_alert_signals(alert),
        duration_ms=alert.duration_ms,
        total_cost_micros=alert.total_cost_micros,
        detected_at=alert.detected_at,
        acknowledged_by_user_id=alert.acknowledged_by_user_id,
        acknowledged_at=alert.acknowledged_at,
        resolved_by_user_id=alert.resolved_by_user_id,
        resolved_at=alert.resolved_at,
        resolution_note=alert.resolution_note,
        created_at=alert.created_at,
        updated_at=alert.updated_at,
    )


def get_trace_alerts(
    db: Session,
    current_user: User,
    *,
    days: int,
    project_id: int | None,
    alert_status: TraceAlertStatus | None,
    severity: str | None,
) -> TraceAlertCollectionOut:
    _ensure_project_filter(project_id, current_user, db)
    start_at = _utc_now() - timedelta(days=days)
    base_conditions: list[Any] = [TraceAlert.detected_at >= start_at]
    if current_user.role != UserRole.admin:
        base_conditions.append(TraceAlert.user_id == current_user.id)
        base_conditions.append(TraceAlert.project_id.in_(_accessible_project_ids(current_user)))
    if project_id is not None:
        base_conditions.append(TraceAlert.project_id == project_id)
    status_counts = {
        item.value if isinstance(item, TraceAlertStatus) else str(item): count
        for item, count in db.execute(
            select(TraceAlert.status, func.count(TraceAlert.id))
            .where(*base_conditions)
            .group_by(TraceAlert.status)
        )
    }
    critical = int(
        db.scalar(
            select(func.count(TraceAlert.id)).where(*base_conditions, TraceAlert.severity == "CRITICAL")
        )
        or 0
    )
    item_conditions = list(base_conditions)
    if alert_status is not None:
        item_conditions.append(TraceAlert.status == alert_status)
    if severity is not None:
        item_conditions.append(TraceAlert.severity == severity)
    alerts = list(
        db.scalars(
            select(TraceAlert)
            .where(*item_conditions)
            .order_by(TraceAlert.status.desc(), TraceAlert.detected_at.desc(), TraceAlert.id.desc())
            .limit(ALERT_LIST_LIMIT)
        )
    )
    projects = _project_map(db, {item.project_id for item in alerts})
    return TraceAlertCollectionOut(
        summary=TraceAlertSummaryOut(
            total=sum(status_counts.values()),
            open=status_counts.get(TraceAlertStatus.open.value, 0),
            acknowledged=status_counts.get(TraceAlertStatus.acknowledged.value, 0),
            resolved=status_counts.get(TraceAlertStatus.resolved.value, 0),
            critical=critical,
        ),
        items=[_alert_out(item, projects) for item in alerts],
    )


def transition_trace_alerts(
    db: Session,
    current_user: User,
    *,
    alert_ids: list[int],
    action: str,
    resolution_note: str,
) -> list[TraceAlertOut]:
    normalized_action = action.strip().upper()
    if normalized_action not in {"ACKNOWLEDGE", "RESOLVE"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid alert action")
    note = resolution_note.strip()
    if normalized_action == "RESOLVE" and not note:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Resolution note is required")
    unique_ids = list(dict.fromkeys(alert_ids))
    alerts = list(
        db.scalars(
            select(TraceAlert)
            .where(TraceAlert.id.in_(unique_ids))
            .with_for_update()
        )
    )
    if len(alerts) != len(unique_ids) or any(not _alert_accessible(item, current_user, db) for item in alerts):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trace alert not found")
    alerts_by_id = {item.id: item for item in alerts}
    ordered = [alerts_by_id[item] for item in unique_ids]
    now = _utc_now()
    for alert in ordered:
        changed = False
        if normalized_action == "ACKNOWLEDGE":
            if alert.status == TraceAlertStatus.resolved:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Resolved alerts cannot be acknowledged")
            if alert.status == TraceAlertStatus.open:
                alert.status = TraceAlertStatus.acknowledged
                alert.acknowledged_by_user_id = current_user.id
                alert.acknowledged_at = now
                changed = True
        elif alert.status != TraceAlertStatus.resolved:
            alert.status = TraceAlertStatus.resolved
            alert.resolved_by_user_id = current_user.id
            alert.resolved_at = now
            alert.resolution_note = note
            changed = True
        if changed:
            record_audit(
                db,
                f"trace_alert.{normalized_action.lower()}",
                current_user.id,
                alert.project_id,
                "trace_alert",
                alert.id,
                {"workflow_id": alert.workflow_id},
            )
    db.flush()
    projects = _project_map(db, {item.project_id for item in ordered})
    return [_alert_out(item, projects) for item in ordered]


def get_trace_health(
    db: Session,
    current_user: User,
    *,
    days: int,
    project_id: int | None,
) -> TraceHealthOut:
    now = _utc_now()
    start_at = now - timedelta(days=days)
    _ensure_project_filter(project_id, current_user, db)
    conditions = _scope_conditions(
        current_user,
        start_at,
        project_id=project_id,
        workflow_status=None,
    )
    workflows = list(
        db.scalars(
            select(WorkflowRun)
            .where(
                *conditions,
                WorkflowRun.finished_at.is_not(None),
                WorkflowRun.status.in_(HEALTH_STATUSES),
            )
            .order_by(WorkflowRun.created_at.desc(), WorkflowRun.id.desc())
            .limit(RUN_ANALYSIS_LIMIT + 1)
        )
    )
    analysis_truncated = len(workflows) > RUN_ANALYSIS_LIMIT
    workflows = workflows[:RUN_ANALYSIS_LIMIT]
    workflow_ids = [item.id for item in workflows]
    costs = {
        workflow_id: int(cost)
        for workflow_id, cost in db.execute(
            select(
                LLMUsage.workflow_id,
                func.coalesce(func.sum(LLMUsage.estimated_cost_micros), 0),
            )
            .where(LLMUsage.workflow_id.in_(workflow_ids))
            .group_by(LLMUsage.workflow_id)
        ).all()
        if workflow_id is not None
    } if workflow_ids else {}
    project_ids = {item.project_id for item in workflows}
    projects = {
        item.id: item
        for item in db.scalars(select(Project).where(Project.id.in_(project_ids)))
    } if project_ids else {}

    sample_count = len(workflows)
    completed_count = sum(item.status == WorkflowStatus.completed for item in workflows)
    failed_count = sample_count - completed_count
    durations = [_duration_ms(item.created_at, item.finished_at) for item in workflows]
    success_rate = round(completed_count / sample_count * 100, 1) if sample_count else 0.0
    p95_duration = _percentile(durations)
    average_cost = round(sum(costs.get(item.id, 0) for item in workflows) / sample_count) if sample_count else 0
    metrics = [
        TraceSLOMetricOut(
            key="success_rate",
            label="运行成功率",
            unit="percent",
            target=settings.observability_slo_success_rate,
            actual=success_rate,
            compliant=success_rate >= settings.observability_slo_success_rate,
        ),
        TraceSLOMetricOut(
            key="p95_duration_ms",
            label="P95 端到端耗时",
            unit="duration",
            target=settings.observability_slo_p95_duration_ms,
            actual=p95_duration,
            compliant=p95_duration <= settings.observability_slo_p95_duration_ms,
        ),
        TraceSLOMetricOut(
            key="average_cost_micros",
            label="单次平均成本",
            unit="cost",
            target=settings.observability_slo_average_cost_micros,
            actual=average_cost,
            compliant=average_cost <= settings.observability_slo_average_cost_micros,
        ),
    ]
    breached_count = sum(not item.compliant for item in metrics)
    if sample_count < settings.observability_slo_min_runs:
        health_status = "INSUFFICIENT_DATA"
    elif not metrics[0].compliant or breached_count >= 2:
        health_status = "BREACHED"
    elif breached_count:
        health_status = "AT_RISK"
    else:
        health_status = "HEALTHY"

    allowed_failures = round(sample_count * (100 - settings.observability_slo_success_rate) / 100, 2)
    if allowed_failures > 0:
        remaining_budget = round(max(0.0, (allowed_failures - failed_count) / allowed_failures * 100), 1)
    else:
        remaining_budget = 100.0 if failed_count == 0 else 0.0
    return TraceHealthOut(
        window=TraceWindowOut(
            start_at=start_at,
            end_at=now,
            days=days,
            analysis_truncated=analysis_truncated,
        ),
        targets=TraceSLOTargetsOut(
            success_rate_percent=settings.observability_slo_success_rate,
            p95_duration_ms=settings.observability_slo_p95_duration_ms,
            average_cost_micros=settings.observability_slo_average_cost_micros,
            minimum_sample_runs=settings.observability_slo_min_runs,
            anomaly_sensitivity=settings.observability_anomaly_sensitivity,
        ),
        summary=TraceHealthSummaryOut(
            status=health_status,
            sample_count=sample_count,
            completed_count=completed_count,
            failed_count=failed_count,
            compliant_metric_count=len(metrics) - breached_count,
            breached_metric_count=breached_count,
            error_budget_allowed_failures=allowed_failures,
            error_budget_consumed_failures=failed_count,
            error_budget_remaining_percent=remaining_budget,
        ),
        metrics=metrics,
        anomalies=_trace_anomalies(workflows, costs=costs, projects=projects),
    )


def get_trace_overview(
    db: Session,
    current_user: User,
    *,
    days: int,
    project_id: int | None,
    workflow_status: WorkflowStatus | None,
) -> TraceOverviewOut:
    now = _utc_now()
    start_at = now - timedelta(days=days)
    _ensure_project_filter(project_id, current_user, db)
    conditions = _scope_conditions(
        current_user,
        start_at,
        project_id=project_id,
        workflow_status=workflow_status,
    )
    unfiltered_conditions = _scope_conditions(
        current_user,
        start_at,
        project_id=None,
        workflow_status=None,
    )

    status_rows = db.execute(
        select(WorkflowRun.status, func.count(WorkflowRun.id))
        .where(*conditions)
        .group_by(WorkflowRun.status)
    ).all()
    status_counts = {_status_value(run_status): count for run_status, count in status_rows}
    total_runs = sum(status_counts.values())

    sampled_runs = list(
        db.scalars(
            select(WorkflowRun)
            .where(*conditions)
            .order_by(WorkflowRun.created_at.desc(), WorkflowRun.id.desc())
            .limit(RUN_ANALYSIS_LIMIT + 1)
        )
    )
    run_sample_truncated = len(sampled_runs) > RUN_ANALYSIS_LIMIT
    sampled_runs = sampled_runs[:RUN_ANALYSIS_LIMIT]
    recent_runs = sampled_runs[:RECENT_RUN_LIMIT]

    scope_ids = select(WorkflowRun.id).where(*conditions)
    usage_total = db.execute(
        select(
            func.count(LLMUsage.id),
            func.coalesce(func.sum(LLMUsage.total_tokens), 0),
            func.coalesce(func.sum(LLMUsage.estimated_cost_micros), 0),
        ).where(LLMUsage.workflow_id.in_(scope_ids))
    ).one()

    usage_sample = list(
        db.scalars(
            select(LLMUsage)
            .where(LLMUsage.workflow_id.in_(scope_ids))
            .order_by(LLMUsage.created_at.desc(), LLMUsage.id.desc())
            .limit(USAGE_ANALYSIS_LIMIT + 1)
        )
    )
    usage_sample_truncated = len(usage_sample) > USAGE_ANALYSIS_LIMIT
    usage_sample = usage_sample[:USAGE_ANALYSIS_LIMIT]
    usage_by_workflow: dict[int, list[LLMUsage]] = defaultdict(list)
    for usage in usage_sample:
        if usage.workflow_id is not None:
            usage_by_workflow[usage.workflow_id].append(usage)

    agent_ids = {item.agent_id for item in usage_sample if item.agent_id is not None}
    agents = {
        item.id: item
        for item in db.scalars(select(Agent).where(Agent.id.in_(agent_ids)))
    } if agent_ids else {}

    recent_ids = [workflow.id for workflow in recent_runs]
    event_counts = dict(
        db.execute(
            select(WorkflowEvent.workflow_id, func.count(WorkflowEvent.id))
            .where(WorkflowEvent.workflow_id.in_(recent_ids))
            .group_by(WorkflowEvent.workflow_id)
        ).all()
    ) if recent_ids else {}
    project_ids = {workflow.project_id for workflow in recent_runs}
    owner_ids = {workflow.user_id for workflow in recent_runs}
    projects = {
        item.id: item
        for item in db.scalars(select(Project).where(Project.id.in_(project_ids)))
    } if project_ids else {}
    owners = {
        item.id: item
        for item in db.scalars(select(User).where(User.id.in_(owner_ids)))
    } if owner_ids else {}

    option_rows = db.execute(
        select(Project.id, Project.name)
        .join(WorkflowRun, WorkflowRun.project_id == Project.id)
        .where(*unfiltered_conditions)
        .distinct()
        .order_by(Project.name, Project.id)
    ).all()

    trend_by_bucket: dict[str, dict[str, int]] = {}
    first_day = start_at.date()
    for offset in range((now.date() - first_day).days + 1):
        bucket = (first_day + timedelta(days=offset)).isoformat()
        trend_by_bucket[bucket] = {
            "runs": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
            "tokens": 0,
            "cost": 0,
        }
    for bucket, run_status, count in db.execute(
        select(func.date(WorkflowRun.created_at), WorkflowRun.status, func.count(WorkflowRun.id))
        .where(*conditions)
        .group_by(func.date(WorkflowRun.created_at), WorkflowRun.status)
    ):
        key = str(bucket)
        if key not in trend_by_bucket:
            continue
        trend_by_bucket[key]["runs"] += count
        status_value = _status_value(run_status)
        if status_value == WorkflowStatus.completed.value:
            trend_by_bucket[key]["completed"] += count
        elif status_value in {item.value for item in FAILED_STATUSES}:
            trend_by_bucket[key]["failed"] += count
        elif status_value == WorkflowStatus.cancelled.value:
            trend_by_bucket[key]["cancelled"] += count
    for bucket, tokens, cost in db.execute(
        select(
            func.date(LLMUsage.created_at),
            func.coalesce(func.sum(LLMUsage.total_tokens), 0),
            func.coalesce(func.sum(LLMUsage.estimated_cost_micros), 0),
        )
        .where(LLMUsage.workflow_id.in_(scope_ids))
        .group_by(func.date(LLMUsage.created_at))
    ):
        key = str(bucket)
        if key in trend_by_bucket:
            trend_by_bucket[key]["tokens"] = int(tokens)
            trend_by_bucket[key]["cost"] = int(cost)

    duration_samples = [
        _duration_ms(workflow.created_at, workflow.finished_at)
        for workflow in sampled_runs
        if workflow.created_at and workflow.finished_at
    ]
    completed_runs = status_counts.get(WorkflowStatus.completed.value, 0)
    failed_runs = sum(status_counts.get(item.value, 0) for item in FAILED_STATUSES)
    decided_runs = completed_runs + failed_runs

    bottleneck_runs = sampled_runs[:BOTTLENECK_RUN_LIMIT]
    bottleneck_ids = [workflow.id for workflow in bottleneck_runs]
    events_by_workflow: dict[int, list[WorkflowEvent]] = defaultdict(list)
    if bottleneck_ids:
        for event in db.scalars(
            select(WorkflowEvent)
            .where(WorkflowEvent.workflow_id.in_(bottleneck_ids))
            .order_by(WorkflowEvent.workflow_id, WorkflowEvent.id)
        ):
            events_by_workflow[event.workflow_id].append(event)

    return TraceOverviewOut(
        window=TraceWindowOut(
            start_at=start_at,
            end_at=now,
            days=days,
            analysis_truncated=run_sample_truncated or usage_sample_truncated,
        ),
        metrics=TraceMetricSummaryOut(
            total_runs=total_runs,
            active_runs=sum(status_counts.get(item.value, 0) for item in ACTIVE_STATUSES),
            completed_runs=completed_runs,
            failed_runs=failed_runs,
            cancelled_runs=status_counts.get(WorkflowStatus.cancelled.value, 0),
            success_rate=round(completed_runs / decided_runs * 100, 1) if decided_runs else 0.0,
            average_duration_ms=round(sum(duration_samples) / len(duration_samples)) if duration_samples else 0,
            p95_duration_ms=_percentile(duration_samples),
            total_tokens=int(usage_total[1]),
            total_cost_micros=int(usage_total[2]),
            total_llm_calls=int(usage_total[0]),
        ),
        status_counts=status_counts,
        trend=[
            TraceTrendPointOut(
                bucket=bucket,
                runs=values["runs"],
                completed=values["completed"],
                failed=values["failed"],
                cancelled=values["cancelled"],
                total_tokens=values["tokens"],
                total_cost_micros=values["cost"],
            )
            for bucket, values in sorted(trend_by_bucket.items())
        ],
        projects=[TraceProjectOptionOut(project_id=item[0], project_name=item[1]) for item in option_rows],
        agents=_agent_metrics(usage_sample, agents),
        bottlenecks=_bottlenecks(bottleneck_runs, events_by_workflow, now),
        recent_runs=[
            _run_out(
                workflow,
                project=projects.get(workflow.project_id),
                owner=owners.get(workflow.user_id),
                usages=usage_by_workflow.get(workflow.id, []),
                event_count=event_counts.get(workflow.id, 0),
                now=now,
            )
            for workflow in recent_runs
        ],
    )


def get_trace_detail(db: Session, current_user: User, workflow_id: int) -> TraceDetailOut:
    workflow = db.get(WorkflowRun, workflow_id)
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow trace not found")
    if current_user.role != UserRole.admin:
        if workflow.user_id != current_user.id or not _project_accessible(workflow.project_id, current_user, db):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow trace not found")

    now = _utc_now()
    events = list(
        db.scalars(
            select(WorkflowEvent)
            .where(WorkflowEvent.workflow_id == workflow.id)
            .order_by(WorkflowEvent.id)
        )
    )
    usages = list(
        db.scalars(
            select(LLMUsage)
            .where(LLMUsage.workflow_id == workflow.id)
            .order_by(LLMUsage.created_at, LLMUsage.id)
        )
    )
    agent_ids = {item.agent_id for item in usages if item.agent_id is not None}
    agents_by_id = {
        item.id: item
        for item in db.scalars(select(Agent).where(Agent.id.in_(agent_ids)))
    } if agent_ids else {}
    agents_by_role = {_agent_role_value(agent): agent for agent in agents_by_id.values()}

    span_drafts = _pair_event_spans(workflow, events, now=now)
    _assign_usage_to_spans(span_drafts, usages, agents_by_id, now)
    spans = [_span_out(span, agents_by_role) for span in span_drafts]
    node_spans = [span for span in spans if span.kind == "node"]
    wait_spans = [span for span in spans if span.kind == "wait"]
    queue_span = next((span for span in spans if span.kind == "queue"), None)
    critical_span = max(node_spans, key=lambda item: item.duration_ms, default=None)
    totals = _usage_totals(usages)
    total_duration = _duration_ms(workflow.created_at, workflow.finished_at or now)
    queue_ms = queue_span.duration_ms if queue_span else 0
    compute_ms = sum(span.duration_ms for span in node_spans)
    human_wait_ms = sum(span.duration_ms for span in wait_spans)

    project = db.get(Project, workflow.project_id)
    owner = db.get(User, workflow.user_id)
    return TraceDetailOut(
        run=_run_out(
            workflow,
            project=project,
            owner=owner,
            usages=usages,
            event_count=len(events),
            now=now,
        ),
        metrics=TraceDetailMetricsOut(
            total_duration_ms=total_duration,
            queue_ms=queue_ms,
            active_compute_ms=compute_ms,
            human_wait_ms=human_wait_ms,
            coordination_ms=max(0, total_duration - queue_ms - compute_ms - human_wait_ms),
            total_tokens=totals["tokens"],
            total_cost_micros=totals["cost"],
            total_llm_calls=totals["calls"],
            critical_span_id=critical_span.span_id if critical_span else None,
        ),
        spans=spans,
        model_calls=[
            TraceModelCallOut(
                id=usage.id,
                agent_id=usage.agent_id,
                agent_name=agents_by_id[usage.agent_id].name if usage.agent_id in agents_by_id else "未归属 Agent",
                agent_role=_agent_role_value(agents_by_id.get(usage.agent_id)) if usage.agent_id else "",
                operation=usage.operation,
                provider=usage.provider,
                model=usage.model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                total_tokens=usage.total_tokens,
                estimated_cost_micros=usage.estimated_cost_micros,
                latency_ms=usage.latency_ms,
                usage_source=usage.usage_source,
                created_at=usage.created_at,
            )
            for usage in usages
        ],
        events=[
            TraceEventDetailOut(
                id=event.id,
                node=event.node,
                event_type=event.event_type,
                message=event.message,
                payload=_public_payload(event),
                created_at=event.created_at,
            )
            for event in events
        ],
    )


def _comparison_direction(
    baseline: int,
    candidate: int,
    *,
    lower_is_better: bool,
    minimum_delta: int,
) -> tuple[int, float | None, str]:
    delta = candidate - baseline
    percent = round(delta / abs(baseline) * 100, 1) if baseline else None
    if abs(delta) < minimum_delta or (percent is not None and abs(percent) < 5.0):
        return delta, percent, "UNCHANGED"
    if not lower_is_better:
        return delta, percent, "CHANGED"
    return delta, percent, "IMPROVED" if delta < 0 else "REGRESSED"


def _comparison_metric(
    key: str,
    label: str,
    unit: str,
    baseline: int,
    candidate: int,
    *,
    lower_is_better: bool = True,
    minimum_delta: int = 1,
) -> TraceComparisonMetricOut:
    delta, percent, direction = _comparison_direction(
        baseline,
        candidate,
        lower_is_better=lower_is_better,
        minimum_delta=minimum_delta,
    )
    return TraceComparisonMetricOut(
        key=key,
        label=label,
        unit=unit,
        baseline_value=baseline,
        candidate_value=candidate,
        delta=delta,
        delta_percent=percent,
        direction=direction,
        lower_is_better=lower_is_better,
    )


def _outcome_direction(baseline: WorkflowStatus, candidate: WorkflowStatus) -> str:
    if baseline == candidate:
        return "UNCHANGED"
    if baseline != WorkflowStatus.completed and candidate == WorkflowStatus.completed:
        return "IMPROVED"
    if baseline == WorkflowStatus.completed and candidate != WorkflowStatus.completed:
        return "REGRESSED"
    return "CHANGED"


def _comparison_verdict(outcome: str, metrics: list[TraceComparisonMetricOut]) -> tuple[str, int, int]:
    primary = [item for item in metrics if item.key in {"total_duration_ms", "total_tokens", "total_cost_micros"}]
    regressions = sum(item.direction == "REGRESSED" for item in primary) + (outcome == "REGRESSED")
    improvements = sum(item.direction == "IMPROVED" for item in primary) + (outcome == "IMPROVED")
    if regressions and improvements:
        verdict = "MIXED"
    elif regressions:
        verdict = "REGRESSED"
    elif improvements:
        verdict = "IMPROVED"
    else:
        verdict = "UNCHANGED"
    return verdict, regressions, improvements


def _comparison_agents(
    baseline: TraceDetailOut,
    candidate: TraceDetailOut,
) -> list[TraceComparisonAgentOut]:
    grouped: dict[str, dict[str, list[TraceModelCallOut]]] = defaultdict(lambda: {"baseline": [], "candidate": []})
    for side, detail in (("baseline", baseline), ("candidate", candidate)):
        for call in detail.model_calls:
            key = call.agent_role or f"agent:{call.agent_id or 'unassigned'}"
            grouped[key][side].append(call)

    rows: list[TraceComparisonAgentOut] = []
    for key, sides in grouped.items():
        baseline_calls = sides["baseline"]
        candidate_calls = sides["candidate"]
        representative = (candidate_calls or baseline_calls)[0]
        baseline_latency = round(sum(item.latency_ms for item in baseline_calls) / len(baseline_calls)) if baseline_calls else 0
        candidate_latency = round(sum(item.latency_ms for item in candidate_calls) / len(candidate_calls)) if candidate_calls else 0
        latency_delta, _, latency_direction = _comparison_direction(
            baseline_latency,
            candidate_latency,
            lower_is_better=True,
            minimum_delta=100,
        )
        baseline_models = sorted({item.model for item in baseline_calls})
        candidate_models = sorted({item.model for item in candidate_calls})
        baseline_providers = sorted({item.provider for item in baseline_calls})
        candidate_providers = sorted({item.provider for item in candidate_calls})
        baseline_tokens = sum(item.total_tokens for item in baseline_calls)
        candidate_tokens = sum(item.total_tokens for item in candidate_calls)
        baseline_cost = sum(item.estimated_cost_micros for item in baseline_calls)
        candidate_cost = sum(item.estimated_cost_micros for item in candidate_calls)
        if not baseline_calls:
            change_type = "ADDED"
        elif not candidate_calls:
            change_type = "REMOVED"
        elif (
            baseline_models != candidate_models
            or baseline_providers != candidate_providers
            or len(baseline_calls) != len(candidate_calls)
            or baseline_tokens != candidate_tokens
            or baseline_cost != candidate_cost
            or baseline_latency != candidate_latency
        ):
            change_type = "MODIFIED"
        else:
            change_type = "UNCHANGED"
        rows.append(
            TraceComparisonAgentOut(
                key=key,
                agent_id=representative.agent_id,
                agent_name=representative.agent_name,
                agent_role=representative.agent_role,
                change_type=change_type,
                baseline_providers=baseline_providers,
                candidate_providers=candidate_providers,
                baseline_models=baseline_models,
                candidate_models=candidate_models,
                baseline_calls=len(baseline_calls),
                candidate_calls=len(candidate_calls),
                baseline_tokens=baseline_tokens,
                candidate_tokens=candidate_tokens,
                token_delta=candidate_tokens - baseline_tokens,
                baseline_cost_micros=baseline_cost,
                candidate_cost_micros=candidate_cost,
                cost_delta_micros=candidate_cost - baseline_cost,
                baseline_average_latency_ms=baseline_latency,
                candidate_average_latency_ms=candidate_latency,
                latency_delta_ms=latency_delta,
                latency_direction=latency_direction,
            )
        )
    return sorted(rows, key=lambda item: (item.change_type == "UNCHANGED", -abs(item.cost_delta_micros), item.agent_name))


def _span_groups(detail: TraceDetailOut) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for span in detail.spans:
        key = f"{span.kind}:{span.node}:{span.agent_role or '-'}"
        group = groups.setdefault(
            key,
            {
                "kind": span.kind,
                "node": span.node,
                "label": span.label,
                "agent_role": span.agent_role,
                "executions": 0,
                "duration": 0,
                "tokens": 0,
                "cost": 0,
            },
        )
        group["executions"] += 1
        group["duration"] += span.duration_ms
        group["tokens"] += span.total_tokens
        group["cost"] += span.total_cost_micros
    return groups


def _comparison_spans(
    baseline: TraceDetailOut,
    candidate: TraceDetailOut,
) -> list[TraceComparisonSpanOut]:
    baseline_groups = _span_groups(baseline)
    candidate_groups = _span_groups(candidate)
    rows: list[TraceComparisonSpanOut] = []
    for key in baseline_groups.keys() | candidate_groups.keys():
        baseline_item = baseline_groups.get(key)
        candidate_item = candidate_groups.get(key)
        representative = candidate_item or baseline_item
        baseline_duration = int(baseline_item["duration"]) if baseline_item else 0
        candidate_duration = int(candidate_item["duration"]) if candidate_item else 0
        duration_delta, duration_percent, duration_direction = _comparison_direction(
            baseline_duration,
            candidate_duration,
            lower_is_better=True,
            minimum_delta=1_000,
        )
        if not baseline_item:
            change_type = "ADDED"
        elif not candidate_item:
            change_type = "REMOVED"
        elif (
            baseline_item["executions"] != candidate_item["executions"]
            or baseline_duration != candidate_duration
            or baseline_item["tokens"] != candidate_item["tokens"]
            or baseline_item["cost"] != candidate_item["cost"]
        ):
            change_type = "MODIFIED"
        else:
            change_type = "UNCHANGED"
        baseline_tokens = int(baseline_item["tokens"]) if baseline_item else 0
        candidate_tokens = int(candidate_item["tokens"]) if candidate_item else 0
        baseline_cost = int(baseline_item["cost"]) if baseline_item else 0
        candidate_cost = int(candidate_item["cost"]) if candidate_item else 0
        rows.append(
            TraceComparisonSpanOut(
                key=key,
                kind=str(representative["kind"]),
                node=str(representative["node"]),
                label=str(representative["label"]),
                agent_role=str(representative["agent_role"]),
                change_type=change_type,
                baseline_executions=int(baseline_item["executions"]) if baseline_item else 0,
                candidate_executions=int(candidate_item["executions"]) if candidate_item else 0,
                baseline_duration_ms=baseline_duration,
                candidate_duration_ms=candidate_duration,
                duration_delta_ms=duration_delta,
                duration_delta_percent=duration_percent,
                duration_direction=duration_direction,
                baseline_tokens=baseline_tokens,
                candidate_tokens=candidate_tokens,
                token_delta=candidate_tokens - baseline_tokens,
                baseline_cost_micros=baseline_cost,
                candidate_cost_micros=candidate_cost,
                cost_delta_micros=candidate_cost - baseline_cost,
            )
        )
    return sorted(
        rows,
        key=lambda item: (item.change_type == "UNCHANGED", -abs(item.duration_delta_ms), item.label),
    )


def compare_trace_runs(
    db: Session,
    current_user: User,
    *,
    baseline_id: int,
    candidate_id: int,
) -> TraceComparisonOut:
    baseline = get_trace_detail(db, current_user, baseline_id)
    candidate = get_trace_detail(db, current_user, candidate_id)
    if baseline_id == candidate_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Baseline and candidate must be different")
    if baseline.run.project_id != candidate.run.project_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Workflow traces must belong to the same project",
        )
    if not baseline.run.finished_at or not candidate.run.finished_at:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only finished workflow traces can be compared",
        )

    metrics = [
        _comparison_metric("total_duration_ms", "端到端耗时", "duration", baseline.metrics.total_duration_ms, candidate.metrics.total_duration_ms, minimum_delta=1_000),
        _comparison_metric("queue_ms", "排队耗时", "duration", baseline.metrics.queue_ms, candidate.metrics.queue_ms, minimum_delta=1_000),
        _comparison_metric("active_compute_ms", "Agent 计算", "duration", baseline.metrics.active_compute_ms, candidate.metrics.active_compute_ms, minimum_delta=1_000),
        _comparison_metric("human_wait_ms", "人工等待", "duration", baseline.metrics.human_wait_ms, candidate.metrics.human_wait_ms, minimum_delta=1_000),
        _comparison_metric("coordination_ms", "协调开销", "duration", baseline.metrics.coordination_ms, candidate.metrics.coordination_ms, minimum_delta=1_000),
        _comparison_metric("total_tokens", "Token", "tokens", baseline.metrics.total_tokens, candidate.metrics.total_tokens, minimum_delta=100),
        _comparison_metric("total_cost_micros", "预估成本", "cost", baseline.metrics.total_cost_micros, candidate.metrics.total_cost_micros, minimum_delta=100),
        _comparison_metric("total_llm_calls", "模型调用", "count", baseline.metrics.total_llm_calls, candidate.metrics.total_llm_calls, lower_is_better=False),
    ]
    outcome = _outcome_direction(baseline.run.status, candidate.run.status)
    verdict, regression_count, improvement_count = _comparison_verdict(outcome, metrics)
    agents = _comparison_agents(baseline, candidate)
    spans = _comparison_spans(baseline, candidate)
    return TraceComparisonOut(
        baseline=baseline.run,
        candidate=candidate.run,
        summary=TraceComparisonSummaryOut(
            verdict=verdict,
            outcome_direction=outcome,
            regression_count=regression_count,
            improvement_count=improvement_count,
            changed_agent_count=sum(item.change_type != "UNCHANGED" for item in agents),
            changed_span_count=sum(item.change_type != "UNCHANGED" for item in spans),
        ),
        metrics=metrics,
        agents=agents,
        spans=spans,
    )
