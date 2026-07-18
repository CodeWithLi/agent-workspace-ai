import json
import re
from copy import deepcopy
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.concurrency import acquire_agent_slot
from app.core.llm import get_llm
from app.core.llm_usage import bind_llm_usage
from app.models import Agent, AgentRole, ProductPrototype, ProductPrototypeVersion, Requirement, User
from app.prototypes.schemas import PrototypeSpecification, PrototypeVersionOut


MAX_PROTOTYPE_REPAIR_ROUNDS = 2
MAX_REVIEW_CONTRACT_REPAIRS = 1
PROTOTYPE_REVIEW_MIN_SCORE = 80


class PrototypeReviewDecision(BaseModel):
    passed: bool
    score: float = Field(ge=0, le=100)
    issues: list[str] = Field(default_factory=list, max_length=12)
    summary: str = Field(min_length=1, max_length=2000)


def _component(component_id: str, component_type: str, **values: Any) -> dict[str, Any]:
    return {"id": component_id, "type": component_type, **values}


def _auth_invitation_spec(product_name: str, prompt: str) -> PrototypeSpecification:
    summary = (
        "覆盖新访客注册、已注册用户登录、忘记密码重置、个人中心邀请链接获取与邀请记录查询"
        "五条核心路径。注册页支持 invite_code 邀请参数，个人中心承载裂变邀请与效果反馈。"
    )
    screens = [
        {
            "id": "register",
            "name": "注册页",
            "description": "新用户通过手机号、邀请码和密码完成注册。",
            "layout": "auth",
            "sections": [{
                "id": "register-form",
                "title": "创建账号",
                "description": "加入偶像泡泡，关注喜欢的偶像并邀请好友。",
                "width": "narrow",
                "components": [
                    _component("register-heading", "heading", text="手机号注册"),
                    _component("register-phone", "input", label="手机号", placeholder="请输入手机号", required=True),
                    _component("register-code", "input", label="邀请码", placeholder="选填，支持链接自动带入"),
                    _component("register-password", "input", label="设置密码", placeholder="至少 8 位字符", required=True),
                    _component("register-note", "callout", text="注册即表示同意用户协议与隐私政策。"),
                    _component(
                        "register-submit",
                        "button",
                        label="完成注册",
                        variant="primary",
                        action={"type": "navigate", "target": "login", "message": "注册成功"},
                    ),
                    _component(
                        "register-login-link",
                        "link",
                        label="已有账号？返回登录",
                        action={"type": "navigate", "target": "login"},
                    ),
                ],
            }],
        },
        {
            "id": "login",
            "name": "登录页",
            "description": "已注册用户通过手机号和密码登录。",
            "layout": "auth",
            "sections": [{
                "id": "login-form",
                "title": "欢迎回来",
                "description": "登录后继续查看专属内容与邀请进度。",
                "width": "narrow",
                "components": [
                    _component("login-heading", "heading", text="账号登录"),
                    _component("login-phone", "input", label="手机号", placeholder="请输入手机号", required=True),
                    _component("login-password", "input", label="密码", placeholder="请输入密码", required=True),
                    _component(
                        "login-submit",
                        "button",
                        label="登录",
                        variant="primary",
                        action={"type": "navigate", "target": "invite", "message": "登录成功"},
                    ),
                    _component(
                        "login-forgot",
                        "link",
                        label="忘记密码？",
                        action={"type": "navigate", "target": "reset-password"},
                    ),
                    _component(
                        "login-register",
                        "link",
                        label="还没有账号？立即注册",
                        action={"type": "navigate", "target": "register"},
                    ),
                ],
            }],
        },
        {
            "id": "reset-password",
            "name": "忘记密码 / 重置密码页",
            "description": "用户通过手机号验证码完成身份核验并设置新密码。",
            "layout": "auth",
            "sections": [{
                "id": "reset-form",
                "title": "重置密码",
                "description": "验证注册手机号后设置新密码，完成后返回登录。",
                "width": "narrow",
                "components": [
                    _component(
                        "reset-steps",
                        "stepper",
                        steps=["验证手机号", "设置新密码", "重置完成"],
                        active_step=1,
                    ),
                    _component("reset-heading", "heading", text="验证手机号"),
                    _component("reset-phone", "input", label="手机号", placeholder="请输入注册手机号", required=True),
                    _component("reset-code", "input", label="验证码", placeholder="请输入 6 位验证码", required=True),
                    _component(
                        "reset-next",
                        "button",
                        label="下一步",
                        variant="primary",
                        action={"type": "advance_step", "message": "验证通过，进入下一步"},
                    ),
                    _component(
                        "reset-back",
                        "link",
                        label="想起密码了？返回登录",
                        action={"type": "navigate", "target": "login"},
                    ),
                ],
            }],
        },
        {
            "id": "invite",
            "name": "个人中心 - 邀请链接页",
            "description": "生成、复制和分享个人邀请链接并查看转化概况。",
            "layout": "dashboard",
            "sections": [
                {
                    "id": "invite-overview",
                    "title": "邀请好友",
                    "description": "每成功邀请一位好友，可解锁专属内容权益。",
                    "width": "wide",
                    "components": [
                        _component(
                            "invite-stats",
                            "stats",
                            items=[
                                {"label": "累计邀请", "value": "128"},
                                {"label": "本月新增", "value": "24"},
                                {"label": "转化率", "value": "31.6%"},
                            ],
                        ),
                        _component(
                            "invite-link",
                            "callout",
                            label="专属邀请链接",
                            text="https://idol.example/register?invite_code=STAR88",
                        ),
                        _component(
                            "invite-copy",
                            "button",
                            label="复制邀请链接",
                            value="https://idol.example/register?invite_code=STAR88",
                            variant="primary",
                            action={"type": "copy", "message": "邀请链接已复制"},
                        ),
                    ],
                },
                {
                    "id": "invite-recent",
                    "title": "最近邀请",
                    "width": "wide",
                    "components": [
                        _component(
                            "invite-table",
                            "table",
                            columns=["用户", "注册时间", "状态"],
                            items=[
                                {"用户": "泡泡糖", "注册时间": "今天 14:20", "状态": "已注册"},
                                {"用户": "小星球", "注册时间": "昨天 21:08", "状态": "已激活"},
                                {"用户": "银河旅人", "注册时间": "07-15 09:30", "状态": "待注册"},
                            ],
                        ),
                        _component(
                            "invite-records-link",
                            "link",
                            label="查看全部邀请记录",
                            action={"type": "navigate", "target": "invite-records"},
                        ),
                    ],
                },
            ],
        },
        {
            "id": "invite-records",
            "name": "个人中心 - 邀请记录页",
            "description": "按状态查看所有邀请记录和奖励发放情况。",
            "layout": "list",
            "sections": [{
                "id": "records-list",
                "title": "邀请记录",
                "description": "共邀请 128 人，已完成注册 96 人。",
                "width": "wide",
                "components": [
                    _component(
                        "records-tabs",
                        "tabs",
                        options=[
                            {"label": "全部", "value": "all"},
                            {"label": "已注册", "value": "registered"},
                            {"label": "待注册", "value": "pending"},
                        ],
                    ),
                    _component(
                        "records-table",
                        "table",
                        columns=["受邀用户", "来源", "注册时间", "奖励", "状态"],
                        items=[
                            {"受邀用户": "泡泡糖", "来源": "微信", "注册时间": "今天 14:20", "奖励": "专属内容券", "状态": "已发放"},
                            {"受邀用户": "小星球", "来源": "复制链接", "注册时间": "昨天 21:08", "奖励": "积分 100", "状态": "已发放"},
                            {"受邀用户": "银河旅人", "来源": "微信", "注册时间": "-", "奖励": "-", "状态": "待注册"},
                        ],
                    ),
                    _component(
                        "records-back",
                        "button",
                        label="返回邀请概览",
                        variant="secondary",
                        action={"type": "navigate", "target": "invite"},
                    ),
                ],
            }],
        },
    ]
    return PrototypeSpecification.model_validate(
        {
            "product_name": product_name,
            "summary": summary,
            "start_screen_id": "register",
            "theme": {
                "primary": "#1F2937",
                "accent": "#2563EB",
                "background": "#F7F8FA",
                "surface": "#FFFFFF",
                "foreground": "#111827",
                "radius": "soft",
            },
            "screens": screens,
        }
    )


