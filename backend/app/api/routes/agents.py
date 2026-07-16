from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.router import AgentRoutingError, RouteDecision
from app.agent.service import (
    ConversationAccessError,
    chat_with_agent,
    get_owned_conversation,
    select_agent_for_message,
    stream_chat_events,
)
from app.api.deps import get_current_user, require_admin
from app.api.routes.projects import get_project_for_user
from app.core.database import get_db
from app.core.audit import record_audit
from app.models import Agent, AgentTool, Conversation, Message, Project, User
from app.schemas import (
    AgentOut,
    AgentRouteResponse,
    AgentToolOut,
    AgentToolUpdate,
    ChatRequest,
    ChatResponse,
    ConversationOut,
    MessageOut,
)

router = APIRouter()


@router.get("", response_model=list[AgentOut])
def list_agents(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[Agent]:
    return list(db.scalars(select(Agent).order_by(Agent.id)))


@router.get("/{agent_id}/tools", response_model=list[AgentToolOut])
def list_agent_tools(
    agent_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[AgentTool]:
    return list(db.scalars(select(AgentTool).where(AgentTool.agent_id == agent_id).order_by(AgentTool.name)))


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
    tool.enabled = payload.enabled
    tool.allowed_roles = payload.allowed_roles
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


def resolve_decision(payload: ChatRequest, user: User, db: Session) -> RouteDecision:
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


def resolve_project(payload: ChatRequest, user: User, db: Session) -> Project | None:
    project = get_project_for_user(payload.project_id, user, db, write=True) if payload.project_id else None
    if payload.conversation_id:
        conversation = get_owned_conversation(db, user.id, payload.conversation_id)
        if conversation.project_id != (project.id if project else None):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="会话所属项目与当前项目不一致")
    return project


@router.post("/route", response_model=AgentRouteResponse)
def route(
    payload: ChatRequest,
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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChatResponse:
    decision = resolve_decision(payload, current_user, db)
    agent = decision.agent
    project = resolve_project(payload, current_user, db)
    try:
        conversation, answer, thinking, tool_calls, messages = await chat_with_agent(
            db, current_user, agent, payload.message, project, payload.conversation_id, decision.reason
        )
    except ConversationAccessError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    decision = resolve_decision(payload, current_user, db)
    agent = decision.agent
    project = resolve_project(payload, current_user, db)
    return StreamingResponse(
        stream_chat_events(db, current_user, agent, payload.message, project, payload.conversation_id, decision.reason),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(
    project_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Conversation]:
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
    try:
        conversation = get_owned_conversation(db, current_user.id, conversation_id)
    except ConversationAccessError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return list(db.scalars(select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at)))
