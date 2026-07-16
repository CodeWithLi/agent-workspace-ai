import json
import logging
from collections.abc import AsyncGenerator

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.registry import DEFAULT_AGENTS
from app.agent.router import RouteDecision, route_agent
from app.core.llm import get_llm
from app.core.audit import record_audit
from app.core.database import SessionLocal
from app.core.memory import get_user_preferences, load_project_memory, save_project_memory
from app.models import Agent, AgentAction, AgentTool, Conversation, Message, Project, User
from app.rag.service import search_knowledge
from app.tools.registry import allowed_tools_for_role, run_tool


logger = logging.getLogger(__name__)


class ConversationAccessError(LookupError):
    pass


TOOL_TRIGGERS: dict[str, tuple[str, ...]] = {
    "knowledge_search": ("知识库", "检索文档", "搜索文档", "查资料", "引用来源", "根据文档", "rag"),
    "requirement_create": ("创建需求", "生成prd", "写prd", "需求分析", "产品需求"),
    "task_create": ("创建任务", "生成任务", "任务拆解", "拆解任务", "建立任务"),
    "report_generate": ("生成报告", "项目报告", "日报", "周报", "风险报告", "进度报告"),
    "architecture_generate": ("架构设计", "设计架构", "数据库设计", "接口设计", "技术选型", "部署方案"),
    "testcase_create": ("测试用例", "测试方案", "边界测试", "接口测试"),
    "meeting_summary": ("会议纪要", "总结会议", "会议总结", "提取待办"),
    "notification_create": ("生成通知", "写通知", "写邮件", "生成公告", "提醒"),
    "analytics_report": ("健康度", "效率分析", "运营分析", "风险预测", "分析项目"),
}


def ensure_default_agents(db: Session) -> None:
    for item in DEFAULT_AGENTS:
        agent = db.scalar(select(Agent).where(Agent.role == item["role"]))
        if agent is None:
            agent = Agent(**item)
            db.add(agent)
            db.flush()

        existing_tools = {tool.name for tool in agent.tool_links}
        for tool_name in [name.strip() for name in item["tools"].split(",") if name.strip()]:
            if tool_name not in existing_tools:
                db.add(AgentTool(agent_id=agent.id, name=tool_name, enabled=True))
    db.commit()


def select_agent_for_message(db: Session, message: str, preferred_agent_id: int | None = None) -> RouteDecision:
    return route_agent(db, message, preferred_agent_id)


def get_owned_conversation(db: Session, user_id: int, conversation_id: int) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if not conversation or conversation.user_id != user_id:
        raise ConversationAccessError("会话不存在")
    return conversation


def build_system_prompt(db: Session, user: User, agent: Agent, project: Project | None = None) -> str:
    project_context = ""
    if project:
        memories = load_project_memory(db, user.id, project.id)
        memory_text = "\n".join(f"- {item.key}: {item.value[:300]}" for item in memories)
        project_context = (
            f"\n当前项目：{project.name}\n项目描述：{project.description}\n项目成员：{project.members or '未设置'}"
            f"\n项目 Memory：\n{memory_text or '暂无'}"
        )
    preferences = get_user_preferences(user.id)
    return (
        f"{agent.system_prompt}\n"
        f"角色说明：{agent.description}\n"
        f"可用工具：{agent.tools or '无'}\n"
        f"用户偏好：{json.dumps(preferences, ensure_ascii=False)}"
        f"{project_context}\n"
        "请输出 Markdown。工具结果是可信上下文，但不要声称执行未出现于工具结果中的操作。"
        "不要编造知识库引用；信息不足时明确指出缺失信息。"
    )


def _tool_is_requested(name: str, message: str) -> bool:
    return any(trigger in message.lower() for trigger in TOOL_TRIGGERS.get(name, ()))


def _available_tools(user: User, agent: Agent) -> set[str]:
    role = agent.role.value if hasattr(agent.role, "value") else str(agent.role)
    user_role = user.role.value if hasattr(user.role, "value") else str(user.role)
    hard_allowlist = allowed_tools_for_role(role)
    links = list(agent.tool_links)
    if links:
        configured = {
            tool.name
            for tool in links
            if tool.enabled and user_role in {item.strip() for item in tool.allowed_roles.split(",")}
        }
    else:
        configured = {name.strip() for name in agent.tools.split(",") if name.strip()}
    available = configured & hard_allowlist
    if not agent.knowledge_access:
        available.discard("knowledge_search")
    return available


