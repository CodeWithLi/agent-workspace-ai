import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.router import AgentRoutingError, route_agent
from app.agent.service import ensure_default_agents
from app.models import Agent, AgentRole


@pytest.mark.parametrize(
    ("message", "expected_role"),
    [
        ("请架构师设计数据库和 API 接口", AgentRole.architect),
        ("分析校园二手平台的用户需求和用户故事", AgentRole.product_manager),
        ("把会议内容总结成会议纪要并提取行动项", AgentRole.meeting_summarizer),
        ("生成接口测试用例和边界测试方案", AgentRole.test_engineer),
        ("从知识库检索文档并给出引用来源", AgentRole.knowledge_admin),
    ],
)
def test_routes_to_expected_agent(db: Session, message: str, expected_role: AgentRole) -> None:
    ensure_default_agents(db)
    decision = route_agent(db, message)
    assert decision.agent.role == expected_role
    assert decision.confidence >= 0.58


def test_explicit_selection_has_priority(db: Session) -> None:
    ensure_default_agents(db)
    product = db.scalar(select(Agent).where(Agent.role == AgentRole.product_manager))
    assert product is not None
    decision = route_agent(db, "请设计系统架构", preferred_agent_id=product.id)
    assert decision.agent.id == product.id
    assert decision.confidence == 1.0


def test_invalid_explicit_agent_does_not_silently_fallback(db: Session) -> None:
    ensure_default_agents(db)
    with pytest.raises(AgentRoutingError):
        route_agent(db, "分析需求", preferred_agent_id=99999)
