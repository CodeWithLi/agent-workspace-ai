from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.routes.projects import get_project_for_user
from app.core.database import get_db
from app.core.llm import get_llm
from app.models import Report, Task, User
from app.schemas import ReportCreate, ReportOut
from app.tools.project_tools import analytics_report

router = APIRouter()


@router.get("", response_model=list[ReportOut])
def list_reports(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Report]:
    return list(db.scalars(select(Report).where(Report.user_id == current_user.id).order_by(Report.created_at.desc())))


@router.post("", response_model=ReportOut)
async def create_report(
    payload: ReportCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Report:
    project = get_project_for_user(payload.project_id, current_user, db, write=True)
    tasks = list(db.scalars(select(Task).where(Task.project_id == project.id)))
    analytics = analytics_report(db, project.id)
    content = await get_llm().chat(
        "你是AI运营分析师。生成项目日报、周报、风险报告或进度报告。",
        f"报告类型：{payload.report_type}\n项目：{project.name}\n任务：{[task.title for task in tasks]}\n分析：{analytics}",
    )
    report = Report(
        project_id=project.id,
        user_id=current_user.id,
        report_type=payload.report_type,
        title=f"{project.name} {payload.report_type}报告",
        content=content,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report