def _generic_product_spec(product_name: str, prompt: str) -> PrototypeSpecification:
    summary = f"围绕“{prompt[:120]}”规划工作台、创建流程、详情与完成反馈四个核心界面。"
    return PrototypeSpecification.model_validate(
        {
            "product_name": product_name,
            "summary": summary,
            "start_screen_id": "overview",
            "theme": {},
            "screens": [
                {
                    "id": "overview",
                    "name": "业务工作台",
                    "description": "聚合核心指标、进行中事项与快捷入口。",
                    "layout": "dashboard",
                    "sections": [{
                        "id": "overview-main",
                        "title": product_name,
                        "description": summary,
                        "width": "wide",
                        "components": [
                            _component("overview-heading", "heading", text="今日工作概览"),
                            _component(
                                "overview-stats",
                                "stats",
                                items=[
                                    {"label": "进行中", "value": "12"},
                                    {"label": "待处理", "value": "5"},
                                    {"label": "完成率", "value": "82%"},
                                ],
                            ),
                            _component(
                                "overview-create",
                                "button",
                                label="创建新事项",
                                variant="primary",
                                action={"type": "navigate", "target": "create"},
                            ),
                            _component(
                                "overview-detail",
                                "link",
                                label="查看最近事项",
                                action={"type": "navigate", "target": "detail"},
                            ),
                        ],
                    }],
                },
                {
                    "id": "create",
                    "name": "创建页",
                    "description": "填写关键信息并提交。",
                    "layout": "form",
                    "sections": [{
                        "id": "create-form",
                        "title": "创建新事项",
                        "description": "填写必要信息，提交后可继续补充详情。",
                        "width": "medium",
                        "components": [
                            _component("create-name", "input", label="名称", placeholder="请输入名称", required=True),
                            _component("create-type", "select", label="类型", options=[{"label": "标准", "value": "standard"}, {"label": "紧急", "value": "urgent"}]),
                            _component("create-description", "textarea", label="描述", placeholder="补充背景和目标"),
                            _component(
                                "create-submit",
                                "button",
                                label="提交",
                                variant="primary",
                                action={"type": "navigate", "target": "complete", "message": "创建成功"},
                            ),
                            _component("create-back", "link", label="返回工作台", action={"type": "navigate", "target": "overview"}),
                        ],
                    }],
                },
                {
                    "id": "detail",
                    "name": "详情页",
                    "description": "查看状态、负责人和活动记录。",
                    "layout": "app",
                    "sections": [{
                        "id": "detail-main",
                        "title": "事项详情",
                        "description": "集中查看当前进展与关键记录。",
                        "width": "wide",
                        "components": [
                            _component("detail-status", "callout", label="当前状态", text="执行中 · 预计明天完成"),
                            _component("detail-list", "list", items=[{"title": "需求已确认", "meta": "产品经理 · 10:20"}, {"title": "方案评审完成", "meta": "架构师 · 11:45"}, {"title": "等待测试验收", "meta": "测试工程师"}]),
                            _component("detail-back", "button", label="返回工作台", variant="secondary", action={"type": "navigate", "target": "overview"}),
                        ],
                    }],
                },
                {
                    "id": "complete",
                    "name": "完成反馈页",
                    "description": "确认操作结果并提供后续路径。",
                    "layout": "auth",
                    "sections": [{
                        "id": "complete-main",
                        "title": "创建成功",
                        "description": "新事项已进入执行队列。",
                        "width": "narrow",
                        "components": [
                            _component("complete-heading", "heading", text="一切准备就绪"),
                            _component("complete-note", "callout", text="你可以继续查看详情，或返回工作台处理其他事项。"),
                            _component("complete-detail", "button", label="查看详情", variant="primary", action={"type": "navigate", "target": "detail"}),
                            _component("complete-home", "link", label="返回工作台", action={"type": "navigate", "target": "overview"}),
                        ],
                    }],
                },
            ],
        }
    )


