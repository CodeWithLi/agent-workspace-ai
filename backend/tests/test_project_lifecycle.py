import json

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.routes.meetings import create_tasks_from_meeting, update_meeting
from app.api.routes.projects import add_task_comment, list_project_activity, update_project, update_task
from app.api.routes.reports import update_report
from app.api.routes.requirements import update_requirement
from app.api.routes.workflow import publish_workflow_artifact
from app.models import Meeting, Project, ProjectMember, ProjectMemberRole, Report, Requirement, Task, User, WorkflowRun, WorkflowStatus
from app.schemas import (
    MeetingUpdate,
    ProjectUpdate,
    ReportUpdate,
    RequirementUpdate,
    TaskCommentCreate,
    TaskUpdate,
    WorkflowPublishRequest,
)


def request(path: str = "/"):
    from starlette.requests import Request

    return Request(
        {
            "type": "http",
            "method": "PATCH",
            "path": path,
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 1234),
        }
    )


def project_team(db: Session) -> tuple[User, User, Project]:
    owner = User(email="lifecycle-owner@example.com", name="Owner", password_hash="hash", permissions="projects:write,knowledge:write")
    member = User(email="lifecycle-member@example.com", name="Member", password_hash="hash", permissions="projects:write,knowledge:write")
    db.add_all([owner, member])
    db.flush()
    project = Project(name="Lifecycle", owner_id=owner.id)
    db.add(project)
    db.flush()
    db.add_all(
        [
            ProjectMember(project_id=project.id, user_id=owner.id, role=ProjectMemberRole.owner),
            ProjectMember(project_id=project.id, user_id=member.id, role=ProjectMemberRole.editor),
        ]
    )
    db.commit()
    return owner, member, project


def test_project_tasks_comments_and_activity_have_full_lifecycle(db: Session) -> None:
    owner, member, project = project_team(db)
    updated_project = update_project(
        project.id,
        ProjectUpdate(name="Lifecycle V2", description="managed", status="ACTIVE"),
        request(),
        owner,
        db,
    )
    assert updated_project.name == "Lifecycle V2"

    task = Task(project_id=project.id, title="Implement", status="TODO")
    db.add(task)
    db.commit()
    updated_task = update_task(
        project.id,
        task.id,
        TaskUpdate(status="RUNNING", assignee_user_id=member.id, priority="HIGH"),
        request(),
        owner,
        db,
    )
    assert updated_task.assignee_user_id == member.id
    comment = add_task_comment(
        project.id,
        task.id,
        TaskCommentCreate(content="Started implementation"),
        request(),
        member,
        db,
    )
    assert comment.user_name == "Member"
    activity = list_project_activity(project.id, 50, owner, db)
    assert {item.action for item in activity} >= {"project.update", "task.update", "task.comment"}


def test_requirements_meetings_and_reports_are_editable(db: Session) -> None:
    owner, _, project = project_team(db)
    requirement = Requirement(project_id=project.id, user_id=owner.id, title="Old", content="Old", status="NEW")
    meeting = Meeting(
        project_id=project.id,
        user_id=owner.id,
        title="Planning",
        transcript="notes",
        action_items=json.dumps([{"task": "Ship API", "owner": "Member", "due_date": "2026-08-01"}]),
    )
    report = Report(project_id=project.id, user_id=owner.id, report_type="daily", title="Old report", content="old")
    db.add_all([requirement, meeting, report])
    db.commit()

    changed_requirement = update_requirement(
        requirement.id,
        RequirementUpdate(title="Approved", status="APPROVED"),
        request(),
        owner,
        db,
    )
    assert changed_requirement.status == "APPROVED"
    changed_meeting = update_meeting(
        meeting.id,
        MeetingUpdate(title="Planning review"),
        request(),
        owner,
        db,
    )
    assert changed_meeting.title == "Planning review"
    tasks = create_tasks_from_meeting(meeting.id, request(), owner, db)
    assert [task.title for task in tasks] == ["Ship API"]
    changed_report = update_report(
        report.id,
        ReportUpdate(title="Published report", content="updated", report_type="weekly"),
        request(),
        owner,
        db,
    )
    assert changed_report.report_type == "weekly"


@pytest.mark.asyncio
async def test_workflow_artifact_can_publish_to_report_or_knowledge(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, _, project = project_team(db)
    workflow = WorkflowRun(
        project_id=project.id,
        user_id=owner.id,
        status=WorkflowStatus.completed,
        current_node="completed",
        state_json=json.dumps({"documents": [{"type": "PRD", "content": "# Product requirements"}]}),
    )
    db.add(workflow)
    db.commit()
    report_result = await publish_workflow_artifact(
        workflow.id,
        WorkflowPublishRequest(document_type="PRD", target="report", request_id="publish-report-request"),
        request(),
        owner,
        db,
    )
    assert report_result.report_id is not None
    assert db.scalar(select(func.count(Report.id)).where(Report.project_id == project.id)) == 1

    monkeypatch.setattr("app.rag.service.object_storage.save", lambda *_args: "minio://bucket/workflow-prd.md")
    knowledge_result = await publish_workflow_artifact(
        workflow.id,
        WorkflowPublishRequest(document_type="PRD", target="knowledge", request_id="publish-knowledge-request"),
        request(),
        owner,
        db,
    )
    assert knowledge_result.document_id is not None
