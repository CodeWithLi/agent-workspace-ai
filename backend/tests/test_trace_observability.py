import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import observability
from app.main import app
from app.models import (
    Agent,
    AgentRole,
    AuditLog,
    LLMUsage,
    Notification,
    Project,
    ProjectMember,
    ProjectMemberRole,
    TraceAlert,
    TraceAlertStatus,
    User,
    UserRole,
    WorkflowEvent,
    WorkflowRun,
    WorkflowStatus,
)
from app.observability import (
    compare_trace_runs,
    get_trace_alerts,
    get_trace_detail,
    get_trace_health,
    get_trace_overview,
    sync_trace_alerts,
    transition_trace_alerts,
)


NOW = datetime(2026, 7, 18, 8, 0, tzinfo=timezone.utc)


def _event(
    workflow: WorkflowRun,
    event_type: str,
    at: datetime,
    *,
    node: str = "",
    payload: dict | None = None,
) -> WorkflowEvent:
    return WorkflowEvent(
        workflow_id=workflow.id,
        node=node,
        event_type=event_type,
        message=f"{event_type} {node}".strip(),
        payload_json=json.dumps(payload or {}),
        created_at=at,
    )


def _seed_trace_data(db: Session) -> dict[str, object]:
    admin = User(
        email="trace-admin@example.com",
        name="Trace Admin",
        password_hash="hash",
        role=UserRole.admin,
    )
    alice = User(
        email="trace-alice@example.com",
        name="Alice",
        password_hash="hash",
        role=UserRole.member,
    )
    bob = User(
        email="trace-bob@example.com",
        name="Bob",
        password_hash="hash",
        role=UserRole.member,
    )
    db.add_all([admin, alice, bob])
    db.flush()

    alpha = Project(name="Alpha", owner_id=alice.id)
    beta = Project(name="Beta", owner_id=bob.id)
    db.add_all([alpha, beta])
    db.flush()
    db.add_all(
        [
            ProjectMember(project_id=alpha.id, user_id=alice.id, role=ProjectMemberRole.owner),
            ProjectMember(project_id=beta.id, user_id=bob.id, role=ProjectMemberRole.owner),
        ]
    )

    architect = Agent(
        name="Trace Architect",
        role=AgentRole.architect,
        description="Architecture",
        system_prompt="hidden architect prompt",
        model="trace-model",
    )
    product_manager = Agent(
        name="Trace Product Manager",
        role=AgentRole.product_manager,
        description="Product",
        system_prompt="hidden product prompt",
        model="trace-model",
    )
    operations = Agent(
        name="Trace Operations",
        role=AgentRole.operations_analyst,
        description="Operations",
        system_prompt="hidden operations prompt",
        model="trace-model",
    )
    db.add_all([architect, product_manager, operations])
    db.flush()

    base = NOW - timedelta(hours=1)
    completed = WorkflowRun(
        project_id=alpha.id,
        user_id=alice.id,
        status=WorkflowStatus.completed,
        current_node="completed",
        state_json=json.dumps({"prompt": "super-secret-prompt", "artifact": "secret-body"}),
        created_at=base,
        started_at=base + timedelta(minutes=1),
        finished_at=base + timedelta(minutes=13),
    )
    failed = WorkflowRun(
        project_id=beta.id,
        user_id=bob.id,
        status=WorkflowStatus.failed,
        current_node="architect",
        state_json=json.dumps({"prompt": "other-secret-prompt"}),
        error="model timeout",
        created_at=base + timedelta(minutes=5),
        started_at=base + timedelta(minutes=6),
        finished_at=base + timedelta(minutes=10),
    )
    db.add_all([completed, failed])
    db.flush()

    db.add_all(
        [
            _event(completed, "QUEUED", base, node="requirement"),
            _event(completed, "STARTED", base + timedelta(minutes=1), node="requirement"),
            _event(completed, "NODE_STARTED", base + timedelta(minutes=2), node="specialists"),
            _event(
                completed,
                "BRANCH_STARTED",
                base + timedelta(minutes=2, seconds=10),
                node="specialists",
                payload={
                    "role": "architect",
                    "revision_round": 0,
                    "deliverable": "secret architecture deliverable",
                    "prompt": "secret branch prompt",
                },
            ),
            _event(
                completed,
                "BRANCH_STARTED",
                base + timedelta(minutes=2, seconds=20),
                node="specialists",
                payload={"role": "product_manager", "revision_round": 0},
            ),
            _event(
                completed,
                "BRANCH_COMPLETED",
                base + timedelta(minutes=6),
                node="specialists",
                payload={"role": "architect", "revision_round": 0, "output_chars": 4800},
            ),
            _event(
                completed,
                "BRANCH_COMPLETED",
                base + timedelta(minutes=7),
                node="specialists",
                payload={"role": "product_manager", "revision_round": 0, "output_chars": 3200},
            ),
            _event(
                completed,
                "NODE_COMPLETED",
                base + timedelta(minutes=7, seconds=30),
                node="specialists",
                payload={"next_node": "quality_gate"},
            ),
            _event(
                completed,
                "PAUSED",
                base + timedelta(minutes=8),
                node="quality_review",
                payload={"approval_gate": "quality_review", "human_feedback": "secret feedback"},
            ),
            _event(completed, "QUEUED", base + timedelta(minutes=9), node="report"),
            _event(completed, "NODE_STARTED", base + timedelta(minutes=9), node="report"),
            _event(
                completed,
                "NODE_COMPLETED",
                base + timedelta(minutes=12),
                node="report",
                payload={"next_node": "completed"},
            ),
            _event(completed, "COMPLETED", base + timedelta(minutes=13), node="completed"),
            _event(failed, "QUEUED", base + timedelta(minutes=5), node="architect"),
            _event(failed, "STARTED", base + timedelta(minutes=6), node="architect"),
            _event(failed, "NODE_STARTED", base + timedelta(minutes=6), node="architect"),
            _event(failed, "FAILED", base + timedelta(minutes=10), node="architect"),
        ]
    )
    db.add_all(
        [
            LLMUsage(
                user_id=alice.id,
                project_id=alpha.id,
                workflow_id=completed.id,
                agent_id=architect.id,
                operation="workflow",
                provider="openai",
                model="gpt-trace",
                input_tokens=60,
                output_tokens=40,
                total_tokens=100,
                estimated_cost_micros=1000,
                latency_ms=1000,
                created_at=base + timedelta(minutes=5),
            ),
            LLMUsage(
                user_id=alice.id,
                project_id=alpha.id,
                workflow_id=completed.id,
                agent_id=product_manager.id,
                operation="workflow",
                provider="openai",
                model="gpt-trace",
                input_tokens=120,
                output_tokens=80,
                total_tokens=200,
                estimated_cost_micros=2000,
                latency_ms=2000,
                created_at=base + timedelta(minutes=6, seconds=30),
            ),
            LLMUsage(
                user_id=alice.id,
                project_id=alpha.id,
                workflow_id=completed.id,
                agent_id=operations.id,
                operation="workflow",
                provider="local",
                model="ops-trace",
                input_tokens=30,
                output_tokens=20,
                total_tokens=50,
                estimated_cost_micros=500,
                latency_ms=500,
                created_at=base + timedelta(minutes=11),
            ),
            LLMUsage(
                user_id=bob.id,
                project_id=beta.id,
                workflow_id=failed.id,
                agent_id=architect.id,
                operation="workflow",
                provider="openai",
                model="gpt-trace",
                input_tokens=40,
                output_tokens=20,
                total_tokens=60,
                estimated_cost_micros=600,
                latency_ms=3000,
                created_at=base + timedelta(minutes=8),
            ),
        ]
    )
    db.commit()
    return {
        "admin": admin,
        "alice": alice,
        "bob": bob,
        "alpha": alpha,
        "beta": beta,
        "completed": completed,
        "failed": failed,
        "architect": architect,
        "product_manager": product_manager,
        "operations": operations,
    }


