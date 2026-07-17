from pathlib import Path

from app.rag.chunking import StructuralChunker
from app.rag.evaluation import evaluate_candidates, legacy_candidates, load_cases, structural_candidates


ROOT = Path(__file__).resolve().parents[2]


def test_repository_rag_chunking_evaluation_is_reproducible() -> None:
    cases = load_cases(Path(__file__).with_name("rag_eval_cases.json"))
    filenames = sorted({case.document for case in cases if case.document is not None})
    documents = {filename: (ROOT / "docs" / filename).read_bytes() for filename in filenames}
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
    assert 0 <= structural.context_precision_at_k <= 1
    assert 0 <= structural.refusal_accuracy <= 1
    assert structural.index_tokens > 0