def build_fallback_spec(title: str, prompt: str) -> PrototypeSpecification:
    normalized = f"{title} {prompt}".lower()
    auth_keywords = ("注册", "登录", "手机号", "邀请", "裂变", "password", "invite", "login")
    if any(keyword in normalized for keyword in auth_keywords):
        return _auth_invitation_spec(title, prompt)
    return _generic_product_spec(title, prompt)


def _json_candidates(text: str) -> list[str]:
    candidates = [text.strip()]
    candidates.extend(re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE))
    first = text.find("{")
    last = text.rfind("}")
    if first >= 0 and last > first:
        candidates.append(text[first : last + 1])
    return list(dict.fromkeys(candidate for candidate in candidates if candidate))


def validate_prototype_specification(
    text: str,
) -> tuple[PrototypeSpecification | None, list[str]]:
    validation_issues: list[str] = []
    for candidate in _json_candidates(text):
        try:
            return PrototypeSpecification.model_validate(json.loads(candidate)), []
        except json.JSONDecodeError:
            validation_issues = ["output: invalid JSON object"]
        except ValidationError as exc:
            validation_issues = [
                f"{'.'.join(str(part) for part in error['loc']) or 'root'}: {error['msg']}"
                for error in exc.errors()[:12]
            ]
    return None, validation_issues or ["output: missing JSON object"]


