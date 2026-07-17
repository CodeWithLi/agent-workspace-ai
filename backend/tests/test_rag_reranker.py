import httpx
import pytest

from app.rag.reranker import CrossEncoderReranker


@pytest.mark.asyncio
async def test_cross_encoder_reranker_reorders_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/rerank"
        assert request.headers["Authorization"] == "Bearer reranker-secret"
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 1, "relevance_score": 0.95},
                    {"index": 0, "relevance_score": 0.1},
                ]
            },
        )

    monkeypatch.setattr("app.rag.reranker.settings.reranker_enabled", True)
    monkeypatch.setattr("app.rag.reranker.settings.reranker_base_url", "https://reranker.example/v1")
    monkeypatch.setattr("app.rag.reranker.settings.reranker_api_key", "reranker-secret")
    monkeypatch.setattr("app.rag.reranker.settings.reranker_candidate_limit", 40)
    rows = [
        {"content": "irrelevant", "score": 0.8},
        {"content": "relevant", "score": 0.4},
    ]

    reranker = CrossEncoderReranker(httpx.MockTransport(handler))
    ranked = await reranker.rerank("query", rows)

    assert [row["content"] for row in ranked] == ["relevant", "irrelevant"]
    assert ranked[0]["rerank_score"] == 0.95
    assert ranked[0]["rerank_fallback"] is False
    await reranker.healthcheck()


@pytest.mark.asyncio
async def test_cross_encoder_reranker_falls_back_on_invalid_response(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={"unexpected": []}))
    monkeypatch.setattr("app.rag.reranker.settings.reranker_enabled", True)
    monkeypatch.setattr("app.rag.reranker.settings.reranker_base_url", "https://reranker.example")
    rows = [{"content": "first", "score": 0.8}, {"content": "second", "score": 0.4}]

    ranked = await CrossEncoderReranker(transport).rerank("query", rows)

    assert ranked == rows
    assert all(row["rerank_fallback"] is True for row in ranked)