def _add_comparison_candidate(db: Session, data: dict[str, object]) -> WorkflowRun:
    base = NOW - timedelta(minutes=30)
    candidate = WorkflowRun(
        project_id=data["alpha"].id,
        user_id=data["alice"].id,
        status=WorkflowStatus.completed,
        current_node="completed",
        state_json=json.dumps({"prompt": "candidate-secret", "artifact": "candidate-body"}),
        created_at=base,
        started_at=base + timedelta(seconds=30),
        finished_at=base + timedelta(minutes=10),
    )
    db.add(candidate)
    db.flush()
    db.add_all(
        [
            _event(candidate, "QUEUED", base, node="requirement"),
            _event(candidate, "STARTED", base + timedelta(seconds=30), node="requirement"),
            _event(candidate, "NODE_STARTED", base + timedelta(minutes=1), node="specialists"),
            _event(
                candidate,
                "BRANCH_STARTED",
                base + timedelta(minutes=1, seconds=10),
                node="specialists",
                payload={"role": "architect", "revision_round": 0},
            ),
            _event(
                candidate,
                "BRANCH_COMPLETED",
                base + timedelta(minutes=4, seconds=10),
                node="specialists",
                payload={"role": "architect", "revision_round": 0, "output_chars": 6200},
            ),
            _event(
                candidate,
                "NODE_COMPLETED",
                base + timedelta(minutes=5),
                node="specialists",
                payload={"next_node": "report"},
            ),
            _event(candidate, "NODE_STARTED", base + timedelta(minutes=5, seconds=30), node="report"),
            _event(
                candidate,
                "NODE_COMPLETED",
                base + timedelta(minutes=9, seconds=30),
                node="report",
                payload={"next_node": "completed"},
            ),
            _event(candidate, "COMPLETED", base + timedelta(minutes=10), node="completed"),
        ]
    )
    db.add(
        LLMUsage(
            user_id=data["alice"].id,
            project_id=data["alpha"].id,
            workflow_id=candidate.id,
            agent_id=data["architect"].id,
            operation="workflow",
            provider="openai",
            model="gpt-candidate",
            input_tokens=300,
            output_tokens=200,
            total_tokens=500,
            estimated_cost_micros=5000,
            latency_ms=5000,
            created_at=base + timedelta(minutes=4),
        )
    )
    db.commit()
    return candidate


