import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.routes.projects import accessible_project_ids, get_project_for_user, project_role
from app.models import Project, ProjectMember, ProjectMemberRole, User, UserRole


def make_user(db: Session, email: str) -> User:
    user = User(
        email=email,
        name=email.split("@")[0],
        password_hash="hash",
        role=UserRole.member,
        permissions="projects:write",
    )
    db.add(user)
    db.flush()
    return user


def test_project_membership_enforces_read_and_write_roles(db: Session) -> None:
    owner = make_user(db, "owner@example.com")
    editor = make_user(db, "editor@example.com")
    viewer = make_user(db, "viewer@example.com")
    outsider = make_user(db, "outsider@example.com")
    project = Project(name="Shared", owner_id=owner.id)
    db.add(project)
    db.flush()
    db.add_all(
        [
            ProjectMember(project_id=project.id, user_id=owner.id, role=ProjectMemberRole.owner),
            ProjectMember(project_id=project.id, user_id=editor.id, role=ProjectMemberRole.editor),
            ProjectMember(project_id=project.id, user_id=viewer.id, role=ProjectMemberRole.viewer),
        ]
    )
    db.commit()

    assert project_role(project, owner, db) == ProjectMemberRole.owner
    assert get_project_for_user(project.id, editor, db, write=True).id == project.id
    assert get_project_for_user(project.id, viewer, db).id == project.id
    assert project.id in accessible_project_ids(viewer, db)
    with pytest.raises(HTTPException) as viewer_error:
        get_project_for_user(project.id, viewer, db, write=True)
    assert viewer_error.value.status_code == 403
    with pytest.raises(HTTPException) as outsider_error:
        get_project_for_user(project.id, outsider, db)
    assert outsider_error.value.status_code == 404

    editor.permissions = ""
    with pytest.raises(HTTPException) as permission_error:
        get_project_for_user(project.id, editor, db, write=True)
    assert permission_error.value.status_code == 403
    assert permission_error.value.detail == "Permission required: projects:write"
