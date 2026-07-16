from datetime import timedelta
from pathlib import Path
from secrets import token_urlsafe
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.config import get_settings
from app.core.database import get_db
from app.core.rate_limit import check_rate_limit, login_rate_limit_key
from app.core.security import create_access_token, decode_access_token, verify_password
from app.models import Agent, AgentRun, Project, TokenTransaction, User, UserRole, WorkflowRun
from app.services.billing import BillingReferenceError, InsufficientTokensError, apply_token_change


router = APIRouter(prefix="/admin", tags=["python-admin"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
settings = get_settings()


def current_admin(request: Request, db: Session) -> User | None:
    token = request.cookies.get(settings.admin_cookie_name)
    subject = decode_access_token(token) if token else None
    user = db.get(User, int(subject)) if subject and subject.isdigit() else None
    if not user or not user.is_active or user.role != UserRole.admin:
        return None
    return user


def valid_csrf(request: Request, csrf_token: str) -> bool:
    expected = request.cookies.get("agent_workspace_admin_csrf", "")
    return bool(expected and csrf_token and expected == csrf_token)


def redirect_with(message_type: str, message: str) -> RedirectResponse:
    return RedirectResponse(f"/admin?{urlencode({message_type: message})}", status_code=303)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="admin_login.html", context={"error": ""})


@router.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
) -> Response:
    check_rate_limit(login_rate_limit_key(request, email))
    user = db.scalar(select(User).where(User.email == email))
    if not user or not verify_password(password, user.password_hash) or user.role != UserRole.admin or not user.is_active:
        return templates.TemplateResponse(
            request=request,
            name="admin_login.html",
            context={"error": "管理员账号或密码错误"},
            status_code=401,
        )
    response = RedirectResponse("/admin", status_code=303)
    response.set_cookie(
        settings.admin_cookie_name,
        create_access_token(str(user.id), timedelta(hours=8)),
        max_age=8 * 3600,
        httponly=True,
        secure=settings.environment == "production",
        samesite="strict",
        path="/admin",
    )
    response.set_cookie(
        "agent_workspace_admin_csrf",
        token_urlsafe(32),
        max_age=8 * 3600,
        httponly=True,
        secure=settings.environment == "production",
        samesite="strict",
        path="/admin",
    )
    record_audit(db, "admin.login", user.id, resource_type="admin", resource_id=user.id, request=request)
    db.commit()
    return response


@router.get("", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)) -> Response:
    admin = current_admin(request, db)
    if not admin:
        return RedirectResponse("/admin/login", status_code=303)
    users = list(db.scalars(select(User).order_by(User.created_at.desc()).limit(200)))
    agents = list(db.scalars(select(Agent).order_by(Agent.id)))
    recent_runs = list(db.scalars(select(AgentRun).order_by(AgentRun.started_at.desc()).limit(30)))
    recent_workflows = list(db.scalars(select(WorkflowRun).order_by(WorkflowRun.created_at.desc()).limit(20)))
    consumed = db.scalar(
        select(func.coalesce(func.sum(TokenTransaction.amount), 0)).where(TokenTransaction.transaction_type == "CONSUME")
    )
    metrics = {
        "users": db.scalar(select(func.count(User.id))) or 0,
        "projects": db.scalar(select(func.count(Project.id))) or 0,
        "agent_runs": db.scalar(select(func.count(AgentRun.id))) or 0,
        "active_runs": db.scalar(select(func.count(AgentRun.id)).where(AgentRun.status == "RUNNING")) or 0,
        "token_consumed": abs(int(consumed or 0)),
    }
    return templates.TemplateResponse(
        request=request,
        name="admin_dashboard.html",
        context={
            "admin": admin,
            "csrf_token": request.cookies.get("agent_workspace_admin_csrf", ""),
            "users": users,
            "agents": agents,
            "recent_runs": recent_runs,
            "recent_workflows": recent_workflows,
            "metrics": metrics,
            "success": request.query_params.get("success", ""),
            "error": request.query_params.get("error", ""),
        },
    )


@router.post("/users/{user_id}/tokens")
def adjust_tokens(
    user_id: int,
    request: Request,
    amount: int = Form(...),
    reason: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    admin = current_admin(request, db)
    if not admin:
        return RedirectResponse("/admin/login", status_code=303)
    if not valid_csrf(request, csrf_token):
        return redirect_with("error", "CSRF 校验失败")
    if amount == 0 or not reason.strip() or abs(amount) > 1_000_000:
        return redirect_with("error", "调整数量或原因无效")
    try:
        apply_token_change(
            db,
            user_id,
            amount,
            "ADJUST",
            idempotency_key=f"admin-page:{admin.id}:{token_urlsafe(16)}",
            reference_type="admin",
            reference_id=str(admin.id),
            description=reason.strip()[:300],
            operator_user_id=admin.id,
        )
    except (InsufficientTokensError, BillingReferenceError) as exc:
        db.rollback()
        return redirect_with("error", str(exc))
    record_audit(
        db,
        "billing.admin_adjust",
        admin.id,
        resource_type="user",
        resource_id=user_id,
        details={"amount": amount, "reason": reason.strip()[:300]},
        request=request,
    )
    db.commit()
    return redirect_with("success", "Token 余额已调整")


@router.post("/agents/{agent_id}")
def update_agent_runtime(
    agent_id: int,
    request: Request,
    concurrency_limit: int = Form(...),
    human_approval_required: str | None = Form(default=None),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    admin = current_admin(request, db)
    if not admin:
        return RedirectResponse("/admin/login", status_code=303)
    if not valid_csrf(request, csrf_token):
        return redirect_with("error", "CSRF 校验失败")
    agent = db.get(Agent, agent_id)
    if not agent or not 1 <= concurrency_limit <= 100:
        return redirect_with("error", "Agent 或并发配置无效")
    agent.concurrency_limit = concurrency_limit
    agent.human_approval_required = human_approval_required == "on"
    record_audit(
        db,
        "agent.runtime_update",
        admin.id,
        resource_type="agent",
        resource_id=agent.id,
        details={"concurrency_limit": concurrency_limit, "human_approval_required": agent.human_approval_required},
        request=request,
    )
    db.commit()
    return redirect_with("success", "Agent 运行策略已更新")


@router.post("/logout")
def logout(request: Request, csrf_token: str = Form(...)) -> RedirectResponse:
    response = RedirectResponse("/admin/login", status_code=303)
    if valid_csrf(request, csrf_token):
        response.delete_cookie(settings.admin_cookie_name, path="/admin")
        response.delete_cookie("agent_workspace_admin_csrf", path="/admin")
    return response
