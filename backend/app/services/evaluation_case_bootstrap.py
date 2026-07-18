import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Agent, EvaluationCase
from app.services.evaluation_coverage import CORE_EVALUATION_ROLES, evaluation_suite_coverage


BASELINE_CASE_TEMPLATES: dict[str, dict[str, Any]] = {
    "product_manager": {
        "name": "基础套件 · 可验收需求定义",
        "input_text": "为企业项目定义一项可进入研发的需求，说明目标用户、问题、范围、优先级和可验证验收标准。",
        "expected_keywords": ["目标用户", "范围", "优先级", "验收标准"],
        "forbidden_keywords": ["跳过验收", "无需确认"],
        "rubric": "需求必须区分目标、范围与非目标，给出可测试的验收标准、关键假设和待确认问题。",
    },
    "architect": {
        "name": "基础套件 · 可恢复系统架构",
        "input_text": "为多租户业务设计可审计、可扩展且可回滚的系统架构，说明关键数据流和失败恢复边界。",
        "expected_keywords": ["架构", "审计", "回滚", "数据流"],
        "forbidden_keywords": ["关闭鉴权", "明文密钥", "跳过审计"],
        "rubric": "方案必须说明组件职责、租户与权限边界、关键取舍、可观测性以及失败后的恢复路径。",
    },
    "test_engineer": {
        "name": "基础套件 · 风险驱动测试设计",
        "input_text": "为一次涉及 API、权限和异步任务的发布设计测试方案，覆盖主路径、边界条件与失败恢复。",
        "expected_keywords": ["测试", "边界", "回归", "验收"],
        "forbidden_keywords": ["跳过回归", "仅测主流程"],
        "rubric": "测试方案必须包含风险优先级、前置条件、可复现步骤、预期结果、异常路径和回归范围。",
    },
    "operations_analyst": {
        "name": "基础套件 · 可观测灰度发布",
        "input_text": "制定 AI 功能的灰度发布与运营监控方案，说明核心指标、告警、成本控制和回滚触发条件。",
        "expected_keywords": ["指标", "告警", "灰度", "回滚"],
        "forbidden_keywords": ["全量直接发布", "关闭告警"],
        "rubric": "方案必须给出可量化指标、分阶段流量、异常阈值、责任人和明确的停止或回滚条件。",
    },
    "project_manager": {
        "name": "基础套件 · 可执行交付计划",
        "input_text": "把跨产品、架构、研发、测试和运营的方案转成可执行交付计划，明确依赖、风险与责任。",
        "expected_keywords": ["里程碑", "依赖", "风险", "负责人"],
        "forbidden_keywords": ["尽快完成", "无需负责人"],
        "rubric": "计划必须包含阶段里程碑、前后依赖、负责人、验收证据、风险缓解和延期时的调整路径。",
    },
}


def bootstrap_missing_evaluation_cases(
    db: Session,
    *,
    user_id: int,
) -> tuple[list[EvaluationCase], dict[str, Any]]:
    agents = list(
        db.scalars(
            select(Agent)
            .where(Agent.role.in_(CORE_EVALUATION_ROLES))
            .order_by(Agent.id)
            .with_for_update()
        )
    )
    configured_roles = {
        str(getattr(agent.role, "value", agent.role))
        for agent in agents
    }
    covered_roles = set(
        db.scalars(
            select(EvaluationCase.agent_role)
            .where(
                EvaluationCase.enabled.is_(True),
                EvaluationCase.agent_role.in_(configured_roles),
            )
            .distinct()
        )
    )
    missing_roles = [
        role
        for role in CORE_EVALUATION_ROLES
        if role in configured_roles and role not in covered_roles
    ]
    created: list[EvaluationCase] = []
    for role in missing_roles:
        template = BASELINE_CASE_TEMPLATES[role]
        item = EvaluationCase(
            name=template["name"],
            agent_role=role,
            input_text=template["input_text"],
            expected_keywords_json=json.dumps(template["expected_keywords"], ensure_ascii=False),
            forbidden_keywords_json=json.dumps(template["forbidden_keywords"], ensure_ascii=False),
            rubric=template["rubric"],
            minimum_score=0.8,
            weight=1.0,
            enabled=True,
            created_by_user_id=user_id,
        )
        db.add(item)
        created.append(item)
    db.flush()
    return created, evaluation_suite_coverage(db)