def _add_health_history(db: Session, owner: User) -> tuple[Project, WorkflowRun]:
    project = Project(name="Health", description="Health history", owner_id=owner.id)
    db.add(project)
    db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=owner.id, role=ProjectMemberRole.owner))
    base = NOW - timedelta(hours=2)
    runs: list[WorkflowRun] = []
    for index in range(6):
        created_at = base + timedelta(minutes=index * 5)
        workflow = WorkflowRun(
            project_id=project.id,
            user_id=owner.id,
            status=WorkflowStatus.completed,
            current_node="completed",
            state_json='{"prompt":"health-secret"}',
            created_at=created_at,
            started_at=created_at,
            finished_at=created_at + timedelta(minutes=1),
        )
        db.add(workflow)
        db.flush()
        db.add(
            LLMUsage(
                user_id=owner.id,
                project_id=project.id,
                workflow_id=workflow.id,
                operation="workflow",
                provider="openai",
                model="health-model",
                input_tokens=50,
                output_tokens=50,
                total_tokens=100,
                estimated_cost_micros=1000,
                latency_ms=1000,
                created_at=created_at + timedelta(seconds=30),
            )
        )
        runs.append(workflow)

    outlier_at = base + timedelta(minutes=40)
    outlier = WorkflowRun(
        project_id=project.id,
        user_id=owner.id,
        status=WorkflowStatus.completed,
        current_node="completed",
        state_json='{"artifact":"outlier-secret"}',
        created_at=outlier_at,
        started_at=outlier_at,
        finished_at=outlier_at + timedelta(minutes=5),
    )
    db.add(outlier)
    db.flush()
    db.add(
        LLMUsage(
            user_id=owner.id,
            project_id=project.id,
            workflow_id=outlier.id,
            operation="workflow",
            provider="openai",
            model="health-model",
            input_tokens=300,
            output_tokens=200,
            total_tokens=500,
            estimated_cost_micros=5000,
            latency_ms=5000,
            created_at=outlier_at + timedelta(minutes=4),
        )
    )
    db.commit()
    return project, outlier


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(observability, "_utc_now", lambda: NOW)


def test_trace_overview_aggregates_admin_scope_and_member_scope(db: Session) -> None:
    data = _seed_trace_data(db)

    admin_overview = get_trace_overview(
        db,
        data["admin"],
        days=7,
        project_id=None,
        workflow_status=None,
    )
    assert admin_overview.metrics.total_runs == 2
    assert admin_overview.metrics.completed_runs == 1
    assert admin_overview.metrics.failed_runs == 1
    assert admin_overview.metrics.success_rate == 50.0
    assert admin_overview.metrics.average_duration_ms == 540_000
    assert admin_overview.metrics.p95_duration_ms == 780_000
    assert admin_overview.metrics.total_tokens == 410
    assert admin_overview.metrics.total_cost_micros == 4100
    assert admin_overview.metrics.total_llm_calls == 4
    assert admin_overview.status_counts == {"COMPLETED": 1, "FAILED": 1}
    assert sum(point.runs for point in admin_overview.trend) == 2
    assert {project.project_name for project in admin_overview.projects} == {"Alpha", "Beta"}
    assert {run.workflow_id for run in admin_overview.recent_runs} == {
        data["completed"].id,
        data["failed"].id,
    }

    member_overview = get_trace_overview(
        db,
        data["alice"],
        days=7,
        project_id=None,
        workflow_status=None,
    )
    assert member_overview.metrics.total_runs == 1
    assert member_overview.metrics.success_rate == 100.0
    assert member_overview.metrics.total_tokens == 350
    assert [project.project_name for project in member_overview.projects] == ["Alpha"]
    assert [run.workflow_id for run in member_overview.recent_runs] == [data["completed"].id]


def test_trace_filters_validate_project_access_and_status(db: Session) -> None:
    data = _seed_trace_data(db)

    failed_only = get_trace_overview(
        db,
        data["admin"],
        days=7,
        project_id=None,
        workflow_status=WorkflowStatus.failed,
    )
    assert failed_only.metrics.total_runs == 1
    assert failed_only.metrics.failed_runs == 1

    with pytest.raises(HTTPException) as inaccessible:
        get_trace_overview(
            db,
            data["alice"],
            days=7,
            project_id=data["beta"].id,
            workflow_status=None,
        )
    assert inaccessible.value.status_code == 404