def extract_prototype_spec(text: str) -> PrototypeSpecification | None:
    spec, _issues = validate_prototype_specification(text)
    return spec


def extract_review_decision(text: str) -> PrototypeReviewDecision | None:
    for candidate in _json_candidates(text):
        try:
            return PrototypeReviewDecision.model_validate(json.loads(candidate))
        except (json.JSONDecodeError, ValidationError):
            continue
    return None


async def _invoke_agent(
    db: Session,
    user: User,
    project_id: int,
    role: AgentRole,
    fallback_prompt: str,
    content: str,
    *,
    json_mode: bool = False,
    contract_only: bool = False,
) -> tuple[str, dict[str, Any]]:
    response_format = {"type": "json_object"} if json_mode else None
    agent = db.scalar(select(Agent).where(Agent.role == role))
    if not agent:
        output = await get_llm().chat(fallback_prompt, content, None, response_format)
        return output, {"role": role.value, "agent_id": None, "name": role.value, "model": "default", "output": output}
    system_prompt = fallback_prompt if contract_only else (
        f"{agent.system_prompt}\n\n"
        "当前任务的输出契约优先于以上通用角色说明。\n"
        f"{fallback_prompt}"
    )
    lease = await acquire_agent_slot(agent.id, agent.concurrency_limit)
    try:
        with bind_llm_usage(
            db=db,
            user_id=user.id,
            project_id=project_id,
            agent_id=agent.id,
        ):
            output = await get_llm().chat(
                system_prompt,
                content,
                agent.model,
                response_format,
            )
    finally:
        await lease.release()
    return output, {
        "role": role.value,
        "agent_id": agent.id,
        "name": agent.name,
        "model": agent.model,
        "prompt_version": agent.current_version,
        "output": output,
    }


