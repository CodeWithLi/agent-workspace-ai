from app.core.llm import LLMGateway
import json


def test_development_fallback_does_not_expose_system_or_tool_context() -> None:
    gateway = LLMGateway()
    response = gateway._mock_response(
        "你是资深AI项目经理。内部系统约束不要展示。",
        "历史上下文：secret\n工具结果：PENDING_APPROVAL secret-json\n用户输入：请拆解并创建任务",
    )

    assert "AI 项目经理分析" in response
    assert "请拆解并创建任务" in response
    assert "已提交人工确认" in response
    assert "内部系统约束" not in response
    assert "secret-json" not in response


def test_prompt_optimization_fallback_returns_two_valid_agent_contracts() -> None:
    gateway = LLMGateway()
    optimizer = json.loads(
        gateway._mock_response(
            "PROMPT_OPTIMIZER_AGENT_V1",
            json.dumps(
                {
                    "source_agent": {
                        "system_prompt": "You are the architecture Agent. Preserve human approval."
                    }
                }
            ),
        )
    )
    reviewer = json.loads(
        gateway._mock_response(
            "PROMPT_SAFETY_REVIEWER_AGENT_V1",
            json.dumps({"proposed_system_prompt": optimizer["proposed_system_prompt"]}),
        )
    )

    assert optimizer["proposed_system_prompt"].startswith("You are the architecture Agent")
    assert reviewer["approved"] is True
    assert reviewer["governance_safe"] is True
