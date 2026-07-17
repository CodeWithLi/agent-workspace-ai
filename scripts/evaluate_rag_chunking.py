import argparse
import json
import sys
from time import perf_counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.rag.chunking import StructuralChunker  # noqa: E402
from app.rag.evaluation import (  # noqa: E402
    evaluate_candidates,
    chonkie_sentence_candidates,
    legacy_candidates,
    load_cases,
    structural_candidates,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare legacy and structural RAG chunking")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--include-chonkie", action="store_true")
    parser.add_argument("--min-score", type=float, default=0.2)
    parser.add_argument("--embedding-cost-per-million", type=float, default=0.0)
    parser.add_argument("--min-query-coverage", type=float, default=0.15)
    args = parser.parse_args()

    cases = load_cases(ROOT / "backend" / "tests" / "rag_eval_cases.json")
    filenames = sorted({case.document for case in cases if case.document is not None})
    documents = {filename: (ROOT / "docs" / filename).read_bytes() for filename in filenames}
    chunker = StructuralChunker()
    strategies = [
        ("legacy-characters-900-140", lambda: legacy_candidates(documents, chunker.tokens.count)),
        ("structural-parent-child-v1", lambda: structural_candidates(documents, chunker)),
    ]
    if args.include_chonkie:
        strategies.append(("chonkie-sentence-1.7.0", lambda: chonkie_sentence_candidates(documents)))
    reports = []
    for name, candidate_factory in strategies:
        started = perf_counter()
        candidates = candidate_factory()
        elapsed_ms = round((perf_counter() - started) * 1000, 2)
        report = evaluate_candidates(
            name,
            documents,
            candidates,
            cases,
            top_k=args.top_k,
            min_score=args.min_score,
            embedding_cost_per_million=args.embedding_cost_per_million,
            min_query_coverage=args.min_query_coverage,
        ).to_dict()
        report["chunking_ms"] = elapsed_ms
        reports.append(report)
    payload = {
        "top_k": args.top_k,
        "min_score": args.min_score,
        "min_query_coverage": args.min_query_coverage,
        "reports": reports,
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