def test_trace_health_reports_slo_breaches_error_budget_and_scope(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _seed_trace_data(db)
    monkeypatch.setattr(observability.settings, "observability_slo_min_runs", 2, raising=False)
    monkeypatch.setattr(observability.settings, "observability_slo_success_rate", 80.0, raising=False)
    monkeypatch.setattr(observability.settings, "observability_slo_p95_duration_ms", 600_000, raising=False)
    monkeypatch.setattr(observability.settings, "observability_slo_average_cost_micros", 3000, raising=False)
    monkeypatch.setattr(observability.settings, "observability_anomaly_sensitivity", 3.0, raising=False)

    health = get_trace_health(db, data["admin"], days=7, project_id=None)
    metrics = {item.key: item for item in health.metrics}
    assert health.summary.status == "BREACHED"
    assert health.summary.sample_count == 2
    assert health.summary.completed_count == 1
    assert health.summary.failed_count == 1
    assert health.summary.error_budget_allowed_failures == 0.4
    assert health.summary.error_budget_consumed_failures == 1
    assert health.summary.error_budget_remaining_percent == 0.0
    assert metrics["success_rate"].actual == 50.0
    assert metrics["success_rate"].compliant is False
    assert metrics["p95_duration_ms"].actual == 780_000
    assert metrics["p95_duration_ms"].compliant is False
    assert metrics["average_cost_micros"].actual == 2050
    assert metrics["average_cost_micros"].compliant is True
    failed_anomaly = next(item for item in health.anomalies if item.workflow_id == data["failed"].id)
    assert failed_anomaly.severity == "CRITICAL"
    assert "运行失败" in failed_anomaly.signals

    member_health = get_trace_health(db, data["alice"], days=7, project_id=None)
    assert member_health.summary.status == "INSUFFICIENT_DATA"
    assert member_health.summary.sample_count == 1
    empty_user = User(
        email="trace-empty@example.com",
        name="Empty Trace User",
        password_hash="hash",
        role=UserRole.member,
    )
    db.add(empty_user)
    db.commit()
    empty_health = get_trace_health(db, empty_user, days=7, project_id=None)
    assert empty_health.summary.status == "INSUFFICIENT_DATA"
    assert empty_health.summary.sample_count == 0
    assert empty_health.summary.error_budget_remaining_percent == 100.0
    assert empty_health.anomalies == []
    with pytest.raises(HTTPException) as inaccessible:
        get_trace_health(db, data["alice"], days=7, project_id=data["beta"].id)
    assert inaccessible.value.status_code == 404


def test_trace_health_detects_history_outliers_without_exposing_run_content(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _seed_trace_data(db)
    project, outlier = _add_health_history(db, data["admin"])
    monkeypatch.setattr(observability.settings, "observability_slo_min_runs", 5, raising=False)
    monkeypatch.setattr(observability.settings, "observability_slo_success_rate", 95.0, raising=False)
    monkeypatch.setattr(observability.settings, "observability_slo_p95_duration_ms", 600_000, raising=False)
    monkeypatch.setattr(observability.settings, "observability_slo_average_cost_micros", 10_000, raising=False)
    monkeypatch.setattr(observability.settings, "observability_anomaly_sensitivity", 3.0, raising=False)

    health = get_trace_health(db, data["admin"], days=7, project_id=project.id)
    assert health.summary.status == "HEALTHY"
    anomaly = next(item for item in health.anomalies if item.workflow_id == outlier.id)
    assert anomaly.severity == "WARNING"
    assert anomaly.signals == ["耗时偏离历史基线", "成本偏离历史基线"]
    serialized = health.model_dump_json()
    assert "health-secret" not in serialized
    assert "outlier-secret" not in serialized


def test_trace_alert_sync_is_idempotent_scoped_and_routes_notifications(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _seed_trace_data(db)
    project, outlier = _add_health_history(db, data["admin"])
    monkeypatch.setattr(observability.settings, "observability_slo_min_runs", 5)
    monkeypatch.setattr(observability.settings, "observability_slo_p95_duration_ms", 2_000_000)
    monkeypatch.setattr(observability.settings, "observability_slo_average_cost_micros", 100_000)
    monkeypatch.setattr(observability.settings, "observability_anomaly_sensitivity", 3.0)
    monkeypatch.setattr(observability.settings, "observability_alert_email_enabled", True, raising=False)

    assert sync_trace_alerts(db, data["admin"], days=7, project_id=None) == 2
    db.commit()
    alerts = list(db.query(TraceAlert).order_by(TraceAlert.workflow_id))
    assert {item.workflow_id for item in alerts} == {data["failed"].id, outlier.id}
    outlier_alert = next(item for item in alerts if item.workflow_id == outlier.id)
    assert outlier_alert.project_id == project.id
    assert json.loads(outlier_alert.signals_json) == ["耗时偏离历史基线", "成本偏离历史基线"]
    assert outlier_alert.status == TraceAlertStatus.open
    assert outlier_alert.severity == "WARNING"

    notifications = list(db.query(Notification).order_by(Notification.id))
    assert len(notifications) == 4
    assert {item.channel for item in notifications} == {"in_app", "email"}
    assert all(item.status == ("SENT" if item.channel == "in_app" else "SCHEDULED") for item in notifications)
    assert sync_trace_alerts(db, data["admin"], days=7, project_id=None) == 0
    db.commit()
    assert db.query(Notification).count() == 4

    admin_alerts = get_trace_alerts(db, data["admin"], days=7, project_id=None, alert_status=None, severity=None)
    assert admin_alerts.summary.total == 2
    assert admin_alerts.summary.open == 2
    assert {item.workflow_id for item in admin_alerts.items} == {data["failed"].id, outlier.id}
    assert get_trace_alerts(db, data["alice"], days=7, project_id=None, alert_status=None, severity=None).items == []
    bob_alerts = get_trace_alerts(db, data["bob"], days=7, project_id=None, alert_status=None, severity=None)
    assert [item.workflow_id for item in bob_alerts.items] == [data["failed"].id]
    data["beta"].owner_id = data["admin"].id
    membership = db.query(ProjectMember).filter_by(project_id=data["beta"].id, user_id=data["bob"].id).one()
    db.delete(membership)
    db.commit()
    assert get_trace_alerts(
        db,
        data["bob"],
        days=7,
        project_id=None,
        alert_status=None,
        severity=None,
    ).items == []
    serialized = admin_alerts.model_dump_json()
    assert "health-secret" not in serialized
    assert "outlier-secret" not in serialized
    assert "other-secret-prompt" not in serialized


def test_trace_alert_sync_backfills_more_than_health_response_limit(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _seed_trace_data(db)
    base = NOW - timedelta(hours=5)
    db.add_all(
        [
            WorkflowRun(
                project_id=data["beta"].id,
                user_id=data["bob"].id,
                status=WorkflowStatus.failed,
                current_node="architect",
                created_at=base + timedelta(minutes=index * 2),
                started_at=base + timedelta(minutes=index * 2, seconds=10),
                finished_at=base + timedelta(minutes=index * 2 + 1),
            )
            for index in range(25)
        ]
    )
    db.commit()
    monkeypatch.setattr(observability.settings, "observability_slo_p95_duration_ms", 2_000_000)
    monkeypatch.setattr(observability.settings, "observability_slo_average_cost_micros", 100_000)
    monkeypatch.setattr(observability.settings, "observability_alert_email_enabled", False, raising=False)

    assert sync_trace_alerts(db, data["admin"], days=7, project_id=None) == 26
    db.commit()
    assert db.query(TraceAlert).count() == 26


def test_trace_alert_state_machine_is_scoped_audited_and_idempotent(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _seed_trace_data(db)
    monkeypatch.setattr(observability.settings, "observability_slo_min_runs", 5)
    monkeypatch.setattr(observability.settings, "observability_slo_p95_duration_ms", 2_000_000)
    monkeypatch.setattr(observability.settings, "observability_slo_average_cost_micros", 100_000)
    monkeypatch.setattr(observability.settings, "observability_alert_email_enabled", False, raising=False)
    assert sync_trace_alerts(db, data["admin"], days=7, project_id=None) == 1
    db.commit()
    alert = db.query(TraceAlert).one()

    with pytest.raises(HTTPException) as hidden:
        transition_trace_alerts(
            db,
            data["alice"],
            alert_ids=[alert.id],
            action="ACKNOWLEDGE",
            resolution_note="",
        )
    assert hidden.value.status_code == 404

    acknowledged = transition_trace_alerts(
        db,
        data["bob"],
        alert_ids=[alert.id],
        action="ACKNOWLEDGE",
        resolution_note="",
    )
    db.commit()
    assert acknowledged[0].status == TraceAlertStatus.acknowledged
    assert acknowledged[0].acknowledged_by_user_id == data["bob"].id
    assert transition_trace_alerts(
        db,
        data["bob"],
        alert_ids=[alert.id],
        action="ACKNOWLEDGE",
        resolution_note="",
    )[0].status == TraceAlertStatus.acknowledged

    resolved = transition_trace_alerts(
        db,
        data["bob"],
        alert_ids=[alert.id],
        action="RESOLVE",
        resolution_note="已修复模型超时并完成复盘",
    )
    db.commit()
    assert resolved[0].status == TraceAlertStatus.resolved
    assert resolved[0].resolution_note == "已修复模型超时并完成复盘"
    with pytest.raises(HTTPException) as backwards:
        transition_trace_alerts(
            db,
            data["bob"],
            alert_ids=[alert.id],
            action="ACKNOWLEDGE",
            resolution_note="",
        )
    assert backwards.value.status_code == 409
    actions = {item.action for item in db.query(AuditLog).filter(AuditLog.resource_type == "trace_alert")}
    assert {"trace_alert.created", "trace_alert.acknowledge", "trace_alert.resolve"}.issubset(actions)


def test_trace_detail_pairs_spans_assigns_usage_and_redacts_payloads(db: Session) -> None:
    data = _seed_trace_data(db)

    detail = get_trace_detail(db, data["alice"], data["completed"].id)
    assert detail.metrics.total_duration_ms == 780_000
    assert detail.metrics.queue_ms == 60_000
    assert detail.metrics.active_compute_ms == 510_000
    assert detail.metrics.human_wait_ms == 60_000
    assert detail.metrics.coordination_ms == 150_000
    assert detail.metrics.total_tokens == 350
    assert detail.metrics.total_cost_micros == 3500
    assert detail.metrics.total_llm_calls == 3

    architect_branch = next(
        span for span in detail.spans if span.kind == "branch" and span.agent_role == "architect"
    )
    product_branch = next(
        span for span in detail.spans if span.kind == "branch" and span.agent_role == "product_manager"
    )
    specialists_node = next(
        span for span in detail.spans if span.kind == "node" and span.node == "specialists"
    )
    report_node = next(span for span in detail.spans if span.kind == "node" and span.node == "report")
    wait_span = next(span for span in detail.spans if span.kind == "wait")
    assert architect_branch.total_tokens == 100
    assert product_branch.total_tokens == 200
    assert specialists_node.total_tokens == 0
    assert report_node.total_tokens == 50
    assert wait_span.duration_ms == 60_000
    assert detail.metrics.critical_span_id == specialists_node.span_id

    serialized = detail.model_dump_json()
    assert "super-secret-prompt" not in serialized
    assert "secret-body" not in serialized
    assert "secret architecture deliverable" not in serialized
    assert "secret branch prompt" not in serialized
    assert "secret feedback" not in serialized
    branch_event = next(event for event in detail.events if event.event_type == "BRANCH_STARTED")
    assert branch_event.payload == {"role": "architect", "revision_round": 0}


def test_trace_detail_closes_failed_branch_attempts_independently(db: Session) -> None:
    data = _seed_trace_data(db)
    workflow = data["completed"]
    base = workflow.started_at + timedelta(minutes=2)
    db.add_all(
        [
            _event(
                workflow,
                "BRANCH_STARTED",
                base,
                node="specialists",
                payload={"role": "operations_analyst", "revision_round": 1, "workflow_attempt": 1},
            ),
            _event(
                workflow,
                "BRANCH_STARTED",
                base + timedelta(seconds=30),
                node="specialists",
                payload={"role": "operations_analyst", "revision_round": 1, "workflow_attempt": 2},
            ),
            _event(
                workflow,
                "BRANCH_FAILED",
                base + timedelta(seconds=50),
                node="specialists",
                payload={
                    "role": "operations_analyst",
                    "revision_round": 1,
                    "workflow_attempt": 2,
                    "error": "secret provider failure",
                },
            ),
        ]
    )
    db.commit()

    detail = get_trace_detail(db, data["alice"], workflow.id)
    failed_branch = next(
        span
        for span in detail.spans
        if span.kind == "branch"
        and span.agent_role == "operations_analyst"
        and span.status == "FAILED"
    )
    assert failed_branch.duration_ms == 20_000
    assert failed_branch.payload == {
        "revision_round": 1,
        "role": "operations_analyst",
        "workflow_attempt": 2,
    }
    stale_branch = next(
        span
        for span in detail.spans
        if span.kind == "branch"
        and span.agent_role == "operations_analyst"
        and span.status == "INCOMPLETE"
    )
    assert stale_branch.payload["workflow_attempt"] == 1
    assert "secret provider failure" not in detail.model_dump_json()


def test_trace_detail_pairs_local_branch_retry_attempts_independently(db: Session) -> None:
    data = _seed_trace_data(db)
    workflow = data["completed"]
    base = workflow.started_at + timedelta(minutes=3)
    db.add_all(
        [
            _event(
                workflow,
                "BRANCH_STARTED",
                base,
                node="specialists",
                payload={
                    "role": "knowledge_admin",
                    "revision_round": 0,
                    "workflow_attempt": 1,
                    "branch_attempt": 1,
                },
            ),
            _event(
                workflow,
                "BRANCH_FAILED",
                base + timedelta(seconds=5),
                node="specialists",
                payload={
                    "role": "knowledge_admin",
                    "revision_round": 0,
                    "workflow_attempt": 1,
                    "branch_attempt": 1,
                    "retryable": True,
                    "will_retry": True,
                    "error": "secret transient failure",
                },
            ),
            _event(
                workflow,
                "BRANCH_STARTED",
                base + timedelta(seconds=10),
                node="specialists",
                payload={
                    "role": "knowledge_admin",
                    "revision_round": 0,
                    "workflow_attempt": 1,
                    "branch_attempt": 2,
                },
            ),
            _event(
                workflow,
                "BRANCH_COMPLETED",
                base + timedelta(seconds=30),
                node="specialists",
                payload={
                    "role": "knowledge_admin",
                    "revision_round": 0,
                    "workflow_attempt": 1,
                    "branch_attempt": 2,
                },
            ),
        ]
    )
    db.commit()

    detail = get_trace_detail(db, data["alice"], workflow.id)
    spans = [
        span
        for span in detail.spans
        if span.kind == "branch" and span.agent_role == "knowledge_admin"
    ]
    assert [(span.status, span.attempt, span.duration_ms) for span in spans] == [
        ("FAILED", 1, 5_000),
        ("COMPLETED", 2, 20_000),
    ]
    assert spans[0].payload["retryable"] is True
    assert spans[0].payload["will_retry"] is True
    assert "secret transient failure" not in detail.model_dump_json()


def test_trace_detail_pairs_node_retries_and_legacy_starts_by_workflow_attempt(db: Session) -> None:
    data = _seed_trace_data(db)
    workflow = data["completed"]
    base = workflow.started_at + timedelta(minutes=2)
    db.add_all(
        [
            _event(
                workflow,
                "NODE_STARTED",
                base,
                node="quality_gate",
                payload={"workflow_attempt": 1},
            ),
            _event(
                workflow,
                "NODE_FAILED",
                base + timedelta(seconds=10),
                node="quality_gate",
                payload={"workflow_attempt": 1, "error": "secret quality failure"},
            ),
            _event(
                workflow,
                "NODE_STARTED",
                base + timedelta(seconds=30),
                node="quality_gate",
                payload={"workflow_attempt": 2},
            ),
            _event(
                workflow,
                "NODE_COMPLETED",
                base + timedelta(seconds=50),
                node="quality_gate",
                payload={"workflow_attempt": 2, "next_node": "project_manager"},
            ),
            _event(workflow, "NODE_STARTED", base + timedelta(minutes=1), node="tester"),
            _event(
                workflow,
                "NODE_COMPLETED",
                base + timedelta(minutes=1, seconds=15),
                node="tester",
                payload={"workflow_attempt": 3, "next_node": "report"},
            ),
        ]
    )
    db.commit()

    detail = get_trace_detail(db, data["alice"], workflow.id)
    quality_spans = [span for span in detail.spans if span.node == "quality_gate"]
    assert [(span.status, span.duration_ms) for span in quality_spans] == [
        ("FAILED", 10_000),
        ("COMPLETED", 20_000),
    ]
    assert [span.payload["workflow_attempt"] for span in quality_spans] == [1, 2]
    tester_span = next(span for span in detail.spans if span.node == "tester")
    assert tester_span.status == "COMPLETED"
    assert tester_span.duration_ms == 15_000
    assert tester_span.payload["workflow_attempt"] == 3
    assert "secret quality failure" not in detail.model_dump_json()


def test_trace_detail_is_tenant_scoped_while_admin_can_inspect_all(db: Session) -> None:
    data = _seed_trace_data(db)

    with pytest.raises(HTTPException) as hidden:
        get_trace_detail(db, data["alice"], data["failed"].id)
    assert hidden.value.status_code == 404
    assert get_trace_detail(db, data["admin"], data["failed"].id).run.owner_name == "Bob"


def test_trace_detail_exposes_immutable_retry_lineage(db: Session) -> None:
    data = _seed_trace_data(db)
    child = WorkflowRun(
        project_id=data["completed"].project_id,
        user_id=data["alice"].id,
        parent_workflow_id=data["completed"].id,
        retry_from_node="architect",
        retry_sequence=2,
        status=WorkflowStatus.failed,
        current_node="architect",
        state_json="{}",
        error="retry failed",
        created_at=NOW - timedelta(minutes=3),
        finished_at=NOW - timedelta(minutes=1),
    )
    db.add(child)
    db.commit()

    detail = get_trace_detail(db, data["alice"], child.id)

    assert detail.run.parent_workflow_id == data["completed"].id
    assert detail.run.retry_from_node == "architect"
    assert detail.run.retry_sequence == 2
    assert f'"parent_workflow_id":{data["completed"].id}' in detail.model_dump_json()


def test_trace_detail_labels_operator_intervention_wait_without_exposing_reason(db: Session) -> None:
    data = _seed_trace_data(db)
    workflow = WorkflowRun(
        project_id=data["completed"].project_id,
        user_id=data["alice"].id,
        status=WorkflowStatus.paused,
        current_node="architect",
        state_json="{}",
        pause_requested_at=NOW - timedelta(minutes=2),
        pause_requested_by_user_id=data["alice"].id,
        pause_reason="secret operator reason",
        intervention_count=2,
        created_at=NOW - timedelta(minutes=5),
        started_at=NOW - timedelta(minutes=4),
    )
    db.add(workflow)
    db.flush()
    db.add(
        _event(
            workflow,
            "PAUSED",
            NOW - timedelta(minutes=2),
            node="architect",
            payload={
                "approval_gate": "operator",
                "reason_chars": len(workflow.pause_reason),
                "private_reason": workflow.pause_reason,
            },
        )
    )
    db.commit()

    detail = get_trace_detail(db, data["alice"], workflow.id)
    wait_span = next(span for span in detail.spans if span.kind == "wait")

    assert detail.run.intervention_count == 2
    assert wait_span.label == "人工干预等待"
    assert wait_span.payload == {"approval_gate": "operator"}
    assert "secret operator reason" not in detail.model_dump_json()


def test_trace_detail_revalidates_project_membership(db: Session) -> None:
    data = _seed_trace_data(db)
    member = User(
        email="trace-revoked@example.com",
        name="Revoked Member",
        password_hash="hash",
        role=UserRole.member,
    )
    db.add(member)
    db.flush()
    membership = ProjectMember(
        project_id=data["alpha"].id,
        user_id=member.id,
        role=ProjectMemberRole.viewer,
    )
    workflow = WorkflowRun(
        project_id=data["alpha"].id,
        user_id=member.id,
        status=WorkflowStatus.queued,
        current_node="requirement",
        state_json="{}",
        created_at=NOW - timedelta(minutes=5),
    )
    db.add_all([membership, workflow])
    db.commit()

    assert get_trace_detail(db, member, workflow.id).run.workflow_id == workflow.id
    db.delete(membership)
    db.commit()
    with pytest.raises(HTTPException) as revoked:
        get_trace_detail(db, member, workflow.id)
    assert revoked.value.status_code == 404


def test_trace_sample_truncation_keeps_exact_database_totals(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _seed_trace_data(db)
    monkeypatch.setattr(observability, "RUN_ANALYSIS_LIMIT", 1)
    monkeypatch.setattr(observability, "USAGE_ANALYSIS_LIMIT", 1)

    overview = get_trace_overview(
        db,
        data["admin"],
        days=7,
        project_id=None,
        workflow_status=None,
    )
    assert overview.window.analysis_truncated is True
    assert overview.metrics.total_runs == 2
    assert overview.metrics.total_tokens == 410
    assert overview.metrics.total_cost_micros == 4100
    assert overview.metrics.total_llm_calls == 4


def test_trace_comparison_reports_mixed_efficiency_agent_and_span_changes(db: Session) -> None:
    data = _seed_trace_data(db)
    candidate = _add_comparison_candidate(db, data)

    comparison = compare_trace_runs(
        db,
        data["alice"],
        baseline_id=data["completed"].id,
        candidate_id=candidate.id,
    )
    metrics = {item.key: item for item in comparison.metrics}
    assert comparison.summary.verdict == "MIXED"
    assert comparison.summary.outcome_direction == "UNCHANGED"
    assert comparison.summary.regression_count == 2
    assert comparison.summary.improvement_count == 1
    assert metrics["total_duration_ms"].baseline_value == 780_000
    assert metrics["total_duration_ms"].candidate_value == 600_000
    assert metrics["total_duration_ms"].direction == "IMPROVED"
    assert metrics["total_tokens"].delta == 150
    assert metrics["total_tokens"].direction == "REGRESSED"
    assert metrics["total_cost_micros"].delta == 1500
    assert metrics["total_cost_micros"].direction == "REGRESSED"
    assert metrics["total_llm_calls"].direction == "CHANGED"

    agents = {item.key: item for item in comparison.agents}
    assert agents["architect"].baseline_models == ["gpt-trace"]
    assert agents["architect"].candidate_models == ["gpt-candidate"]
    assert agents["architect"].change_type == "MODIFIED"
    assert agents["product_manager"].change_type == "REMOVED"
    assert agents["operations_analyst"].change_type == "REMOVED"
    spans = {item.key: item for item in comparison.spans}
    assert spans["branch:specialists:architect"].duration_direction == "IMPROVED"
    assert spans["wait:quality_review:-"].change_type == "REMOVED"

    serialized = comparison.model_dump_json()
    assert "super-secret-prompt" not in serialized
    assert "secret-body" not in serialized
    assert "candidate-secret" not in serialized
    assert "candidate-body" not in serialized


def test_trace_comparison_rejects_invalid_or_inaccessible_pairs(db: Session) -> None:
    data = _seed_trace_data(db)
    candidate = _add_comparison_candidate(db, data)

    with pytest.raises(HTTPException) as same_run:
        compare_trace_runs(
            db,
            data["alice"],
            baseline_id=candidate.id,
            candidate_id=candidate.id,
        )
    assert same_run.value.status_code == 400

    with pytest.raises(HTTPException) as different_project:
        compare_trace_runs(
            db,
            data["admin"],
            baseline_id=data["completed"].id,
            candidate_id=data["failed"].id,
        )
    assert different_project.value.status_code == 409

    unfinished = WorkflowRun(
        project_id=data["alpha"].id,
        user_id=data["alice"].id,
        status=WorkflowStatus.queued,
        current_node="requirement",
        state_json="{}",
        created_at=NOW - timedelta(minutes=2),
    )
    db.add(unfinished)
    db.commit()
    with pytest.raises(HTTPException) as active_run:
        compare_trace_runs(
            db,
            data["alice"],
            baseline_id=candidate.id,
            candidate_id=unfinished.id,
        )
    assert active_run.value.status_code == 409

    with pytest.raises(HTTPException) as hidden:
        compare_trace_runs(
            db,
            data["alice"],
            baseline_id=candidate.id,
            candidate_id=data["failed"].id,
        )
    assert hidden.value.status_code == 404


def test_trace_routes_are_published_in_openapi() -> None:
    paths = app.openapi()["paths"]
    assert "/api/v1/traces/overview" in paths
    assert "/api/v1/traces/health" in paths
    assert "/api/v1/traces/alerts" in paths
    assert "/api/v1/traces/alerts/sync" in paths
    assert "/api/v1/traces/alerts/bulk" in paths
    assert "/api/v1/traces/compare" in paths
    assert "/api/v1/traces/{workflow_id}" in paths
