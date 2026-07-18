from __future__ import annotations

import json
import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Agent,
    LLMUsage,
    Project,
    ProjectMember,
    User,
    UserRole,
    WorkflowEvent,
    WorkflowRun,
    WorkflowStatus,
)
from app.schemas import (
    TraceAgentMetricOut,
    TraceBottleneckOut,
    TraceDetailMetricsOut,
    TraceDetailOut,
    TraceEventDetailOut,
    TraceMetricSummaryOut,
    TraceModelCallOut,
    TraceOverviewOut,
    TraceProjectOptionOut,
    TraceRunOut,
    TraceSpanOut,
    TraceTrendPointOut,
    TraceWindowOut,
)


RUN_ANALYSIS_LIMIT = 2_000
USAGE_ANALYSIS_LIMIT = 50_000
BOTTLENECK_RUN_LIMIT = 500
RECENT_RUN_LIMIT = 100

ACTIVE_STATUSES = {
    WorkflowStatus.queued,
    WorkflowStatus.running,
    WorkflowStatus.cancelling,
    WorkflowStatus.compensating,
}
FAILED_STATUSES = {WorkflowStatus.failed, WorkflowStatus.compensation_failed}

NODE_LABELS = {
    "requirement": "需求分析",
    "product": "产品方案",
    "architect": "架构设计",
    "planning": "动态规划",
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
    "approval_gate",
    "next_node",
    "output_chars",
    "revision_roles",
    "revision_round",
    "role",
    "roles",
    "score",
    "success_criteria_count",
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
            spans.append(
                _SpanDraft(
                    span_id=f"wait-{open_pause.id}",
                    kind="wait",
                    node=open_pause.node,
                    label="人工确认等待",
                    agent_role="",
                    status="COMPLETED",
                    attempt=1,
                    started_at=open_pause.created_at,
                    finished_at=event.created_at,
                    duration_ms=_duration_ms(open_pause.created_at, event.created_at),
                    payload=_public_payload(open_pause),
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
        spans.append(
            _SpanDraft(
                span_id=f"wait-{open_pause.id}",
                kind="wait",
                node=open_pause.node,
                label="人工确认等待",
                agent_role="",
                status="PAUSED" if workflow.status == WorkflowStatus.paused else open_status,
                attempt=1,
                started_at=open_pause.created_at,
                finished_at=workflow.finished_at,
                duration_ms=_duration_ms(open_pause.created_at, open_end),
                payload=_public_payload(open_pause),
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
