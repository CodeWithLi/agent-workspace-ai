import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent.router import AgentRoutingError, RouteDecision
from app.agent.concurrency import AgentBusyError, acquire_agent_slot
from app.agent.discussion import DiscussionConfigurationError, select_discussion_agents, stream_discussion_events
from app.agent.service import (
    ConversationAccessError,
    chat_with_agent,
    get_owned_conversation,
    regenerate_assistant_message,
    select_agent_for_message,
    stream_chat_events,
)
from app.api.deps import ensure_permission, get_current_user, require_admin, require_permission
from app.api.routes.projects import get_project_for_user
from app.core.database import get_db
from app.core.config import get_settings
from app.core.audit import record_audit
from app.core.llm_usage import bind_llm_usage
from app.models import Agent, AgentAction, AgentPromptVersion, AgentRun, AgentTool, Conversation, Message, MessageFeedback, Project, User, UserRole
from app.schemas import (
    AgentOut,
    AgentActionOut,
    AgentRouteResponse,
    AgentRouteRequest,
    AgentToolOut,
    AgentToolUpdate,
    AgentUpdate,
    AgentVersionCreate,
    AgentVersionOut,
    ChatRequest,
    ChatResponse,
    ConversationOut,
    DiscussionRequest,
    MessageOut,
    MessageFeedbackOut,
    MessageFeedbackRequest,
    MessageRegenerateOut,
    MessageRegenerateRequest,
)
from app.tools.project_tools import task_create
from app.tools.registry import allowed_tools_for_role
from app.services.agent_runs import complete_agent_run, fail_agent_run
from app.services.billing import InsufficientTokensError, apply_token_change
from app.services.agent_versions import create_version

router = APIRouter()
settings = get_settings()
EVALUATION_RELEASE_REQUIRED = (
    "Direct Agent activation is disabled; create a draft and publish it through a passed evaluation run"
)