async def infer_tool_calls(
    db: Session,
    user: User,
    agent: Agent,
    project: Project | None,
    message: str,
    conversation_id: int | None = None,
) -> list[dict]:
    calls: list[dict] = []
    tool_names = _available_tools(user, agent)

    if project and "context_search" in tool_names:
        output = run_tool("context_search", db=db, project_id=project.id)
        calls.append({"name": "context_search", "input": {"project_id": project.id}, "output": output})

    for name in sorted(tool_names - {"context_search"}):
        if not _tool_is_requested(name, message):
            continue
        if name == "knowledge_search":
            answer, results = await search_knowledge(db, user, message, project.id if project else None, top_k=5)
            calls.append({"name": name, "input": {"query": message}, "output": {"answer": answer, "results": results}})
        elif name == "task_create" and project:
            if agent.human_approval_required:
                input_json = json.dumps({"project_id": project.id}, sort_keys=True)
                action = db.scalar(
                    select(AgentAction).where(
                        AgentAction.user_id == user.id,
                        AgentAction.project_id == project.id,
                        AgentAction.agent_id == agent.id,
                        AgentAction.conversation_id == conversation_id,
                        AgentAction.tool_name == name,
                        AgentAction.input_json == input_json,
                        AgentAction.status == "PENDING",
                    )
                )
                if action is None:
                    action = AgentAction(
                        user_id=user.id,
                        project_id=project.id,
                        agent_id=agent.id,
                        conversation_id=conversation_id,
                        tool_name=name,
                        input_json=input_json,
                        status="PENDING",
                    )
                    db.add(action)
                    db.flush()
                output = {"status": "PENDING_APPROVAL", "action_id": action.id}
            else:
                tasks = run_tool(name, db=db, project_id=project.id)
                output = [{"id": task.id, "title": task.title, "status": task.status.value} for task in tasks]
            calls.append({"name": name, "input": {"project_id": project.id}, "output": output})
        elif name == "requirement_create":
            calls.append({"name": name, "input": {"user_input": message}, "output": run_tool(name, user_input=message)})
        elif name == "architecture_generate":
            calls.append({"name": name, "input": {"user_input": message}, "output": run_tool(name, user_input=message)})
        elif name == "testcase_create":
            calls.append({"name": name, "input": {"user_input": message}, "output": run_tool(name, user_input=message)})
        elif name == "meeting_summary":
            calls.append({"name": name, "input": {"transcript": message}, "output": run_tool(name, transcript=message)})
        elif name == "notification_create":
            calls.append({"name": name, "input": {"title": "通知草稿"}, "output": run_tool(name, title="通知草稿", content=message)})
        elif name == "analytics_report" and project:
            calls.append({"name": name, "input": {"project_id": project.id}, "output": run_tool(name, db=db, project_id=project.id)})
        elif name == "report_generate":
            sections = {"用户请求": message, "项目上下文": calls[0]["output"] if calls and calls[0]["name"] == "context_search" else {}}
            calls.append({"name": name, "input": {"sections": list(sections)}, "output": run_tool(name, sections=sections)})
    return calls[:4]


def _short_term_context(messages: list[Message], budget: int = 12000) -> str:
    selected: list[str] = []
    used = 0
    for item in messages:
        line = f"{item.role}: {item.content[:2000]}"
        if used + len(line) > budget:
            break
        selected.append(line)
        used += len(line)
    return "\n".join(reversed(selected))


