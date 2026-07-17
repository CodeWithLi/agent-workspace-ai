from typing import Any

from app.prototypes.schemas import PrototypeScreen, PrototypeSpecification


def _screen_components(screen: PrototypeScreen):
    return [component for section in screen.sections for component in section.components]


def build_prototype_task_blueprints(specification: PrototypeSpecification) -> list[dict[str, str]]:
    blueprints = []
    for screen in specification.screens:
        components = _screen_components(screen)
        required_labels = [
            component.label
            for component in components
            if component.required and component.type in {"input", "textarea", "select"}
        ]
        action_labels = [
            component.label or component.text or component.id
            for component in components
            if component.action
        ]
        acceptance = []
        if required_labels:
            acceptance.append(f"必填字段：{'、'.join(required_labels)}")
        if action_labels:
            acceptance.append(f"可交互操作：{'、'.join(action_labels)}")
        blueprints.append(
            {
                "screen_id": screen.id,
                "title": f"实现原型界面：{screen.name}"[:200],
                "description": "\n".join(
                    [
                        screen.description or f"实现 {screen.name} 的结构和交互。",
                        *acceptance,
                        "验收时需同时覆盖桌面和移动端。",
                    ]
                ),
                "priority": "HIGH" if screen.id == specification.start_screen_id else "MEDIUM",
            }
        )
    return blueprints


def build_prototype_test_case_blueprints(
    specification: PrototypeSpecification,
) -> list[dict[str, Any]]:
    screen_names = {screen.id: screen.name for screen in specification.screens}
    cases: list[dict[str, Any]] = []
    for screen in specification.screens:
        components = _screen_components(screen)
        required = [
            component
            for component in components
            if component.required and component.type in {"input", "textarea", "select"}
        ]
        cases.append(
            {
                "screen_id": screen.id,
                "case_key": f"screen:{screen.id}:render",
                "title": f"渲染并完成 {screen.name} 主路径",
                "preconditions": f"已打开 {screen.name}，原型版本数据加载成功。",
                "steps": [
                    "检查标题、说明、字段和主要操作可见",
                    "完成当前界面的主要交互",
                    "在桌面和移动预览模式下重复检查",
                ],
                "expected_result": f"{screen.name} 内容完整、交互有反馈且两种设备模式无页面级横向溢出。",
                "priority": "HIGH",
            }
        )
        if required:
            labels = "、".join(component.label for component in required)
            cases.append(
                {
                    "screen_id": screen.id,
                    "case_key": f"screen:{screen.id}:required",
                    "title": f"校验 {screen.name} 必填字段",
                    "preconditions": f"已打开 {screen.name}，所有必填字段保持为空。",
                    "steps": ["直接触发主要提交或下一步操作", f"逐项检查必填字段：{labels}"],
                    "expected_result": "流程不会继续，缺失字段显示明确且可访问的错误状态。",
                    "priority": "HIGH",
                }
            )
        for component in components:
            action = component.action
            if not action or action.type != "navigate" or not action.target:
                continue
            target_name = screen_names[action.target]
            cases.append(
                {
                    "screen_id": screen.id,
                    "case_key": f"screen:{screen.id}:navigate:{component.id}",
                    "title": f"从 {screen.name} 跳转到 {target_name}",
                    "preconditions": f"已打开 {screen.name}，所需字段已填写。",
                    "steps": [f"触发“{component.label or component.text or component.id}”操作"],
                    "expected_result": f"当前预览切换到 {target_name}，且浏览器不会离开原型工作室。",
                    "priority": "MEDIUM",
                }
            )
    return cases
