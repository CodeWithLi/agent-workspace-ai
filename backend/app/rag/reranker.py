from __future__ import annotations

import logging
from time import perf_counter
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.llm_usage import estimate_tokens, record_llm_usage
from app.core.metrics import RAG_RERANK_REQUESTS


logger = logging.getLogger(__name__)
settings = get_settings()


class CrossEncoderReranker:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.transport = transport

    async def rerank(self, query: str, rows: list[dict]) -> list[dict]:
        if not settings.reranker_enabled or not rows:
            RAG_RERANK_REQUESTS.labels("disabled").inc()
            return rows
        if not settings.reranker_base_url:
            logger.warning("Reranker enabled without RERANKER_BASE_URL; using fusion ranking")
            return self._fallback(rows)
        endpoint = settings.reranker_base_url.rstrip("/")
        if not endpoint.endswith("/rerank"):
            endpoint += "/rerank"
        headers = {"Content-Type": "application/json"}
        if settings.reranker_api_key:
            headers["Authorization"] = f"Bearer {settings.reranker_api_key}"
        candidates = rows[: settings.reranker_candidate_limit]
        started = perf_counter()
        try:
            async with httpx.AsyncClient(
                timeout=settings.reranker_timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.post(
                    endpoint,
                    headers=headers,
                    json={
                        "model": settings.reranker_model,
                        "query": query,
                        "documents": [row["content"] for row in candidates],
                        "top_n": len(candidates),
                        "return_documents": False,
                    },
                )
                response.raise_for_status()
                payload: Any = response.json()
            results = payload.get("results") if isinstance(payload, dict) else payload
            if not isinstance(results, list):
                raise ValueError("Reranker response does not contain a results list")
            scores: dict[int, float] = {}
            for item in results:
                if not isinstance(item, dict) or not isinstance(item.get("index"), int):
                    continue
                index = item["index"]
                raw_score = item.get("relevance_score", item.get("score"))
                if 0 <= index < len(candidates) and isinstance(raw_score, (int, float)):
                    scores[index] = max(0.0, min(1.0, float(raw_score)))
            if not scores:
                raise ValueError("Reranker response contains no usable scores")
            for index, row in enumerate(candidates):
                row["rerank_score"] = round(scores.get(index, 0.0), 4)
                row["score"] = round(0.35 * row["score"] + 0.65 * row["rerank_score"], 4)
                row["rerank_fallback"] = False
            record_llm_usage(
                "rerank",
                "external",
                settings.reranker_model,
                estimate_tokens(query) + sum(estimate_tokens(row["content"]) for row in candidates),
                0,
                int((perf_counter() - started) * 1000),
                usage_source="estimated",
            )
            RAG_RERANK_REQUESTS.labels("success").inc()
            return sorted(candidates, key=lambda row: row["score"], reverse=True) + rows[len(candidates) :]
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            logger.warning("Reranker request failed; using fusion ranking: %s", exc)
            RAG_RERANK_REQUESTS.labels("fallback").inc()
            return self._fallback(rows)

    async def healthcheck(self) -> None:
        if not settings.reranker_enabled:
            raise RuntimeError("Reranker is disabled")
        rows = await self.rerank("Connection test", [{"content": "Connection test", "score": 1.0}])
        if not rows or rows[0].get("rerank_fallback") is not False:
            raise RuntimeError("Reranker connection failed")

    @staticmethod
    def _fallback(rows: list[dict]) -> list[dict]:
        for row in rows:
            row["rerank_fallback"] = True
        return rows


reranker = CrossEncoderReranker()
