import json

import pytest
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.agent.orchestration import AgentHandoff, build_fallback_plan
from app.api.routes.workflow import continue_workflow
from app.langgraph.workflow import initial_state
from app.models import Project, User, WorkflowEvent, WorkflowRun, WorkflowStatus
from app.schemas import WorkflowContinueRequest


def http_request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
    )


def paused_branch_workflow(
    db: Session,
    user: User,
    project: Project,
) -> WorkflowRun:
    plan = build_fallback_plan("设计可灰度发布并可恢复的企业协作流程")
    operations = next(
        assignment for assignment in plan.assignments if assignment.role == "operations_analyst"
    )
    state = initial_state(project, "设计可灰度发布并可恢复的企业协作流程", require_plan_approval=True)
    plan_snapshot = plan.model_dump(mode="json")
    state.update(
        {
            "execution_plan": plan_snapshot,
            "plan_version": 1,
            "plan_revisions": [
                {
                    "version": 1,
                    "plan": plan_snapshot,
                    "feedback": "",
                    "created_at": "2026-07-20T00:00:00Z",
                }
            ],
            "plan_approved": True,
            "specialist_handoffs": [
                AgentHandoff(
                    role=operations.role,
                    objective=operations.objective,
                    deliverable=operations.deliverable,
                    content="已完成发布窗口、监控阈值、失败信号、回滚条件和后续负责人定义。" * 2,
                    revision_round=0,
                ).model_dump(mode="json")
            ],
            "specialist_failures": [
                {
                    "role": "test_engineer",
                    "wave": 1,
                    "branch_attempt": 1,
                    "retryable": False,
                    "category": "NON_RETRYABLE",
                    "message": "测试环境配置缺少验收凭据",
                }
            ],
            "messages": [
                {"role": "architect_agent", "content": "保留的架构证据"},
                {"role": "specialist_operations_analyst", "content": "旧运营交接"},
                {"role": "quality_gate_agent", "content": "旧质量审查"},
            ],
        }
    )
    workflow = WorkflowRun(
        project_id=project.id,
        user_id=user.id,
        status=WorkflowStatus.paused,
        current_node="specialist_review",
        state_json=json.dumps(state, ensure_ascii=False),
        pause_before_report=True,
        attempt_count=1,
    )
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return workflow


@pytest.mark.asyncio
async def test_branch_review_api_retries_checkpoint_or_returns_to_planner(db: Session) -> None:
    user = User(
        email="branch-recovery-api@example.com",
        name="Branch Recovery",
        password_hash="hash",
        permissions="projects:write",
    )
    db.add(user)
    db.flush()
    project = Project(name="Branch Recovery", owner_id=user.id)
    db.add(project)
    db.commit()

    retry_workflow = paused_branch_workflow(db, user, project)
    retry_response = await continue_workflow(
        WorkflowContinueRequest(
            workflow_id=retry_workflow.id,
            decision="RETRY",
            human_feedback="补齐测试凭据后，仅重跑失败测试分支。",
        ),
        http_request("/api/v1/workflow/continue"),
        user,
        db,
    )
    retry_state = retry_response.state

    assert retry_response.status == WorkflowStatus.queued
    assert retry_response.current_node == "specialists"
    assert [item["role"] for item in retry_state["specialist_handoffs"]] == ["operations_analyst"]
    assert retry_state["specialist_failures"] == []
    assert retry_state["specialist_recovery_count"] == 1
    assert retry_state["revision_feedback"] == "补齐测试凭据后，仅重跑失败测试分支。"
    retry_events = [
        event.event_type
        for event in db.query(WorkflowEvent)
        .filter(WorkflowEvent.workflow_id == retry_workflow.id)
        .order_by(WorkflowEvent.id)
    ]
    assert "SPECIALIST_RETRY_REQUESTED" in retry_events

    replan_workflow = paused_branch_workflow(db, user, project)
    replan_response = await continue_workflow(
        WorkflowContinueRequest(
            workflow_id=replan_workflow.id,
            decision="REPLAN",
            human_feedback="增加安全审查角色并重新设计验收依赖。",
        ),
        http_request("/api/v1/workflow/continue"),
        user,
        db,
    )
    replan_state = replan_response.state

    assert replan_response.status == WorkflowStatus.queued
    assert replan_response.current_node == "planning"
    assert replan_state["require_plan_approval"] is True
    assert replan_state["plan_approved"] is False
    assert replan_state["plan_revision_count"] == 1
    assert replan_state["plan_revision_feedback"] == "增加安全审查角色并重新设计验收依赖。"
    assert replan_state["specialist_handoffs"] == []
    assert replan_state["specialist_failures"] == []
    assert replan_state["quality_gate"] == {}
    assert replan_state["messages"] == [
        {"role": "architect_agent", "content": "保留的架构证据"}
    ]
    replan_events = [
        event.event_type
        for event in db.query(WorkflowEvent)
        .filter(WorkflowEvent.workflow_id == replan_workflow.id)
        .order_by(WorkflowEvent.id)
    ]
    assert "SPECIALIST_REPLAN_REQUESTED" in replan_events
