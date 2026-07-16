from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.routes.projects import accessible_project_ids
from app.core.database import get_db
from app.models import KnowledgeDocument, Project, Requirement, Task, User
from app.schemas import GlobalSearchResponse, GlobalSearchResult

router = APIRouter()


@router.get("", response_model=GlobalSearchResponse)
def global_search(
    q: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GlobalSearchResponse:
    query = f"%{q}%"
    results: list[GlobalSearchResult] = []

    project_ids = accessible_project_ids(current_user, db)
    for project in db.scalars(select(Project).where(Project.id.in_(project_ids), Project.name.ilike(query)).limit(5)):
        results.append(GlobalSearchResult(type="project", title=project.name, description=project.description, url=f"/projects/{project.id}"))

    for requirement in db.scalars(
        select(Requirement)
        .where(
            or_(Requirement.user_id == current_user.id, Requirement.project_id.in_(project_ids)),
            Requirement.title.ilike(query),
        )
        .limit(5)
    ):
        results.append(GlobalSearchResult(type="requirement", title=requirement.title, description=requirement.content[:120], url="/requirements"))

    if project_ids:
        for task in db.scalars(select(Task).where(Task.project_id.in_(project_ids), Task.title.ilike(query)).limit(5)):
            results.append(GlobalSearchResult(type="task", title=task.title, description=task.description, url="/tasks"))

    for doc in db.scalars(
        select(KnowledgeDocument)
        .where(
            or_(KnowledgeDocument.owner_id == current_user.id, KnowledgeDocument.project_id.in_(project_ids)),
            KnowledgeDocument.filename.ilike(query),
        )
        .limit(5)
    ):
        results.append(GlobalSearchResult(type="document", title=doc.filename, description=doc.summary[:120], url="/knowledge"))

    return GlobalSearchResponse(results=results[:12])
