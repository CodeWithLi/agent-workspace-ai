import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent.router import AgentRoutingError, RouteDecision
from app.agent.concurrency import AgentBusyError, acquire_agent_slot
from app.agent.service import (
    ConversationAccessError,
    chat_with_agent,
    get_owned_conversation,
    select_agent_for_message,
    stream_chat_events,
)
from app.api.deps import ensure_permission, get_current_user, require_admin, require_permission
from app.api.routes.projects import get_project_for_user
from app.core.database import get_db
from app.core.config import get_settings
from app.core.audit import record_audit
from app.models import Agent, AgentAction, AgentRun, AgentTool, Conversation, Message, Project, User, UserRole
from app.schemas import (
    AgentOut,
    AgentActionOut,
    AgentRouteResponse,
    AgentRouteRequest,
    AgentToolOut,
    AgentToolUpdate,
    AgentUpdate,
    ChatRequest,
    ChatResponse,
    ConversationOut,
    MessageOut,
)
from app.tools.project_tools import task_create
from app.tools.registry import allowed_tools_for_role
from app.services.agent_runs import complete_agent_run, fail_agent_run
from app.services.billing import InsufficientTokensError, apply_token_change

router = APIRouter()
settings = get_settings()


def create_agent_run(
    db: Session,
    request: Request,
    current_user: User,
    agent: Agent,
    project: Project | None,
    payload: ChatRequest,
) -> AgentRun:
    existing = db.scalar(select(AgentRun).where(AgentRun.request_id == payload.request_id))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent request has already been submitted")
    run = AgentRun(
        request_id=payload.request_id,
        user_id=current_user.id,
        project_id=project.id if project else None,
        agent_id=agent.id,
        conversation_id=payload.conversation_id,
        status="RUNNING",
    )
    db.add(run)
    try:
        db.flush()
        billing = apply_token_change(
            db,
            current_user.id,
            -settings.chat_token_cost,
            "CONSUME",
            idempotency_key=f"agent:{current_user.id}:{payload.request_id}",
            reference_type="agent_run",
            reference_id=payload.request_id,
            description=f"{agent.name} 对话",
        )
        run.billing_transaction_id = billing.id
        record_audit(
            db,
            "agent.run_start",
            current_user.id,
            project.id if project else None,
            "agent_run",
            run.id,
            {"agent_id": agent.id, "request_id": payload.request_id, "token_cost": settings.chat_token_cost},
            request,
        )
        db.commit()
    except InsufficientTokensError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent request has already been submitted") from exc
    db.refresh(run)
    return run


@router.get("", response_model=list[AgentOut])
def list_agents(db: Session = Depends(get_db), _: User = Depends(require_permission("agents:read"))) -> list[Agent]:
    return list(db.scalars(select(Agent).order_by(Agent.id)))


