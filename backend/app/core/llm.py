import hashlib
import json
import logging
import math
import re
from collections.abc import AsyncGenerator

import httpx

from app.core.config import get_settings


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

    async def chat(self, system_prompt: str, user_prompt: str, model: str | None = None) -> str:
        if not self.api_key:
            if not self.settings.llm_fallback_enabled:
                raise LLMGatewayError("LLM_API_KEY is not configured")
            return self._mock_response(system_prompt, user_prompt)

        payload = {
            "model": self.resolve_model(model),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
        }
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
                return data["choices"][0]["message"]["content"]
        except Exception as exc:
            self._fallback_or_raise(exc)
            return self._mock_response(system_prompt, user_prompt)

    async def stream(self, system_prompt: str, user_prompt: str, model: str | None = None) -> AsyncGenerator[str, None]:
        if not self.api_key:
            text = await self.chat(system_prompt, user_prompt, model)
            for index in range(0, len(text), 12):
                yield text[index : index + 12]
            return

        payload = {
            "model": self.resolve_model(model),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
            "stream": True,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
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
                        content = data.get("choices", [{}])[0].get("delta", {}).get("content")
                        if content:
                            yield content
        except Exception as exc:
            self._fallback_or_raise(exc)
            text = self._mock_response(system_prompt, user_prompt)
            for index in range(0, len(text), 12):
                yield text[index : index + 12]

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        api_key = self.settings.embedding_api_key or self.api_key
        base_url = self.settings.embedding_base_url or self.base_url
        embedding_model = self.settings.embedding_model
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
                    rows = sorted(response.json()["data"], key=lambda item: item["index"])
                    return [self._resize_and_normalize(item["embedding"]) for item in rows]
            except Exception as exc:
                if not self.settings.llm_fallback_enabled:
                    raise LLMGatewayError("Embedding provider request failed") from exc
                logger.warning("Embedding request failed; using local feature hashing: %s", exc)
        return [self._local_embedding(text) for text in texts]

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
        heading = system_prompt.splitlines()[0] if system_prompt else "AI数字员工"
        return (
            f"## {heading}\n\n"
            f"基于输入：{user_prompt}\n\n"
            "- 结论：已形成可执行的分析结果。\n"
            "- 关键动作：拆解目标、约束、风险、任务和验收标准。\n"
            "- 下一步：进入项目空间沉淀任务、文档和知识库引用。"
        )


_gateway: LLMGateway | None = None


class LLMGatewayError(RuntimeError):
    pass


def get_llm() -> LLMGateway:
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway
