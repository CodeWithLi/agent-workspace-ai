import json
import logging
from collections.abc import AsyncGenerator

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.concurrency import acquire_agent_slot
from app.agent.service import ConversationAccessError, build_system_prompt, get_owned_conversation
from app.core.audit import record_audit
from app.core.database import SessionLocal
from app.core.llm import get_llm
from app.core.llm_usage import bind_llm_usage
from app.core.memory import save_project_memory
from app.models import Agent, AgentRole, Conversation, Message, Project, User
from app.services.agent_runs import complete_agent_run, fail_agent_run


logger = logging.getLogger(__name__)

DISCUSSION_ROLES: tuple[tuple[AgentRole, str], ...] = (
    (AgentRole.product_manager, "product"),
    (AgentRole.architect, "architecture"),
    (AgentRole.test_engineer, "quality"),
    (AgentRole.operations_analyst, "operations"),
    (AgentRole.project_manager, "final"),
)

STAGE_INSTRUCTIONS = {
    "product": "澄清目标用户、核心场景、范围边界和成功指标，指出需求中仍需确认的假设。",
    "architecture": "回应产品观点，提出技术架构、关键数据流、技术取舍和不可行风险。",
    "quality": "审查前述方案，补充验收标准、边界场景、测试策略和最可能失败的环节。",
    "operations": "从交付、成本、运营和灰度发布角度挑战方案，给出风险缓解建议。",
    "final": "综合全部观点并裁决冲突，输出一份用户可以直接执行的最终方案。",
}


class DiscussionConfigurationError(LookupError):
    pass


def select_discussion_agents(db: Session) -> list[Agent]:
    agents_by_role = {agent.role: agent for agent in db.scalars(select(Agent))}
    missing = [role.value for role, _stage in DISCUSSION_ROLES if role not in agents_by_role]
    if missing:
        raise DiscussionConfigurationError(f"缺少团队讨论角色：{', '.join(missing)}")
    return [agents_by_role[role] for role, _stage in DISCUSSION_ROLES]


def _event(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def _history_transcript(db: Session, conversation_id: int) -> str:
    rows = list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.id.desc())
            .limit(30)
        )
    )
    agent_names = {
        agent.id: agent.name
        for agent in db.scalars(select(Agent).where(Agent.id.in_({row.agent_id for row in rows if row.agent_id})))
    }
    lines = []
    for row in reversed(rows):
        speaker = "用户" if row.role == "user" else agent_names.get(row.agent_id, "AI 员工")
        lines.append(f"{speaker}：{row.content[:3000]}")
    return "\n\n".join(lines)[-24000:]


def _discussion_prompt(
    requirement: str,
    history: str,
    current_round: list[str],
    agent: Agent,
    stage: str,
    index: int,
) -> str:
    transcript = "\n\n".join(current_round) or "尚无本轮发言，你负责提出第一个观点。"
    if stage == "final":
        output_contract = (
            "最终输出必须使用 Markdown，并依次包含：执行摘要、目标与范围、关键决策、产品方案、"
            "技术方案、实施里程碑、测试与验收、发布与运营、风险清单、待确认问题。"
        )
    else:
        output_contract = "输出需包含：回应与判断、你的专业建议、风险或待确认项。控制在 700 字以内。"
    return (
        f"用户原始需求：\n{requirement}\n\n"
        f"既往讨论记录：\n{history or '这是首次讨论。'}\n\n"
        f"本轮已发表观点：\n{transcript[-18000:]}\n\n"
        f"当前发言人：{agent.name}，第 {index + 1}/{len(DISCUSSION_ROLES)} 阶段。\n"
        f"本阶段任务：{STAGE_INSTRUCTIONS[stage]}\n"
        "请明确回应前面观点，不要假装调用工具或声称已经执行项目变更。"
        f"{output_contract}"
    )