def create_agent_run(
    db: Session,
    request: Request,
    current_user: User,
    agent: Agent,
    project: Project | None,
    payload: ChatRequest | DiscussionRequest,
    *,
    token_cost: int | None = None,
    description: str | None = None,
) -> AgentRun:
    cost = settings.chat_token_cost if token_cost is None else token_cost
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
            -cost,
            "CONSUME",
            idempotency_key=f"agent:{current_user.id}:{payload.request_id}",
            reference_type="agent_run",
            reference_id=payload.request_id,
            description=description or f"{agent.name} 对话",
        )
        run.billing_transaction_id = billing.id
        record_audit(
            db,
            "agent.run_start",
            current_user.id,
            project.id if project else None,
            "agent_run",
            run.id,
            {"agent_id": agent.id, "request_id": payload.request_id, "token_cost": cost},
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


@router.patch("/{agent_id}", response_model=AgentOut, deprecated=True)
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
    values = payload.model_dump()
    changed = [field for field, value in values.items() if getattr(agent, field) != value]
    if changed:
        record_audit(
            db,
            "agent.direct_update_blocked",
            current_admin.id,
            resource_type="agent",
            resource_id=agent.id,
            details={"changed_fields": changed},
            request=request,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=EVALUATION_RELEASE_REQUIRED)
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


@router.get("/{agent_id}/versions", response_model=list[AgentVersionOut])
def list_agent_versions(
    agent_id: int,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[AgentPromptVersion]:
    if not db.get(Agent, agent_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI employee not found")
    return list(
        db.scalars(
            select(AgentPromptVersion)
            .where(AgentPromptVersion.agent_id == agent_id)
            .order_by(AgentPromptVersion.version.desc())
        )
    )


@router.post("/{agent_id}/versions", response_model=AgentVersionOut, status_code=status.HTTP_201_CREATED)
def create_agent_version(
    agent_id: int,
    payload: AgentVersionCreate,
    request: Request,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AgentPromptVersion:
    agent = db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI employee not found")
    values = payload.model_dump(exclude={"release_note"})
    version = create_version(db, agent, values, current_admin.id, release_note=payload.release_note)
    record_audit(
        db,
        "agent.version_create",
        current_admin.id,
        resource_type="agent_version",
        resource_id=version.id,
        details={"agent_id": agent.id, "version": version.version},
        request=request,
    )
    db.commit()
    db.refresh(version)
    return version


@router.post(
    "/{agent_id}/versions/{version_id}/publish",
    response_model=AgentVersionOut,
    deprecated=True,
)
def publish_agent_version(
    agent_id: int,
    version_id: int,
    request: Request,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AgentPromptVersion:
    agent = db.get(Agent, agent_id)
    version = db.get(AgentPromptVersion, version_id)
    if not agent or not version or version.agent_id != agent.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent version not found")
    record_audit(
        db,
        "agent.direct_publish_blocked",
        current_admin.id,
        resource_type="agent_version",
        resource_id=version.id,
        details={"agent_id": agent.id, "version": version.version},
        request=request,
    )
    db.commit()
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=EVALUATION_RELEASE_REQUIRED)


@router.post(
    "/{agent_id}/versions/{target_version}/rollback",
    response_model=AgentOut,
    deprecated=True,
)
def rollback_agent_version(
    agent_id: int,
    target_version: int,
    request: Request,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Agent:
    agent = db.get(Agent, agent_id)
    target = db.scalar(
        select(AgentPromptVersion).where(
            AgentPromptVersion.agent_id == agent_id,
            AgentPromptVersion.version == target_version,
        )
    )
    if not agent or not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent version not found")
    record_audit(
        db,
        "agent.direct_rollback_blocked",
        current_admin.id,
        resource_type="agent_version",
        resource_id=target.id,
        details={"agent_id": agent.id, "target_version": target_version},
        request=request,
    )
    db.commit()
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=EVALUATION_RELEASE_REQUIRED)


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
        with bind_llm_usage(
            db=db,
            user_id=current_user.id,
            project_id=project.id if project else None,
            agent_id=agent.id,
            agent_run_id=run.id,
        ):
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


@router.post("/discussion/stream")
async def discussion_stream(
    payload: DiscussionRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    ensure_permission(current_user, "agents:read")
    project = get_project_for_user(payload.project_id, current_user, db, write=True) if payload.project_id else None
    if payload.conversation_id:
        try:
            conversation = get_owned_conversation(db, current_user.id, payload.conversation_id)
        except ConversationAccessError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        if conversation.mode != "TEAM":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该会话不是团队讨论")
        if conversation.project_id != (project.id if project else None):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="讨论所属项目与当前项目不一致")
    try:
        agents = select_discussion_agents(db)
    except DiscussionConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    coordinator = agents[-1]
    run = create_agent_run(
        db,
        request,
        current_user,
        coordinator,
        project,
        payload,
        token_cost=settings.discussion_token_cost,
        description="多 AI 团队讨论",
    )
    return StreamingResponse(
        stream_discussion_events(
            current_user.id,
            payload.message,
            project.id if project else None,
            payload.conversation_id,
            run.id,
            run.billing_transaction_id,
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


@router.post("/messages/{message_id}/feedback", response_model=MessageFeedbackOut)
def submit_message_feedback(
    message_id: int,
    payload: MessageFeedbackRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageFeedback:
    ensure_permission(current_user, "agents:read")
    message = db.get(Message, message_id)
    if not message or message.role != "assistant":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assistant message not found")
    try:
        get_owned_conversation(db, current_user.id, message.conversation_id)
    except ConversationAccessError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    feedback = db.scalar(
        select(MessageFeedback).where(
            MessageFeedback.message_id == message.id,
            MessageFeedback.user_id == current_user.id,
        )
    )
    if feedback is None:
        feedback = MessageFeedback(message_id=message.id, user_id=current_user.id, rating=payload.rating)
        db.add(feedback)
    feedback.rating = payload.rating
    feedback.comment = payload.comment
    record_audit(
        db,
        "agent.message_feedback",
        current_user.id,
        resource_type="message",
        resource_id=message.id,
        details={"rating": payload.rating},
        request=request,
    )
    db.commit()
    db.refresh(feedback)
    return feedback


@router.post("/messages/{message_id}/regenerate", response_model=MessageRegenerateOut)
async def regenerate_message(
    message_id: int,
    payload: MessageRegenerateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageRegenerateOut:
    ensure_permission(current_user, "agents:read")
    original = db.get(Message, message_id)
    if not original or original.role != "assistant":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assistant message not found")
    try:
        conversation = get_owned_conversation(db, current_user.id, original.conversation_id)
    except ConversationAccessError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    agent = db.get(Agent, conversation.agent_id)
    project = get_project_for_user(conversation.project_id, current_user, db, write=True) if conversation.project_id else None
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI employee not found")
    parent = db.get(Message, original.parent_message_id) if original.parent_message_id else None
    message_text = parent.content if parent else "Regenerate assistant response"
    run_payload = ChatRequest(
        request_id=payload.request_id,
        agent_id=agent.id,
        message=message_text,
        project_id=project.id if project else None,
        conversation_id=conversation.id,
    )
    try:
        lease = await acquire_agent_slot(agent.id, agent.concurrency_limit)
    except AgentBusyError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    try:
        run = create_agent_run(db, request, current_user, agent, project, run_payload)
        with bind_llm_usage(
            db=db,
            user_id=current_user.id,
            project_id=project.id if project else None,
            agent_id=agent.id,
            agent_run_id=run.id,
        ):
            regenerated = await regenerate_assistant_message(db, current_user, original)
        complete_agent_run(db, run.id, conversation.id)
    except Exception as exc:
        db.rollback()
        if "run" in locals():
            fail_agent_run(db, run.id, run.billing_transaction_id, str(exc))
        raise
    finally:
        await lease.release()
    db.refresh(current_user)
    return MessageRegenerateOut(message=regenerated, token_balance=current_user.ai_token_balance)
