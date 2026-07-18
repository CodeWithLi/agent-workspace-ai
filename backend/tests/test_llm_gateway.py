import json

import httpx
import pytest

from app.core.llm import LLMGateway, LLMGatewayError, LLMRetryableError


def http_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://llm.example.test/chat/completions")
    response = httpx.Response(status_code, request=request)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        return exc
    raise AssertionError("Expected an HTTP status error")


@pytest.mark.parametrize("status_code", [408, 409, 429, 500, 503])
def test_gateway_classifies_transient_provider_statuses_as_retryable(
    status_code: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = LLMGateway()
    monkeypatch.setattr(gateway.settings, "llm_fallback_enabled", False)

    with pytest.raises(LLMRetryableError):
        gateway._fallback_or_raise(http_status_error(status_code))


@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 422])
def test_gateway_keeps_request_and_configuration_statuses_non_retryable(
    status_code: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = LLMGateway()
    monkeypatch.setattr(gateway.settings, "llm_fallback_enabled", False)

    with pytest.raises(LLMGatewayError) as failure:
        gateway._fallback_or_raise(http_status_error(status_code))
    assert not isinstance(failure.value, LLMRetryableError)


def test_gateway_classifies_network_failures_as_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    gateway = LLMGateway()
    monkeypatch.setattr(gateway.settings, "llm_fallback_enabled", False)
    request = httpx.Request("POST", "https://llm.example.test/chat/completions")

    with pytest.raises(LLMRetryableError):
        gateway._fallback_or_raise(httpx.ConnectError("connection reset", request=request))


@pytest.mark.asyncio
async def test_gateway_keeps_missing_api_key_non_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    gateway = LLMGateway()
    monkeypatch.setattr(gateway.settings, "llm_api_key", None)
    monkeypatch.setattr(gateway.settings, "openai_api_key", None)
    monkeypatch.setattr(gateway.settings, "llm_fallback_enabled", False)

    with pytest.raises(LLMGatewayError) as failure:
        await gateway.chat("system", "user")
    assert not isinstance(failure.value, LLMRetryableError)


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
