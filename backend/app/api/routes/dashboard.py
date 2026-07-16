from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.routes.projects import accessible_project_ids
from app.core.database import get_db
from app.models import Agent, KnowledgeDocument, Project, Task, User
from app.schemas import DashboardStats

router = APIRouter()


@router.get("/stats", response_model=DashboardStats)
def stats(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> DashboardStats:
    project_ids = accessible_project_ids(current_user, db)
    task_counts = {"TODO": 0, "RUNNING": 0, "DONE": 0, "FAILED": 0}
    if project_ids:
        for status, count in db.execute(
            select(Task.status, func.count(Task.id)).where(Task.project_id.in_(project_ids)).group_by(Task.status)
        ):
            task_counts[status.value] = count
    recent_projects = list(
        db.scalars(select(Project).where(Project.id.in_(project_ids)).order_by(Project.created_at.desc()).limit(5))
    )
    document_filter = KnowledgeDocument.owner_id == current_user.id
    if project_ids:
        document_filter = or_(document_filter, KnowledgeDocument.project_id.in_(project_ids))
    return DashboardStats(
        projects=len(project_ids),
        agents=db.scalar(select(func.count(Agent.id))) or 0,
        tasks=task_counts,
        documents=db.scalar(select(func.count(KnowledgeDocument.id)).where(document_filter)) or 0,
        recent_activities=[f"项目动态：{project.name}" for project in recent_projects],
    )
