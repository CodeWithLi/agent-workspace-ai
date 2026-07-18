from pathlib import Path

from app.rag.chunking import StructuralChunker
import pytest

from app.rag.evaluation import (
    RetrievalCase,
    answer_judge_prompt,
    compare_end_to_end_reports,
    deterministic_answer_assertion_score,
    deterministic_citation_score,
    evaluate_candidates,
    first_relevant_rank,
    legacy_candidates,
    load_cases,
    load_documents,
    judge_context_tokens,
    parse_answer_judge_response,
    structural_candidates,
)


def test_judge_prompt_keeps_every_citation_within_model_context() -> None:
    case = RetrievalCase(
        name="bounded-judge",
        query="Which evidence is authoritative?",
        document="DOC.md",
        evidence="authoritative evidence",
    )
    rows = [
        {
            "citation": f"DOC.md#chunk-{index}",
            "content": f"authoritative evidence {index} " + "long context " * 1200,
        }
        for index in range(5)
    ]

    prompt = answer_judge_prompt(case, "The evidence is authoritative. [DOC.md#chunk-4]", rows)

    assert all(f"[DOC.md#chunk-{index}]" in prompt for index in range(5))
    assert "Reference evidence: authoritative evidence" in prompt
    assert judge_context_tokens.count(prompt) < 3000


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
    assert legacy.context_precision_at_k == 0.1639
    assert structural.context_precision_at_k == 0.2278
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
    assert (
        deterministic_citation_score(
            "Use PITR [runbook.md#chunk-2]",
            {"runbook.md#chunk-2"},
            answerable=True,
        )
        == 1.0
    )
    assert (
        deterministic_citation_score(
            "Use PITR [unknown.md#chunk-9]",
            {"runbook.md#chunk-2"},
            answerable=True,
        )
        == 0.0
    )
    assert deterministic_citation_score("上下文不足。", set(), answerable=False) == 1.0

    with pytest.raises(ValueError, match="valid JSON"):
        parse_answer_judge_response("not-json")
    with pytest.raises(ValueError, match=r"within \[0, 1\]"):
        parse_answer_judge_response(
            '{"faithfulness":1.1,"answer_relevance":1,"citation_correctness":1,'
            '"refusal_correct":false,"reason":"invalid"}'
        )


def test_repeated_chunks_count_as_one_evidence_target() -> None:
    assert first_relevant_rank([False, True, True]) == 2
    assert first_relevant_rank([False, False]) is None


def test_deterministic_answer_assertions_detect_opposite_claims() -> None:
    required = (("拒绝启动", "不会启动", "refuse to start"),)
    forbidden = ("系统会继续运行",)

    assert deterministic_answer_assertion_score("配置无效时应用会拒绝启动。", required, forbidden) == 1.0
    assert deterministic_answer_assertion_score("配置无效时系统不会启动。", required, forbidden) == 1.0
    assert deterministic_answer_assertion_score("配置无效时系统会继续运行。", required, forbidden) == 0.0
    assert (
        deterministic_answer_assertion_score(
            "knowledge_access 为 false 时会移除 knowledge_search。",
            (("knowledge_access",), ("false",), ("knowledge_search",), ("移除", "remove")),
            (),
        )
        == 1.0
    )


def test_end_to_end_ab_gate_requires_significant_gain_without_regression() -> None:
    baseline_metrics = {
        "recall_at_k": 0.7,
        "mrr": 0.7,
        "ndcg_at_k": 0.7,
        "context_precision_at_k": 0.4,
        "citation_target_accuracy": 0.9,
        "faithfulness": 0.9,
        "answer_relevance": 0.9,
        "deterministic_citation_validity": 1.0,
        "judge_citation_correctness": 0.95,
        "answer_assertion_accuracy": 1.0,
        "refusal_accuracy": 1.0,
    }
    candidate_metrics = {**baseline_metrics, "recall_at_k": 0.76}

    passed = compare_end_to_end_reports(
        {"metrics": baseline_metrics, "evaluation_errors": []},
        {"metrics": candidate_metrics, "evaluation_errors": []},
    )
    regressed = compare_end_to_end_reports(
        {"metrics": baseline_metrics, "evaluation_errors": []},
        {
            "metrics": {**candidate_metrics, "citation_target_accuracy": 0.7},
            "evaluation_errors": [],
        },
    )

    assert passed["passed"] is True
    assert passed["deltas"]["recall_at_k"] == 0.06
    assert regressed["passed"] is False
    assert any("citation_target_accuracy regressed" in failure for failure in regressed["failures"])
