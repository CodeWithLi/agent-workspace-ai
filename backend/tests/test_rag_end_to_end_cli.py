import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from app.rag.types import DocumentElement, ParsedDocument


ROOT = Path(__file__).resolve().parents[2]


def load_evaluation_script() -> ModuleType:
    path = ROOT / "scripts" / "evaluate_rag_end_to_end.py"
    spec = importlib.util.spec_from_file_location("evaluate_rag_end_to_end", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_evaluation_config_fingerprint_ignores_strategy_but_locks_model_stack() -> None:
    module = load_evaluation_script()
    args = SimpleNamespace(
        provider="local-open-models",
        judge_model=None,
        top_k=5,
        min_score=0.2,
        chunk_strategy="legacy",
    )
    settings = SimpleNamespace(
        embedding_model="fallback-embedding",
        reranker_model="fallback-reranker",
        rag_query_rewrite_enabled=True,
        rag_query_rewrite_max_variants=3,
        reranker_candidate_limit=40,
        rag_min_query_coverage=0.15,
        rag_dense_override_score=0.72,
        rag_context_max_tokens=4000,
        rag_multi_vector_enabled=False,
    )
    gateway = SimpleNamespace(
        model="answer-v1",
        embedding_model_name="embedding-v1",
        reranker_model_name="reranker-v1",
        judge_model_name="judge-v1",
        model_revisions={"answer": {"revision": "abc"}},
    )
    keyword_args = {
        "reranker_enabled": True,
        "embedding_dimensions": 384,
        "rerank_min_score": 0.08,
        "rerank_min_query_coverage": 0.08,
        "rerank_relevance_threshold": 0.12,
    }

    baseline = module.build_evaluation_config(args, settings, gateway, **keyword_args)
    args.chunk_strategy = "semantic"
    settings.rag_multi_vector_enabled = True
    candidate = module.build_evaluation_config(args, settings, gateway, **keyword_args)
    changed_model = module.build_evaluation_config(
        args,
        settings,
        SimpleNamespace(**{**vars(gateway), "model": "answer-v2"}),
        **keyword_args,
    )

    assert baseline == candidate
    assert len(baseline["sha256"]) == 64
    assert baseline["runtime"]["python"]
    assert set(baseline["runtime"]["packages"]) == {
        "chonkie",
        "llama-cpp-python",
        "sentence-transformers",
        "torch",
    }
    assert changed_model["sha256"] != baseline["sha256"]


@pytest.mark.asyncio
async def test_candidate_rows_use_production_parser_and_fingerprint_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_evaluation_script()
    calls: list[tuple[str, bytes]] = []

    async def parse(filename: str, data: bytes) -> ParsedDocument:
        calls.append((filename, data))
        content = "OCR recovery policy requires approval."
        return ParsedDocument(
            filename=filename,
            content_hash="a" * 64,
            text=content,
            elements=(
                DocumentElement(
                    stable_id="element-1",
                    element_index=0,
                    kind="paragraph",
                    content=content,
                    page_start=1,
                    page_end=1,
                    char_end=len(content),
                    metadata={"bbox": [1.0, 2.0, 3.0, 4.0]},
                ),
            ),
            parser_name="docling-serve",
            parser_version="test-json-v1",
            metadata={"page_count": 1},
        )

    monkeypatch.setattr(module, "parse_document_with_backend", parse)
    settings = SimpleNamespace(
        rag_child_chunk_tokens=400,
        rag_parent_chunk_tokens=1200,
        rag_chunk_overlap_tokens=100,
        rag_min_chunk_tokens=30,
        rag_parser_backend="docling",
        rag_parser_fallback_enabled=False,
        rag_max_document_chars=2_000_000,
        rag_max_pdf_pages=500,
        rag_max_elements=50_000,
        rag_max_chunks=10_000,
    )
    documents = {"scans/recovery.pdf": b"pdf bytes"}

    rows, semantic_tokens, parsing = await module.candidate_rows(
        documents,
        "legacy",
        settings,
        gateway=object(),
    )
    _, _, repeated_parsing = await module.candidate_rows(
        documents,
        "legacy",
        settings,
        gateway=object(),
    )

    assert calls == [("scans/recovery.pdf", b"pdf bytes")] * 2
    assert semantic_tokens == 0
    assert rows[0]["content"] == "OCR recovery policy requires approval."
    assert parsing == repeated_parsing
    assert parsing["backend"] == "docling"
    assert parsing["fallback_enabled"] is False
    assert len(parsing["parsed_corpus_sha256"]) == 64
    assert len(parsing["documents"]) == 1
    parsed_document = parsing["documents"][0]
    assert parsed_document["name"] == "scans/recovery.pdf"
    assert parsed_document["parser_name"] == "docling-serve"
    assert parsed_document["parser_version"] == "test-json-v1"
    assert parsed_document["element_count"] == 1
    assert parsed_document["page_count"] == 1
    assert parsed_document["fallback_from"] is None
    assert len(parsed_document["parsed_sha256"]) == 64