def evaluate_specification(spec: PrototypeSpecification) -> dict[str, Any]:
    screen_ids = {screen.id for screen in spec.screens}
    edges: dict[str, set[str]] = {screen.id: set() for screen in spec.screens}
    input_count = 0
    primary_actions = 0
    interactive_count = 0
    screens_without_actions: list[str] = []
    for screen in spec.screens:
        screen_action_count = 0
        for section in screen.sections:
            for component in section.components:
                if component.type in {"input", "textarea", "select"}:
                    input_count += 1
                if component.variant == "primary" and component.action:
                    primary_actions += 1
                if component.action:
                    interactive_count += 1
                    screen_action_count += 1
                    if component.action.type == "navigate" and component.action.target:
                        edges[screen.id].add(component.action.target)
        if screen_action_count == 0:
            screens_without_actions.append(screen.name)
    reachable = {spec.start_screen_id}
    frontier = [spec.start_screen_id]
    while frontier:
        current = frontier.pop()
        for target in edges[current] - reachable:
            reachable.add(target)
            frontier.append(target)
    checks = [
        {"name": "navigation_integrity", "passed": reachable == screen_ids, "detail": f"{len(reachable)}/{len(screen_ids)} screens reachable"},
        {"name": "interactive_paths", "passed": interactive_count >= len(spec.screens), "detail": f"{interactive_count} interactive actions"},
        {
            "name": "screen_action_coverage",
            "passed": not screens_without_actions,
            "detail": "all screens expose an action" if not screens_without_actions else f"missing actions: {', '.join(screens_without_actions)}",
        },
        {"name": "primary_actions", "passed": primary_actions >= max(1, len(spec.screens) - 1), "detail": f"{primary_actions} primary actions"},
        {"name": "visible_form_labels", "passed": True, "detail": f"{input_count} labeled form controls"},
        {"name": "responsive_contract", "passed": all(screen.sections for screen in spec.screens), "detail": "structured sections support desktop and mobile renderers"},
    ]
    score = round(sum(1 for check in checks if check["passed"]) / len(checks) * 100, 1)
    issues = [check["detail"] for check in checks if not check["passed"]]
    return {"score": score, "passed": all(check["passed"] for check in checks), "checks": checks, "issues": issues}


def repair_specification_structure(
    spec: PrototypeSpecification,
) -> tuple[PrototypeSpecification, list[str]]:
    quality = evaluate_specification(spec)
    failed_checks = {check["name"] for check in quality["checks"] if not check["passed"]}
    structural_checks = {
        "navigation_integrity",
        "interactive_paths",
        "screen_action_coverage",
        "primary_actions",
    }
    if not failed_checks or not failed_checks.issubset(structural_checks):
        return spec, []

    payload = spec.model_dump(mode="json")
    screens = payload["screens"]
    start_index = next(
        index for index, screen in enumerate(screens) if screen["id"] == spec.start_screen_id
    )
    ordered_screens = [screens[start_index], *screens[:start_index], *screens[start_index + 1 :]]
    component_ids = {
        component["id"]
        for screen in screens
        for section in screen["sections"]
        for component in section["components"]
    }
    primary_count = sum(
        1
        for screen in screens
        for section in screen["sections"]
        for component in section["components"]
        if component.get("variant") == "primary" and component.get("action")
    )
    required_primary = max(1, len(screens) - 1)
    repairs: list[str] = []

    for index, screen in enumerate(ordered_screens):
        target = ordered_screens[(index + 1) % len(ordered_screens)]
        has_target = any(
            (component.get("action") or {}).get("type") == "navigate"
            and (component.get("action") or {}).get("target") == target["id"]
            for section in screen["sections"]
            for component in section["components"]
        )
        if has_target:
            continue
        base_id = f"{screen['id'][:48]}-flow-{index + 1}"
        component_id = base_id
        suffix = 2
        while component_id in component_ids:
            component_id = f"{base_id[:60]}-{suffix}"
            suffix += 1
        variant = "primary" if primary_count < required_primary else "secondary"
        if variant == "primary":
            primary_count += 1
        screen["sections"][-1]["components"].append(
            {
                "id": component_id,
                "type": "link",
                "label": f"前往{target['name']}",
                "variant": variant,
                "action": {"type": "navigate", "target": target["id"]},
            }
        )
        component_ids.add(component_id)
        repairs.append(f"{screen['name']} -> {target['name']}")

    if primary_count < required_primary:
        for screen in ordered_screens:
            for section in screen["sections"]:
                for component in section["components"]:
                    if primary_count >= required_primary:
                        break
                    if component.get("action") and component.get("variant") != "primary":
                        component["variant"] = "primary"
                        primary_count += 1
                        repairs.append(f"{screen['name']}: 提升主要操作 {component['id']}")
                if primary_count >= required_primary:
                    break
            if primary_count >= required_primary:
                break

    repaired = PrototypeSpecification.model_validate(payload)
    return repaired, repairs


