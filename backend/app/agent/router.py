from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Agent, AgentRole


@dataclass(frozen=True)
class RouteDecision:
    agent: Agent
    confidence: float
    reason: str


class AgentRoutingError(LookupError):
    pass


INTENT_KEYWORDS: dict[str, dict[str, float]] = {
    AgentRole.product_manager.value: {"需求分析": 0.45, "prd": 0.45, "用户故事": 0.35, "产品规划": 0.35, "验收标准": 0.3, "需求": 0.14, "产品": 0.12},
    AgentRole.project_manager.value: {"任务拆解": 0.45, "项目计划": 0.4, "项目经理": 0.55, "排期": 0.35, "里程碑": 0.35, "进度": 0.25, "日报": 0.3, "周报": 0.3, "风险": 0.15},
    AgentRole.architect.value: {"架构师": 0.55, "系统架构": 0.45, "数据库设计": 0.45, "接口设计": 0.45, "技术选型": 0.4, "部署方案": 0.35, "数据库": 0.24, "api": 0.22, "架构": 0.3},
    AgentRole.test_engineer.value: {"测试工程师": 0.55, "测试用例": 0.45, "测试方案": 0.4, "边界测试": 0.4, "接口测试": 0.4, "质量保证": 0.35, "测试": 0.22},
    AgentRole.meeting_summarizer.value: {"会议纪要员": 0.55, "会议纪要": 0.5, "会议总结": 0.45, "行动项": 0.35, "会议": 0.18, "纪要": 0.3},
    AgentRole.knowledge_admin.value: {"知识库管理员": 0.55, "知识库": 0.42, "知识检索": 0.4, "文档检索": 0.4, "引用来源": 0.35, "rag": 0.42, "搜索文档": 0.35},
    AgentRole.notification_secretary.value: {"通知秘书": 0.55, "发送通知": 0.45, "写邮件": 0.45, "邮件通知": 0.4, "公告": 0.32, "提醒": 0.3},
    AgentRole.operations_analyst.value: {"运营分析师": 0.55, "项目健康度": 0.45, "效率分析": 0.42, "风险预测": 0.4, "运营分析": 0.42, "优化建议": 0.3},
}

ROLE_ALIASES: dict[str, tuple[str, ...]] = {
    AgentRole.product_manager.value: ("产品经理", "产品agent", "pm agent"),
    AgentRole.project_manager.value: ("项目经理", "项目管理agent"),
    AgentRole.architect.value: ("架构师", "架构agent"),
    AgentRole.test_engineer.value: ("测试工程师", "测试agent", "qa agent"),
    AgentRole.meeting_summarizer.value: ("会议纪要员", "会议agent"),
    AgentRole.knowledge_admin.value: ("知识库管理员", "知识库agent"),
    AgentRole.notification_secretary.value: ("通知秘书", "通知agent"),
    AgentRole.operations_analyst.value: ("运营分析师", "运营agent"),
}


def route_agent(db: Session, message: str, preferred_agent_id: int | None = None) -> RouteDecision:
    if preferred_agent_id:
        agent = db.get(Agent, preferred_agent_id)
        if not agent:
            raise AgentRoutingError("指定的 AI 员工不存在")
        return RouteDecision(agent=agent, confidence=1.0, reason="用户已明确选择该 AI 员工")

    text = message.lower()
    agents = {agent.role.value if hasattr(agent.role, "value") else str(agent.role): agent for agent in db.scalars(select(Agent))}
    if not agents:
        raise AgentRoutingError("系统尚未配置 AI 员工")

    for role, aliases in ROLE_ALIASES.items():
        hit = next((alias for alias in aliases if alias.lower() in text), None)
        if hit and role in agents:
            return RouteDecision(agent=agents[role], confidence=0.99, reason=f"明确提及角色：{hit}")

    scores: list[tuple[str, float, list[str]]] = []
    for role, keywords in INTENT_KEYWORDS.items():
        hits = [keyword for keyword in keywords if keyword.lower() in text]
        if hits:
            score = min(0.96, 0.3 + sum(keywords[keyword] for keyword in hits))
            scores.append((role, score, hits))

    if not scores:
        fallback = agents.get(AgentRole.product_manager.value) or next(iter(agents.values()))
        return RouteDecision(agent=fallback, confidence=0.35, reason="未识别到明确意图，默认由AI产品经理澄清需求")

    ranked = sorted(scores, key=lambda item: item[1], reverse=True)
    role, confidence, hits = ranked[0]
    if len(ranked) > 1 and confidence - ranked[1][1] < 0.08:
        confidence = min(confidence, 0.58)
    agent = agents.get(role) or next(iter(agents.values()))
    return RouteDecision(agent=agent, confidence=confidence, reason=f"命中关键词：{', '.join(hits[:5])}")