async def _prepare_chat(
    db: Session,
    user: User,
    agent: Agent,
    message: str,
    project: Project | None,
    conversation_id: int | None,
    route_reason: str,
) -> tuple[Conversation, str, str, str, list[dict]]:
    conversation = get_owned_conversation(db, user.id, conversation_id) if conversation_id else None
    if conversation:
        if conversation.agent_id != agent.id:
            raise ConversationAccessError("切换 AI 员工需要开启新会话")
        if conversation.project_id != (project.id if project else None):
            raise ConversationAccessError("会话所属项目与当前项目不一致")
    else:
        conversation = Conversation(
            title=message[:60],
            project_id=project.id if project else None,
            agent_id=agent.id,
            user_id=user.id,
        )
        db.add(conversation)
        db.flush()

    recent_messages = list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.desc())
            .limit(20)
        )
    )
    context = _short_term_context(recent_messages)
    tool_calls = await infer_tool_calls(db, user, agent, project, message, conversation.id)
    tool_context = json.dumps(tool_calls, ensure_ascii=False, default=str)
    thinking = (
        f"路由到：{agent.name}。{route_reason or '用户明确选择'}。"
        f"读取短期上下文 {len(recent_messages)} 条，按意图执行工具 {len(tool_calls)} 个。"
    )
    db.add(Message(conversation_id=conversation.id, role="user", content=message))
    db.flush()
    prompt = f"历史上下文：\n{context}\n\n工具结果：\n{tool_context}\n\n用户输入：\n{message}"
    return conversation, build_system_prompt(db, user, agent, project), prompt, thinking, tool_calls


def _finalize_chat(
    db: Session,
    user: User,
    agent: Agent,
    project: Project | None,
    conversation: Conversation,
    answer: str,
    thinking: str,
    tool_calls: list[dict],
) -> None:
    db.add(
        Message(
            conversation_id=conversation.id,
            role="assistant",
            content=answer,
            thinking=thinking,
            tool_calls=json.dumps(tool_calls, ensure_ascii=False, default=str),
        )
    )
    if agent.memory_enable and project:
        save_project_memory(
            db,
            user_id=user.id,
            project_id=project.id,
            agent_id=agent.id,
            key=f"{agent.role.value}_latest",
            value=answer[:1000],
        )
    if tool_calls:
        record_audit(
            db,
            "agent.tools_execute",
            user.id,
            project.id if project else None,
            "conversation",
            conversation.id,
            {"agent_id": agent.id, "tools": [call["name"] for call in tool_calls]},
        )
    db.commit()


async def chat_with_agent(
    db: Session,
    user: User,
    agent: Agent,
    message: str,
    project: Project | None,
    conversation_id: int | None,
    route_reason: str = "",
) -> tuple[Conversation, str, str, list[dict], list[Message]]:
    conversation, system_prompt, prompt, thinking, tool_calls = await _prepare_chat(
        db, user, agent, message, project, conversation_id, route_reason
    )
    answer = await get_llm().chat(system_prompt, prompt, agent.model)
    _finalize_chat(db, user, agent, project, conversation, answer, thinking, tool_calls)
    messages = list(db.scalars(select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at)))
    return conversation, answer, thinking, tool_calls, messages


async def stream_chat_events(
    user_id: int,
    agent_id: int,
    message: str,
    project_id: int | None,
    conversation_id: int | None,
    route_reason: str,
) -> AsyncGenerator[str, None]:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        agent = db.get(Agent, agent_id)
        project = db.get(Project, project_id) if project_id else None
        if not user or not user.is_active or not agent or (project_id and not project):
            payload = {"content": "会话上下文已失效，请刷新后重试。"}
            yield f"event: error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            return

        conversation, system_prompt, prompt, thinking, tool_calls = await _prepare_chat(
            db, user, agent, message, project, conversation_id, route_reason
        )
        yield f"event: thinking\ndata: {json.dumps({'content': thinking}, ensure_ascii=False)}\n\n"
        for call in tool_calls:
            yield f"event: tool\ndata: {json.dumps(call, ensure_ascii=False, default=str)}\n\n"

        parts: list[str] = []
        try:
            async for token in get_llm().stream(system_prompt, prompt, agent.model):
                parts.append(token)
                yield f"event: token\ndata: {json.dumps({'content': token}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            db.rollback()
            logger.exception("Streaming chat failed: %s", exc)
            payload = {"content": "模型服务暂时不可用，请稍后重试。"}
            yield f"event: error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            return

        answer = "".join(parts)
        _finalize_chat(db, user, agent, project, conversation, answer, thinking, tool_calls)
        done = {"conversation_id": conversation.id, "agent_id": agent.id, "agent_name": agent.name}
        yield f"event: done\ndata: {json.dumps(done, ensure_ascii=False)}\n\n"