@router.get("/{agent_id}/tools", response_model=list[AgentToolOut])
def list_agent_tools(
    agent_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("agents:read")),
) -> list[AgentTool]:
    if not db.get(Agent, agent_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI employee not found")
    return list(db.scalars(select(AgentTool).where(AgentTool.agent_id == agent_id).order_by(AgentTool.name)))


@router.patch("/{agent_id}", response_model=AgentOut)
def update_agent(
    agent_id: int,
    payload: AgentUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> Agent:
    agent = db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI employee not found")
    changed = [field for field, value in payload.model_dump().items() if getattr(agent, field) != value]
    for field, value in payload.model_dump().items():
        setattr(agent, field, value)
    record_audit(
        db,
        "agent.update",
        current_admin.id,
        resource_type="agent",
        resource_id=agent.id,
        details={"changed_fields": changed},
        request=request,
    )
    db.commit()
    db.refresh(agent)
    return agent


@router.patch("/{agent_id}/tools/{tool_id}", response_model=AgentToolOut)
def update_agent_tool(
    agent_id: int,
    tool_id: int,
    payload: AgentToolUpdate,
    request: Request,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> AgentTool:
    tool = db.get(AgentTool, tool_id)
    if not tool or tool.agent_id != agent_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent tool not found")
    roles = {role.strip() for role in payload.allowed_roles.split(",") if role.strip()}
    if not roles or not roles <= {"admin", "member"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Allowed roles must contain admin and/or member")
    agent = db.get(Agent, agent_id)
    role = agent.role.value if agent and hasattr(agent.role, "value") else str(agent.role if agent else "")
    if tool.name not in allowed_tools_for_role(role):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tool is not allowed for this AI employee role")
    tool.enabled = payload.enabled
    tool.allowed_roles = ",".join(sorted(roles))
    record_audit(
        db,
        "agent.tool_update",
        _.id,
        resource_type="agent_tool",
        resource_id=tool.id,
        details={"agent_id": agent_id, "tool": tool.name, "enabled": tool.enabled, "allowed_roles": tool.allowed_roles},
        request=request,
    )
    db.commit()
    db.refresh(tool)
    return tool


@router.get("/actions", response_model=list[AgentActionOut])
def list_agent_actions(
    action_status: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AgentAction]:
    ensure_permission(current_user, "agents:read")
    stmt = select(AgentAction)
    if current_user.role != UserRole.admin:
        stmt = stmt.where(AgentAction.user_id == current_user.id)
    if action_status:
        stmt = stmt.where(AgentAction.status == action_status.upper())
    return list(db.scalars(stmt.order_by(AgentAction.created_at.desc()).limit(200)))


@router.post("/actions/{action_id}/approve", response_model=AgentActionOut)
def approve_agent_action(
    action_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentAction:
    action = db.scalar(select(AgentAction).where(AgentAction.id == action_id).with_for_update())
    if not action or (current_user.role != UserRole.admin and action.user_id != current_user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent action not found")
    ensure_permission(current_user, "agents:read")
    if action.status != "PENDING":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent action has already been decided")
    initiator = db.get(User, action.user_id)
    if not initiator or not initiator.is_active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Action initiator is no longer active")
    ensure_permission(initiator, "agents:read")
    project = get_project_for_user(action.project_id, current_user, db, write=True) if action.project_id else None
    if action.project_id and initiator.id != current_user.id:
        get_project_for_user(action.project_id, initiator, db, write=True)
    agent = db.get(Agent, action.agent_id)
    if not agent:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="AI employee no longer exists")
    role = agent.role.value if hasattr(agent.role, "value") else str(agent.role)
    initiator_role = initiator.role.value if hasattr(initiator.role, "value") else str(initiator.role)
    enabled = {
        tool.name
        for tool in agent.tool_links
        if tool.enabled and initiator_role in {item.strip() for item in tool.allowed_roles.split(",")}
    }
    if action.tool_name not in allowed_tools_for_role(role) or action.tool_name not in enabled:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tool permission was revoked before approval")
    if action.tool_name == "task_create" and project:
        tasks = task_create(db, project.id)
        result = [{"id": task.id, "title": task.title, "status": task.status.value} for task in tasks]
    else:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Unsupported approval action")
    action.status = "EXECUTED"
    action.result_json = json.dumps(result, ensure_ascii=False)
    action.approved_by_user_id = current_user.id
    action.decided_at = datetime.now(timezone.utc)
    record_audit(
        db,
        "agent.action_approve",
        current_user.id,
        action.project_id,
        "agent_action",
        action.id,
        {"tool": action.tool_name, "created_count": len(result)},
        request,
    )
    db.commit()
    db.refresh(action)
    return action


@router.post("/actions/{action_id}/reject", response_model=AgentActionOut)
def reject_agent_action(
    action_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentAction:
    action = db.scalar(select(AgentAction).where(AgentAction.id == action_id).with_for_update())
    if not action or (current_user.role != UserRole.admin and action.user_id != current_user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent action not found")
    ensure_permission(current_user, "agents:read")
    if action.status != "PENDING":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent action has already been decided")
    action.status = "REJECTED"
    action.approved_by_user_id = current_user.id
    action.decided_at = datetime.now(timezone.utc)
    record_audit(db, "agent.action_reject", current_user.id, action.project_id, "agent_action", action.id, {"tool": action.tool_name}, request)
    db.commit()
    db.refresh(action)
    return action


def resolve_decision(payload: AgentRouteRequest, user: User, db: Session) -> RouteDecision:
    ensure_permission(user, "agents:read")
    try:
        if payload.conversation_id:
            conversation = get_owned_conversation(db, user.id, payload.conversation_id)
            if payload.agent_id and payload.agent_id != conversation.agent_id:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="切换 AI 员工需要开启新会话")
            agent = db.get(Agent, conversation.agent_id)
            if not agent:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI 员工不存在")
            return RouteDecision(agent=agent, confidence=1.0, reason="继续当前会话，保持 AI 员工角色一致")
        return select_agent_for_message(db, payload.message, payload.agent_id)
    except (AgentRoutingError, ConversationAccessError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def resolve_project(payload: AgentRouteRequest, user: User, db: Session) -> Project | None:
    project = get_project_for_user(payload.project_id, user, db, write=True) if payload.project_id else None
    if payload.conversation_id:
        conversation = get_owned_conversation(db, user.id, payload.conversation_id)
        if conversation.project_id != (project.id if project else None):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="会话所属项目与当前项目不一致")
    return project


@router.post("/route", response_model=AgentRouteResponse)
def route(
    payload: AgentRouteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentRouteResponse:
    decision = resolve_decision(payload, current_user, db)
    return AgentRouteResponse(
        agent_id=decision.agent.id,
        agent_name=decision.agent.name,
        confidence=decision.confidence,
        reason=decision.reason,
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChatResponse:
    decision = resolve_decision(payload, current_user, db)
    agent = decision.agent
    project = resolve_project(payload, current_user, db)
    try:
        lease = await acquire_agent_slot(agent.id, agent.concurrency_limit)
    except AgentBusyError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    try:
        run = create_agent_run(db, request, current_user, agent, project, payload)
    except Exception:
        await lease.release()
        raise
    try:
        conversation, answer, thinking, tool_calls, messages = await chat_with_agent(
            db, current_user, agent, payload.message, project, payload.conversation_id, decision.reason
        )
        complete_agent_run(db, run.id, conversation.id)
    except ConversationAccessError as exc:
        db.rollback()
        fail_agent_run(db, run.id, run.billing_transaction_id, str(exc))
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        fail_agent_run(db, run.id, run.billing_transaction_id, str(exc))
        raise
    finally:
        await lease.release()
    return ChatResponse(
        conversation_id=conversation.id,
        agent_id=agent.id,
        agent_name=agent.name,
        answer=answer,
        thinking=thinking,
        tool_calls=tool_calls,
        messages=messages,
    )


@router.post("/chat/stream")
async def chat_stream(
    payload: ChatRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    decision = resolve_decision(payload, current_user, db)
    agent = decision.agent
    project = resolve_project(payload, current_user, db)
    try:
        lease = await acquire_agent_slot(agent.id, agent.concurrency_limit)
    except AgentBusyError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    try:
        run = create_agent_run(db, request, current_user, agent, project, payload)
    except Exception:
        await lease.release()
        raise
    return StreamingResponse(
        stream_chat_events(
            current_user.id,
            agent.id,
            payload.message,
            project.id if project else None,
            payload.conversation_id,
            decision.reason,
            run.id,
            run.billing_transaction_id,
            lease,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(
    project_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Conversation]:
    ensure_permission(current_user, "agents:read")
    stmt = select(Conversation).where(Conversation.user_id == current_user.id)
    if project_id is not None:
        get_project_for_user(project_id, current_user, db)
        stmt = stmt.where(Conversation.project_id == project_id)
    return list(db.scalars(stmt.order_by(Conversation.created_at.desc()).limit(100)))


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
def list_conversation_messages(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Message]:
    ensure_permission(current_user, "agents:read")
    try:
        conversation = get_owned_conversation(db, current_user.id, conversation_id)
    except ConversationAccessError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return list(db.scalars(select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at)))
