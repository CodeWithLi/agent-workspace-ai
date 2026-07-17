from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import ensure_permission, get_current_user
from app.api.routes.projects import accessible_project_ids, get_project_for_user
from app.core.audit import record_audit
from app.core.database import get_db
from app.core.llm import get_llm
from app.core.llm_usage import bind_llm_usage
from app.models import Report, Task, User
from app.schemas import ReportCreate, ReportOut, ReportUpdate
from app.tools.project_tools import analytics_report


router = APIRouter()


def get_report_for_user(report_id: int, user: User, db: Session, *, write: bool = False) -> Report:
    report = db.get(Report, report_id)
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    get_project_for_user(report.project_id, user, db, write=write)
    return report


@router.get("", response_model=list[ReportOut])
def list_reports(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Report]:
    project_ids = accessible_project_ids(current_user, db)
    if not project_ids:
        return []
    return list(
        db.scalars(
            select(Report).where(Report.project_id.in_(project_ids)).order_by(Report.created_at.desc())
        )
    )


@router.post("", response_model=ReportOut)
async def create_report(
    payload: ReportCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Report:
    project = get_project_for_user(payload.project_id, current_user, db, write=True)
    tasks = list(db.scalars(select(Task).where(Task.project_id == project.id)))
    analytics = analytics_report(db, project.id)
    with bind_llm_usage(db=db, user_id=current_user.id, project_id=project.id):
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
    db.flush()
    record_audit(db, "report.create", current_user.id, project.id, "report", report.id, request=request)
    db.commit()
    db.refresh(report)
    return report


@router.patch("/{report_id}", response_model=ReportOut)
def update_report(
    report_id: int,
    payload: ReportUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Report:
    ensure_permission(current_user, "projects:write")
    report = get_report_for_user(report_id, current_user, db, write=True)
    values = payload.model_dump(exclude_unset=True)
    for field, value in values.items():
        setattr(report, field, value)
    record_audit(db, "report.update", current_user.id, report.project_id, "report", report.id, {"fields": sorted(values)}, request)
    db.commit()
    db.refresh(report)
    return report


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_report(
    report_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    ensure_permission(current_user, "projects:write")
    report = get_report_for_user(report_id, current_user, db, write=True)
    record_audit(db, "report.delete", current_user.id, report.project_id, "report", report.id, request=request)
    db.delete(report)
    db.commit()
