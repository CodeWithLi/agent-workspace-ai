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
    load_evaluation_corpus,
    structural_candidates,
)


DEFAULT_CASES_PATH = ROOT / "backend" / "tests" / "rag_eval_cases.json"
DEFAULT_DOCUMENTS_DIRECTORY = ROOT / "backend" / "tests" / "rag_eval_documents"


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare legacy and structural RAG chunking")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--documents-dir", type=Path, default=DEFAULT_DOCUMENTS_DIRECTORY)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--include-chonkie", action="store_true")
    parser.add_argument("--min-score", type=float, default=0.2)
    parser.add_argument("--embedding-cost-per-million", type=float, default=0.0)
    parser.add_argument("--min-query-coverage", type=float, default=0.15)
    parser.add_argument("--enforce-gates", action="store_true")
    parser.add_argument("--min-context-precision-gain", type=float, default=0.01)
    parser.add_argument("--max-p95-retrieval-ms", type=float, default=100.0)
    parser.add_argument("--min-heading-metadata-coverage", type=float, default=0.99)
    args = parser.parse_args()

    try:
        cases, documents, dataset = load_evaluation_corpus(args.cases, args.documents_dir)
    except ValueError as exc:
        parser.error(str(exc))
    chunker = StructuralChunker()
    strategies = [
        ("legacy-characters-900-140", lambda: legacy_candidates(documents, chunker.tokens.count)),
        (f"structural-parent-child-v{chunker.version}", lambda: structural_candidates(documents, chunker)),
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
    baseline, structural = reports[:2]
    gate_failures = []
    for metric in ("recall_at_k", "mrr", "ndcg_at_k", "citation_target_accuracy", "refusal_accuracy"):
        if structural[metric] < baseline[metric]:
            gate_failures.append(f"{metric} regressed: {structural[metric]} < {baseline[metric]}")
    precision_gain = structural["context_precision_at_k"] - baseline["context_precision_at_k"]
    if precision_gain < args.min_context_precision_gain:
        gate_failures.append(
            f"context precision gain {precision_gain:.4f} < {args.min_context_precision_gain:.4f}"
        )
    if structural["heading_metadata_coverage"] < args.min_heading_metadata_coverage:
        gate_failures.append(
            "heading metadata coverage is below the mixed-format threshold: "
            f"{structural['heading_metadata_coverage']:.4f} < "
            f"{args.min_heading_metadata_coverage:.4f}"
        )
    if structural["max_chunk_tokens"] > chunker.config.child_tokens:
        gate_failures.append("structural chunk exceeds the child token budget")
    index_token_overhead_budget = len(documents) * chunker.config.overlap_tokens
    index_token_limit = baseline["index_tokens"] + index_token_overhead_budget
    if structural["index_tokens"] > index_token_limit:
        gate_failures.append(
            "structural index token count exceeds the configured overlap budget: "
            f"{structural['index_tokens']} > {index_token_limit}"
        )
    if structural["p95_retrieval_ms"] > args.max_p95_retrieval_ms:
        gate_failures.append(
            f"p95 retrieval {structural['p95_retrieval_ms']:.3f}ms > {args.max_p95_retrieval_ms:.3f}ms"
        )
    payload = {
        "dataset": dataset,
        "top_k": args.top_k,
        "min_score": args.min_score,
        "min_query_coverage": args.min_query_coverage,
        "reports": reports,
        "gates": {
            "passed": not gate_failures,
            "failures": gate_failures,
            "min_context_precision_gain": args.min_context_precision_gain,
            "max_p95_retrieval_ms": args.max_p95_retrieval_ms,
            "min_heading_metadata_coverage": args.min_heading_metadata_coverage,
            "max_index_token_overhead": index_token_overhead_budget,
        },
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 1 if args.enforce_gates and gate_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
