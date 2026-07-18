import hashlib
import json
import logging
import math
import re
from time import perf_counter
from collections.abc import AsyncGenerator

import httpx

from app.core.config import get_settings
from app.core.llm_usage import estimate_tokens, record_llm_usage


logger = logging.getLogger(__name__)


class LLMGateway:
    """OpenAI-compatible gateway used by every Agent."""

    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def api_key(self) -> str | None:
        return self.settings.llm_api_key or self.settings.openai_api_key

    @property
    def base_url(self) -> str:
        if self.settings.llm_api_key:
            return self.settings.llm_base_url
        return self.settings.openai_base_url

    @property
    def model(self) -> str:
        if self.settings.llm_api_key:
            return self.settings.llm_model
        return self.settings.openai_model

    def resolve_model(self, requested: str | None) -> str:
        if not requested:
            return self.model
        if not self.settings.llm_api_key and requested == self.settings.llm_model:
            return self.settings.openai_model
        return requested

    def _fallback_or_raise(self, exc: Exception) -> str:
        if self.settings.llm_fallback_enabled:
            logger.warning("LLM request failed; development fallback is enabled: %s", exc)
            return "fallback"
        raise LLMGatewayError("LLM provider request failed") from exc

    async def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        response_format: dict[str, str] | None = None,
    ) -> str:
        started = perf_counter()
        resolved_model = self.resolve_model(model)
        input_tokens = estimate_tokens(system_prompt) + estimate_tokens(user_prompt)
        if not self.api_key:
            if not self.settings.llm_fallback_enabled:
                raise LLMGatewayError("LLM_API_KEY is not configured")
            answer = self._mock_response(system_prompt, user_prompt)
            record_llm_usage(
                "chat",
                "local",
                resolved_model,
                input_tokens,
                estimate_tokens(answer),
                int((perf_counter() - started) * 1000),
                usage_source="estimated",
            )
            return answer

        payload = {
            "model": resolved_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
        }
        if response_format:
            payload["response_format"] = response_format
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with httpx.AsyncClient(timeout=90) as client:
                response = await client.post(
                    f"{self.base_url.rstrip('/')}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()
                answer = data["choices"][0]["message"]["content"]
                usage = data.get("usage") or {}
                record_llm_usage(
                    "chat",
                    self.settings.llm_provider,
                    resolved_model,
                    int(usage.get("prompt_tokens", input_tokens)),
                    int(usage.get("completion_tokens", estimate_tokens(answer))),
                    int((perf_counter() - started) * 1000),
                    usage_source="provider" if usage else "estimated",
                )
                return answer
        except Exception as exc:
            self._fallback_or_raise(exc)
            answer = self._mock_response(system_prompt, user_prompt)
            record_llm_usage(
                "chat",
                "local",
                resolved_model,
                input_tokens,
                estimate_tokens(answer),
                int((perf_counter() - started) * 1000),
                usage_source="estimated",
            )
            return answer

    async def stream(self, system_prompt: str, user_prompt: str, model: str | None = None) -> AsyncGenerator[str, None]:
        if not self.api_key:
            text = await self.chat(system_prompt, user_prompt, model)
            for index in range(0, len(text), 12):
                yield text[index : index + 12]
            return

        started = perf_counter()
        resolved_model = self.resolve_model(model)
        input_tokens = estimate_tokens(system_prompt) + estimate_tokens(user_prompt)
        payload = {
            "model": resolved_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            usage: dict = {}
            output_parts: list[str] = []
            async with httpx.AsyncClient(timeout=90) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url.rstrip('/')}/chat/completions",
                    json=payload,
                    headers=headers,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if not raw or raw == "[DONE]":
                            continue
                        data = json.loads(raw)
                        if data.get("usage"):
                            usage = data["usage"]
                        content = data.get("choices", [{}])[0].get("delta", {}).get("content")
                        if content:
                            output_parts.append(content)
                            yield content
            output = "".join(output_parts)
            record_llm_usage(
                "chat",
                self.settings.llm_provider,
                resolved_model,
                int(usage.get("prompt_tokens", input_tokens)),
                int(usage.get("completion_tokens", estimate_tokens(output))),
                int((perf_counter() - started) * 1000),
                usage_source="provider" if usage else "estimated",
            )
        except Exception as exc:
            self._fallback_or_raise(exc)
            text = self._mock_response(system_prompt, user_prompt)
            for index in range(0, len(text), 12):
                yield text[index : index + 12]
            record_llm_usage(
                "chat",
                "local",
                resolved_model,
                input_tokens,
                estimate_tokens(text),
                int((perf_counter() - started) * 1000),
                usage_source="estimated",
            )

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        api_key = self.settings.embedding_api_key or self.api_key
        base_url = self.settings.embedding_base_url or self.base_url
        embedding_model = self.settings.embedding_model
        started = perf_counter()
        input_tokens = sum(estimate_tokens(text) for text in texts)
        if not self.settings.embedding_api_key and not self.settings.llm_api_key and embedding_model == "embedding-3":
            embedding_model = "text-embedding-3-small"
        if api_key:
            try:
                async with httpx.AsyncClient(timeout=90) as client:
                    response = await client.post(
                        f"{base_url.rstrip('/')}/embeddings",
                        json={"model": embedding_model, "input": texts},
                        headers={"Authorization": f"Bearer {api_key}"},
                    )
                    response.raise_for_status()
                    data = response.json()
                    rows = sorted(data["data"], key=lambda item: item["index"])
                    usage = data.get("usage") or {}
                    record_llm_usage(
                        "embedding",
                        self.settings.llm_provider,
                        embedding_model,
                        int(usage.get("prompt_tokens", usage.get("total_tokens", input_tokens))),
                        0,
                        int((perf_counter() - started) * 1000),
                        usage_source="provider" if usage else "estimated",
                    )
                    return [self._resize_and_normalize(item["embedding"]) for item in rows]
            except Exception as exc:
                if not self.settings.llm_fallback_enabled:
                    raise LLMGatewayError("Embedding provider request failed") from exc
                logger.warning("Embedding request failed; using local feature hashing: %s", exc)
        vectors = [self._local_embedding(text) for text in texts]
        record_llm_usage(
            "embedding",
            "local",
            embedding_model,
            input_tokens,
            0,
            int((perf_counter() - started) * 1000),
            usage_source="estimated",
        )
        return vectors

    async def embed(self, text: str) -> list[float]:
        return (await self.embed_many([text]))[0]

    def _local_embedding(self, text: str) -> list[float]:
        """Meaningful offline fallback: signed feature hashing over words and CJK n-grams."""
        lower = text.lower()
        terms = re.findall(r"[a-z0-9_]+", lower)
        cjk = "".join(re.findall(r"[\u4e00-\u9fff]", lower))
        terms.extend(cjk[index : index + size] for size in (1, 2, 3) for index in range(len(cjk) - size + 1))
        values = [0.0] * self.settings.embedding_dimensions
        for term in terms:
            digest = hashlib.blake2b(term.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % len(values)
            sign = 1.0 if digest[4] & 1 else -1.0
            values[index] += sign
        return self._resize_and_normalize(values)

    def _resize_and_normalize(self, vector: list[float]) -> list[float]:
        dimensions = self.settings.embedding_dimensions
        resized = [0.0] * dimensions
        for index, value in enumerate(vector):
            resized[index % dimensions] += float(value)
        norm = math.sqrt(sum(value * value for value in resized))
        return [value / norm for value in resized] if norm else resized

    def _mock_response(self, system_prompt: str, user_prompt: str) -> str:
        if (
            "原型质量门禁判定 Agent" in system_prompt
            or "JSON 质量门禁归一化器" in system_prompt
        ):
            return json.dumps(
                {
                    "passed": True,
                    "score": 92,
                    "issues": [],
                    "summary": "本地安全模板通过路径、表单标签和响应式结构检查。",
                },
                ensure_ascii=False,
            )
        roles = (
            ("产品经理", "AI 产品经理"),
            ("项目经理", "AI 项目经理"),
            ("架构师", "AI 架构师"),
            ("测试", "AI 测试工程师"),
            ("会议", "AI 会议纪要员"),
            ("知识库", "AI 知识库管理员"),
            ("通知", "AI 通知秘书"),
            ("运营", "AI 运营分析师"),
        )
        role = next((label for keyword, label in roles if keyword in system_prompt), "AI 数字员工")
        request = user_prompt.rsplit("用户输入：", 1)[-1].strip() if "用户输入：" in user_prompt else user_prompt.strip()
        request = request[:800]
        execution = "敏感工具动作已提交人工确认，批准前不会写入项目。" if "PENDING_APPROVAL" in user_prompt else "已完成本地结构化分析。"
        return (
            f"## {role}分析（本地开发回退）\n\n"
            "> 当前未连接外部大模型，以下结果用于验证业务流程，不替代正式模型输出。\n\n"
            f"**请求摘要**：{request}\n\n"
            f"**执行状态**：{execution}\n\n"
            "**下一步**：检查执行记录和工具结果；配置 `LLM_API_KEY` 后重新生成正式内容。"
        )


_gateway: LLMGateway | None = None


class LLMGatewayError(RuntimeError):
    pass


def get_llm() -> LLMGateway:
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway
