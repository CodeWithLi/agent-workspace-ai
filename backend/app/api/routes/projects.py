from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import ensure_permission, get_current_user
from app.core.database import get_db
from app.core.audit import record_audit
from app.models import Project, ProjectMember, ProjectMemberRole, Task, User
from app.schemas import (
    ProjectCreate,
    ProjectMemberCreate,
    ProjectMemberOut,
    ProjectOut,
    TaskCreate,
    TaskOut,
    TaskUpdate,
)

router = APIRouter()


def project_role(project: Project, user: User, db: Session) -> ProjectMemberRole | None:
    if project.owner_id == user.id:
        return ProjectMemberRole.owner
    return db.scalar(
        select(ProjectMember.role).where(ProjectMember.project_id == project.id, ProjectMember.user_id == user.id)
    )


def get_project_for_user(project_id: int, user: User, db: Session, write: bool = False) -> Project:
    project = db.get(Project, project_id)
    role = project_role(project, user, db) if project else None
    if not project or role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if write and role == ProjectMemberRole.viewer:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Project viewer has read-only access")
    if write:
        ensure_permission(user, "projects:write")
    project.current_user_role = role
    return project


def get_owned_project(project_id: int, user: User, db: Session) -> Project:
    """Backward-compatible read access helper used by project-aware routes."""
    return get_project_for_user(project_id, user, db)


def accessible_project_ids(user: User, db: Session) -> list[int]:
    return list(
        db.scalars(
            select(Project.id)
            .outerjoin(ProjectMember, ProjectMember.project_id == Project.id)
            .where(or_(Project.owner_id == user.id, ProjectMember.user_id == user.id))
            .distinct()
        )
    )


def member_response(member: ProjectMember) -> ProjectMemberOut:
    return ProjectMemberOut(
        id=member.id,
        project_id=member.project_id,
        user_id=member.user_id,
        email=member.user.email,
        name=member.user.name,
        role=member.role,
        created_at=member.created_at,
    )


@router.get("", response_model=list[ProjectOut])
def list_projects(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Project]:
    ids = accessible_project_ids(current_user, db)
    if not ids:
        return []
    projects = list(db.scalars(select(Project).where(Project.id.in_(ids)).order_by(Project.created_at.desc())))
    for project in projects:
        project.current_user_role = project_role(project, current_user, db)
    return projects


@router.post("", response_model=ProjectOut)
def create_project(
    payload: ProjectCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Project:
    ensure_permission(current_user, "projects:write")
    project = Project(
        name=payload.name,
        description=payload.description,
        members=payload.members,
        owner_id=current_user.id,
    )
    db.add(project)
    db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=current_user.id, role=ProjectMemberRole.owner))
    record_audit(db, "project.create", current_user.id, project.id, "project", project.id, request=request)
    db.commit()
    db.refresh(project)
    project.current_user_role = ProjectMemberRole.owner
    return project


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Project:
    return get_project_for_user(project_id, current_user, db)


@router.get("/{project_id}/members", response_model=list[ProjectMemberOut])
def list_members(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ProjectMemberOut]:
    get_project_for_user(project_id, current_user, db)
    members = list(
        db.scalars(select(ProjectMember).where(ProjectMember.project_id == project_id).order_by(ProjectMember.created_at))
    )
    return [member_response(member) for member in members]


@router.post("/{project_id}/members", response_model=ProjectMemberOut)
def add_or_update_member(
    project_id: int,
    payload: ProjectMemberCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectMemberOut:
    ensure_permission(current_user, "projects:write")
    project = get_project_for_user(project_id, current_user, db)
    if project.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the project owner can manage members")
    invited_user = db.scalar(select(User).where(User.email == payload.email))
    if not invited_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User must register before being invited")
    if invited_user.id == project.owner_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Project owner is already a member")
    member = db.scalar(
        select(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.user_id == invited_user.id)
    )
    if member:
        member.role = payload.role
    else:
        member = ProjectMember(project_id=project_id, user_id=invited_user.id, role=payload.role)
        db.add(member)
    db.flush()
    record_audit(
        db,
        "project.member_upsert",
        current_user.id,
        project.id,
        "project_member",
        member.id,
        {"member_user_id": invited_user.id, "role": payload.role.value},
        request,
    )
    db.commit()
    db.refresh(member)
    return member_response(member)


@router.delete("/{project_id}/members/{member_id}")
def remove_member(
    project_id: int,
    member_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    ensure_permission(current_user, "projects:write")
    project = get_project_for_user(project_id, current_user, db)
    if project.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the project owner can manage members")
    member = db.get(ProjectMember, member_id)
    if not member or member.project_id != project_id or member.role == ProjectMemberRole.owner:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project member not found")
    removed_user_id = member.user_id
    db.delete(member)
    record_audit(db, "project.member_remove", current_user.id, project.id, "project_member", member_id, {"member_user_id": removed_user_id}, request)
    db.commit()
    return {"ok": True}


@router.get("/{project_id}/tasks", response_model=list[TaskOut])
def list_tasks(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Task]:
    get_project_for_user(project_id, current_user, db)
    return list(db.scalars(select(Task).where(Task.project_id == project_id).order_by(Task.created_at.desc())))


@router.post("/{project_id}/tasks", response_model=TaskOut)
def create_task(
    project_id: int,
    payload: TaskCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Task:
    get_project_for_user(project_id, current_user, db, write=True)
    task = Task(project_id=project_id, **payload.model_dump())
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.patch("/{project_id}/tasks/{task_id}", response_model=TaskOut)
def update_task(
    project_id: int,
    task_id: int,
    payload: TaskUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Task:
    get_project_for_user(project_id, current_user, db, write=True)
    task = db.get(Task, task_id)
    if not task or task.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    task.status = payload.status
    db.commit()
    db.refresh(task)
    return task
