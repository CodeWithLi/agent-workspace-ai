import json

import pytest

from app.rag.local_evaluation_models import LocalOpenModelSuite
from app.rag.service import rewrite_query


class FakeEmbeddingModel:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def encode(self, texts: list[str], **_kwargs):
        self.calls.append(texts)
        return [[1.0, 0.0] for _text in texts]


class FakeCrossEncoder:
    def predict(self, _pairs, **_kwargs):
        return [3.0, -3.0]


class FakeLlama:
    def __init__(self) -> None:
        self.requests: list[dict] = []

    def create_chat_completion(self, **request):
        self.requests.append(request)
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "faithfulness": 1.0,
                                "answer_relevance": 1.0,
                                "citation_correctness": 1.0,
                                "refusal_correct": True,
                                "reason": "supported",
                            }
                        )
                    }
                }
            ]
        }


@pytest.mark.asyncio
async def test_local_open_models_use_e5_query_and_passage_prefixes() -> None:
    suite = LocalOpenModelSuite()
    model = FakeEmbeddingModel()
    suite._embedding_model = model

    passages = await suite.embed_many(["alpha"])
    queries = await suite.embed_queries(["beta"])

    assert passages == [[1.0, 0.0]]
    assert queries == [[1.0, 0.0]]
    assert model.calls == [["passage: alpha"], ["query: beta"]]


@pytest.mark.asyncio
async def test_local_open_models_apply_real_reranker_scores() -> None:
    suite = LocalOpenModelSuite()
    suite._reranker = FakeCrossEncoder()
    rows = [
        {"content": "relevant", "score": 0.2},
        {"content": "irrelevant", "score": 0.9},
    ]

    ranked = await suite.rerank("query", rows)

    assert [row["content"] for row in ranked] == ["relevant", "irrelevant"]
    assert all(row["rerank_fallback"] is False for row in ranked)
    assert ranked[0]["rerank_score"] > ranked[1]["rerank_score"]


@pytest.mark.asyncio
async def test_local_open_models_constrain_judge_to_required_json_schema() -> None:
    suite = LocalOpenModelSuite()
    model = FakeLlama()
    suite._llm = model

    result = await suite.chat(
        "You are a strict RAG evaluation judge. Output JSON only.",
        "Evaluate this answer.",
    )

    assert json.loads(result)["citation_correctness"] == 1.0
    schema = model.requests[0]["response_format"]["schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "faithfulness",
        "answer_relevance",
        "citation_correctness",
        "refusal_correct",
        "reason",
    }


@pytest.mark.asyncio
async def test_rewrite_query_uses_injected_gateway(monkeypatch) -> None:
    class Gateway:
        async def chat(self, *_args, **_kwargs) -> str:
            return '{"queries":["restore drill","backup exercise"]}'

    monkeypatch.setattr("app.rag.service.settings.rag_query_rewrite_enabled", True)
    monkeypatch.setattr("app.rag.service.settings.rag_query_rewrite_max_variants", 3)

    assert await rewrite_query("recovery test", gateway=Gateway()) == [
        "recovery test",
        "restore drill",
        "backup exercise",
    ]


def test_local_open_model_revisions_are_pinned() -> None:
    revisions = LocalOpenModelSuite().model_revisions

    assert all(len(model["revision"]) == 40 for model in revisions.values())