async def stream_discussion_events(
    user_id: int,
    message: str,
    project_id: int | None,
    conversation_id: int | None,
    run_id: int,
    billing_transaction_id: int | None,
) -> AsyncGenerator[str, None]:
    try:
        with SessionLocal() as db:
            user = db.get(User, user_id)
            project = db.get(Project, project_id) if project_id else None
            if not user or not user.is_active or (project_id and not project):
                fail_agent_run(db, run_id, billing_transaction_id, "Discussion context is no longer available")
                yield _event("error", {"content": "讨论上下文已失效，请刷新后重试。"})
                return
            try:
                agents = select_discussion_agents(db)
                if conversation_id:
                    conversation = get_owned_conversation(db, user.id, conversation_id)
                    if conversation.mode != "TEAM":
                        raise ConversationAccessError("该会话不是团队讨论")
                    if conversation.project_id != project_id:
                        raise ConversationAccessError("讨论所属项目与当前项目不一致")
                else:
                    conversation = Conversation(
                        title=message[:60],
                        project_id=project_id,
                        agent_id=agents[-1].id,
                        user_id=user.id,
                        mode="TEAM",
                    )
                    db.add(conversation)
                    db.flush()
                history = _history_transcript(db, conversation.id)
                user_message = Message(
                    conversation_id=conversation.id,
                    role="user",
                    stage="request",
                    content=message,
                )
                db.add(user_message)
                db.commit()
                db.refresh(user_message)
            except Exception as exc:
                db.rollback()
                fail_agent_run(db, run_id, billing_transaction_id, str(exc))
                logger.exception("Discussion preparation failed: %s", exc)
                yield _event("error", {"content": str(exc) or "讨论准备失败，请刷新后重试。"})
                return

            yield _event(
                "discussion_start",
                {
                    "conversation_id": conversation.id,
                    "total_steps": len(agents),
                    "participants": [
                        {"agent_id": agent.id, "agent_name": agent.name, "role": agent.role.value}
                        for agent in agents
                    ],
                },
            )
            round_transcript: list[str] = []
            try:
                for index, (agent, (_role, stage)) in enumerate(zip(agents, DISCUSSION_ROLES)):
                    yield _event(
                        "speaker_start",
                        {
                            "agent_id": agent.id,
                            "agent_name": agent.name,
                            "stage": stage,
                            "index": index + 1,
                            "total": len(agents),
                        },
                    )
                    prompt = _discussion_prompt(message, history, round_transcript, agent, stage, index)
                    system_prompt = (
                        f"{build_system_prompt(db, user, agent, project)}\n"
                        "你正在参加一个多 AI 专家评审会。你的发言会被后续 AI 直接阅读，请保持观点具体、可追溯。"
                    )
                    lease = await acquire_agent_slot(agent.id, agent.concurrency_limit)
                    parts: list[str] = []
                    try:
                        with bind_llm_usage(
                            db=db,
                            user_id=user.id,
                            project_id=project_id,
                            agent_id=agent.id,
                            agent_run_id=run_id,
                        ):
                            async for token in get_llm().stream(system_prompt, prompt, agent.model):
                                parts.append(token)
                                yield _event(
                                    "token",
                                    {"agent_id": agent.id, "agent_name": agent.name, "stage": stage, "content": token},
                                )
                    finally:
                        await lease.release()
                    answer = "".join(parts).strip()
                    if not answer:
                        raise RuntimeError(f"{agent.name} 未生成有效内容")
                    assistant_message = Message(
                        conversation_id=conversation.id,
                        agent_id=agent.id,
                        role="assistant",
                        stage=stage,
                        content=answer,
                        thinking=f"团队讨论第 {index + 1} 阶段：{stage}",
                        parent_message_id=user_message.id,
                    )
                    db.add(assistant_message)
                    db.commit()
                    db.refresh(assistant_message)
                    round_transcript.append(f"{agent.name}：{answer}")
                    yield _event(
                        "speaker_done",
                        {
                            "agent_id": agent.id,
                            "agent_name": agent.name,
                            "stage": stage,
                            "message_id": assistant_message.id,
                        },
                    )

                final_message = assistant_message
                if project:
                    save_project_memory(
                        db,
                        user_id=user.id,
                        project_id=project.id,
                        agent_id=agents[-1].id,
                        key="team_discussion_latest",
                        value=final_message.content[:2000],
                    )
                record_audit(
                    db,
                    "agent.discussion_complete",
                    user.id,
                    project_id,
                    "conversation",
                    conversation.id,
                    {"participant_agent_ids": [agent.id for agent in agents], "run_id": run_id},
                )
                db.commit()
                complete_agent_run(db, run_id, conversation.id)
                db.refresh(user)
                yield _event(
                    "done",
                    {
                        "conversation_id": conversation.id,
                        "agent_id": agents[-1].id,
                        "agent_name": agents[-1].name,
                        "message_id": final_message.id,
                        "token_balance": user.ai_token_balance,
                    },
                )
            except Exception as exc:
                db.rollback()
                fail_agent_run(db, run_id, billing_transaction_id, str(exc))
                logger.exception("Team discussion failed: %s", exc)
                yield _event("error", {"content": "团队讨论未完成，费用已退回，请稍后重试。"})
                return
    except BaseException as exc:
        with SessionLocal() as recovery_db:
            fail_agent_run(recovery_db, run_id, billing_transaction_id, str(exc) or type(exc).__name__)
        raise