def merge_quality_decision(
    automated: dict[str, Any],
    reviewer: PrototypeReviewDecision | None,
    raw_review: str,
    repair_rounds: int,
    review_contract_repairs: int,
) -> dict[str, Any]:
    reviewer_passed = bool(
        reviewer and reviewer.passed and reviewer.score >= PROTOTYPE_REVIEW_MIN_SCORE
    )
    reviewer_summary = reviewer.summary if reviewer else (
        "测试 Agent 未返回可验证的结构化结论。" + (f" 原始输出：{raw_review[:1200]}" if raw_review.strip() else "")
    )
    checks = [
        *automated["checks"],
        {
            "name": "agent_review",
            "passed": reviewer_passed,
            "detail": reviewer_summary,
        },
    ]
    issues = list(automated["issues"])
    if reviewer:
        for issue in reviewer.issues:
            if issue not in issues:
                issues.append(issue)
        if reviewer.passed and reviewer.score < PROTOTYPE_REVIEW_MIN_SCORE:
            issues.append(
                f"测试 Agent 分数 {reviewer.score:g} 低于 {PROTOTYPE_REVIEW_MIN_SCORE} 分门禁"
            )
    else:
        issues.append("测试 Agent 结构化评审失败")
    reviewer_score = reviewer.score if reviewer else 0.0
    return {
        "score": round(min(float(automated["score"]), reviewer_score), 1),
        "passed": bool(automated["passed"] and reviewer_passed),
        "checks": checks,
        "issues": issues,
        "reviewer_summary": reviewer_summary,
        "reviewer_score": reviewer_score,
        "reviewer_passed": reviewer_passed,
        "repair_rounds": repair_rounds,
        "review_contract_repairs": review_contract_repairs,
    }


async def review_prototype_specification(
    db: Session,
    user: User,
    prototype: ProductPrototype,
    spec: PrototypeSpecification,
    automated: dict[str, Any],
    trace: list[dict[str, Any]],
    repair_rounds: int,
    *,
    fallback: bool = False,
) -> dict[str, Any]:
    review_prompt = (
        "你是原型质量门禁判定 Agent。本步骤不是编写测试策略或测试用例；"
        "禁止输出 test_strategy、functional_test_cases 等额外结构。"
        "检查用户路径、边界状态、表单可访问性、移动端可用性和验收风险。"
        "只输出一个 JSON 对象且只能包含四个字段："
        "{\"passed\":boolean,\"score\":0-100,\"issues\":[string],\"summary\":string}。"
        f"存在任何阻塞验收的问题或分数低于 {PROTOTYPE_REVIEW_MIN_SCORE} 时 passed 必须为 false。"
        "不要输出 Markdown。"
    )
    review_output, review_trace = await _invoke_agent(
        db,
        user,
        prototype.project_id,
        AgentRole.test_engineer,
        review_prompt,
        json.dumps(
            {"specification": spec.model_dump(mode="json"), "automated_quality": automated},
            ensure_ascii=False,
        ),
        json_mode=True,
        contract_only=True,
    )
    review_trace.update(
        {"stage": "quality_review", "round": repair_rounds, "fallback": fallback}
    )
    trace.append(review_trace)
    reviewer = extract_review_decision(review_output)
    contract_repairs = 0

    while reviewer is None and contract_repairs < MAX_REVIEW_CONTRACT_REPAIRS:
        contract_repairs += 1
        normalized_output, normalized_trace = await _invoke_agent(
            db,
            user,
            prototype.project_id,
            AgentRole.test_engineer,
            (
                "你是 JSON 质量门禁归一化器。忽略其他角色说明，不重新编写测试方案。"
                "根据自动检查和上一份评审，只输出一个 JSON 对象且只能包含："
                "{\"passed\":boolean,\"score\":0-100,\"issues\":[string],\"summary\":string}。"
                "不得输出 Markdown、test_strategy、测试用例或其他字段。"
            ),
            json.dumps(
                {
                    "automated_quality": automated,
                    "previous_review": review_output[:12000],
                },
                ensure_ascii=False,
            ),
            json_mode=True,
            contract_only=True,
        )
        normalized_trace.update(
            {
                "stage": "quality_review_repair",
                "round": repair_rounds,
                "contract_repair": contract_repairs,
                "fallback": fallback,
            }
        )
        trace.append(normalized_trace)
        review_output = normalized_output
        reviewer = extract_review_decision(review_output)

    return merge_quality_decision(
        automated,
        reviewer,
        review_output,
        repair_rounds,
        contract_repairs,
    )


