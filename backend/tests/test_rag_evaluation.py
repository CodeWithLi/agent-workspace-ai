from pathlib import Path

from app.rag.chunking import StructuralChunker
import pytest

from app.rag.evaluation import (
    deterministic_citation_score,
    evaluate_candidates,
    legacy_candidates,
    load_cases,
    load_documents,
    parse_answer_judge_response,
    structural_candidates,
)


def test_repository_rag_chunking_evaluation_is_reproducible() -> None:
    cases = load_cases(Path(__file__).with_name("rag_eval_cases.json"))
    documents = load_documents(cases, Path(__file__).with_name("rag_eval_documents"))
    chunker = StructuralChunker()

    legacy = evaluate_candidates(
        "legacy",
        documents,
        legacy_candidates(documents, chunker.tokens.count),
        cases,
    )
    structural = evaluate_candidates(
        "structural",
        documents,
        structural_candidates(documents, chunker),
        cases,
    )

    assert legacy.cases == structural.cases == 8
    assert legacy.evidence_containment == structural.evidence_containment == 1.0
    assert legacy.heading_metadata_coverage == 0.0
    assert structural.heading_metadata_coverage == 1.0
    assert structural.max_chunk_tokens <= chunker.config.child_tokens
    assert structural.recall_at_k >= legacy.recall_at_k
    assert structural.mrr >= legacy.mrr
    assert structural.ndcg_at_k >= legacy.ndcg_at_k
    assert structural.context_precision_at_k > legacy.context_precision_at_k
    assert structural.citation_target_accuracy >= legacy.citation_target_accuracy
    assert 0 <= structural.refusal_accuracy <= 1
    assert 0 < structural.index_tokens <= legacy.index_tokens


def test_answer_judge_parser_and_citation_gate_are_strict() -> None:
    judged = parse_answer_judge_response(
        '```json\n{"faithfulness":0.95,"answer_relevance":0.9,"citation_correctness":1,'
        '"refusal_correct":true,"reason":"Grounded in the cited recovery procedure."}\n```'
    )

    assert judged.faithfulness == 0.95
    assert judged.refusal_correct is True
    assert deterministic_citation_score(
        "Use PITR [runbook.md#chunk-2]",
        {"runbook.md#chunk-2"},
        answerable=True,
    ) == 1.0
    assert deterministic_citation_score(
        "Use PITR [unknown.md#chunk-9]",
        {"runbook.md#chunk-2"},
        answerable=True,
    ) == 0.0
    assert deterministic_citation_score("上下文不足。", set(), answerable=False) == 1.0

    with pytest.raises(ValueError, match="valid JSON"):
        parse_answer_judge_response("not-json")
    with pytest.raises(ValueError, match=r"within \[0, 1\]"):
        parse_answer_judge_response(
            '{"faithfulness":1.1,"answer_relevance":1,"citation_correctness":1,'
            '"refusal_correct":false,"reason":"invalid"}'
        )