async def generate_prototype_version(
    db: Session,
    user: User,
    prototype: ProductPrototype,
    source_prompt: str,
    version: int,
) -> ProductPrototypeVersion:
    requirement = db.get(Requirement, prototype.requirement_id) if prototype.requirement_id else None
    context = {
        "prototype_title": prototype.title,
        "source_prompt": source_prompt,
        "requirement": {
            "title": requirement.title,
            "content": requirement.content,
            "analysis": requirement.analysis,
        } if requirement else None,
    }
    trace: list[dict[str, Any]] = []
    product_brief, product_trace = await _invoke_agent(
        db,
        user,
        prototype.project_id,
        AgentRole.product_manager,
        "你正在生成交互原型。先定义目标用户、核心路径、界面清单、每个界面的成功条件。不要声称已实现代码。",
        json.dumps(context, ensure_ascii=False),
    )
    product_trace.update({"stage": "product_definition", "round": 0})
    trace.append(product_trace)
    schema_guide = {
        "json_schema": PrototypeSpecification.model_json_schema(),
        "component_types": ["heading", "text", "input", "textarea", "select", "button", "link", "stepper", "stats", "callout", "table", "tabs", "list", "divider"],
        "action_types": ["navigate", "toast", "submit", "copy", "advance_step", "back"],
        "layouts": ["auth", "app", "dashboard", "form", "list"],
        "rules": ["return one JSON object only", "all IDs lowercase and unique", "all form controls have labels", "navigate targets must exist", "2-12 screens"],
    }
    architect_output, architect_trace = await _invoke_agent(
        db,
        user,
        prototype.project_id,
        AgentRole.architect,
        (
            "你是交互原型 DSL 编译器。把产品方案转换为安全的结构化原型，只输出一个满足用户消息中"
            " json_schema 的 JSON 对象。顶层必须且只能使用 product_name、summary、start_screen_id、"
            "theme、screens；不要回显 context、product_brief、schema_guide，不输出 HTML、JavaScript、"
            "Markdown 或解释。"
        ),
        json.dumps(
            {"context": context, "product_brief": product_brief, "schema_guide": schema_guide},
            ensure_ascii=False,
        ),
        json_mode=True,
        contract_only=True,
    )
    architect_trace.update({"stage": "architecture", "round": 0})
    trace.append(architect_trace)
    spec: PrototypeSpecification | None = None
    quality: dict[str, Any] | None = None
    best_spec: PrototypeSpecification | None = None
    best_quality: dict[str, Any] | None = None
    repair_rounds = 0
    deterministic_repairs = 0
    generation_mode = "MULTI_AGENT"

    for attempt in range(MAX_PROTOTYPE_REPAIR_ROUNDS + 1):
        spec, validation_issues = validate_prototype_specification(architect_output)
        repair_issues: list[str]
        if spec is None:
            repair_issues = validation_issues
        else:
            automated = evaluate_specification(spec)
            if not automated["passed"]:
                repaired_spec, structural_repairs = repair_specification_structure(spec)
                if structural_repairs:
                    repaired_quality = evaluate_specification(repaired_spec)
                    if repaired_quality["score"] > automated["score"]:
                        spec = repaired_spec
                        automated = repaired_quality
                        deterministic_repairs += 1
                        trace.append(
                            {
                                "role": "quality_gate",
                                "agent_id": None,
                                "name": "确定性原型修复器",
                                "model": "local",
                                "output": json.dumps(
                                    {
                                        "repairs": structural_repairs,
                                        "quality": automated,
                                    },
                                    ensure_ascii=False,
                                ),
                                "stage": "deterministic_repair",
                                "round": attempt,
                            }
                        )
            quality = await review_prototype_specification(
                db,
                user,
                prototype,
                spec,
                automated,
                trace,
                repair_rounds,
            )
            quality["deterministic_repairs"] = deterministic_repairs
            if best_quality is None or quality["score"] > best_quality["score"]:
                best_spec = spec.model_copy(deep=True)
                best_quality = deepcopy(quality)
            if quality["passed"]:
                break
            repair_issues = quality["issues"]

        if attempt >= MAX_PROTOTYPE_REPAIR_ROUNDS:
            break
        repair_rounds += 1
        previous_spec = spec.model_dump(mode="json") if spec else architect_output[:20000]
        architect_output, repair_trace = await _invoke_agent(
            db,
            user,
            prototype.project_id,
            AgentRole.architect,
            (
                "你是交互架构返修 Agent。根据确定性门禁和测试 Agent 反馈修复原型。"
                "保留已正确的产品需求，返回完整且可独立校验的原型 DSL JSON；"
                "顶层必须且只能使用 product_name、summary、start_screen_id、theme、screens；"
                "严格满足用户消息中的 json_schema，不要输出 answer、context、HTML、JavaScript、"
                "Markdown 或解释。"
            ),
            json.dumps(
                {
                    "context": context,
                    "product_brief": product_brief,
                    "schema_guide": schema_guide,
                    "repair_round": repair_rounds,
                    "quality_issues": repair_issues,
                    "previous_specification": previous_spec,
                },
                ensure_ascii=False,
            ),
            json_mode=True,
            contract_only=True,
        )
        repair_trace.update({"stage": "architecture_repair", "round": repair_rounds})
        trace.append(repair_trace)

    if best_spec is not None and (
        spec is None
        or quality is None
        or (
            not quality["passed"]
            and best_quality is not None
            and best_quality["score"] >= quality["score"]
        )
    ):
        spec = best_spec
        quality = best_quality
        if quality is not None:
            quality["repair_rounds"] = repair_rounds

    if spec is None:
        spec = build_fallback_spec(prototype.title, source_prompt)
        generation_mode = "MULTI_AGENT_TEMPLATE_FALLBACK"
        automated = evaluate_specification(spec)
        quality = await review_prototype_specification(
            db,
            user,
            prototype,
            spec,
            automated,
            trace,
            repair_rounds,
            fallback=True,
        )
        quality["deterministic_repairs"] = deterministic_repairs
    elif quality and quality["passed"] and (repair_rounds or deterministic_repairs):
        generation_mode = "MULTI_AGENT_REPAIRED"
    elif not quality or not quality["passed"]:
        generation_mode = "MULTI_AGENT_REVIEW_REQUIRED"

    if quality is None:
        raise RuntimeError("Prototype generation completed without a quality decision")
    item = ProductPrototypeVersion(
        prototype_id=prototype.id,
        version=version,
        source_prompt=source_prompt,
        specification_json=spec.model_dump_json(),
        agent_trace_json=json.dumps(trace, ensure_ascii=False),
        quality_json=json.dumps(quality, ensure_ascii=False),
        generation_mode=generation_mode,
        created_by_user_id=user.id,
    )
    db.add(item)
    db.flush()
    return item


def version_out(item: ProductPrototypeVersion) -> PrototypeVersionOut:
    return PrototypeVersionOut(
        id=item.id,
        version=item.version,
        source_prompt=item.source_prompt,
        specification=PrototypeSpecification.model_validate_json(item.specification_json),
        agent_trace=json.loads(item.agent_trace_json or "[]"),
        quality=json.loads(item.quality_json or "{}"),
        generation_mode=item.generation_mode,
        created_by_user_id=item.created_by_user_id,
        created_at=item.created_at,
    )
