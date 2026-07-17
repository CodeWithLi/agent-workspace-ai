from __future__ import annotations

import json
import math
import re
from time import perf_counter
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from typing import Callable

from app.rag.chunking import StructuralChunker
from app.rag.parsers import parse_document_elements
from app.rag.service import query_coverage, sparse_scores, split_text


@dataclass(slots=True, frozen=True)
class RetrievalCase:
    name: str
    query: str
    document: str | None
    evidence: str | None
    answerable: bool = True


@dataclass(slots=True, frozen=True)
class CandidateChunk:
    document: str
    content: str
    token_count: int
    has_heading_path: bool


@dataclass(slots=True, frozen=True)
class ChunkingEvaluation:
    strategy: str
    documents: int
    chunks: int
    cases: int
    recall_at_k: float
    mrr: float
    ndcg_at_k: float
    context_precision_at_k: float
    context_recall_at_k: float
    citation_target_accuracy: float
    refusal_accuracy: float
    evidence_containment: float
    heading_metadata_coverage: float
    average_chunk_tokens: float
    max_chunk_tokens: int
    index_tokens: int
    estimated_embedding_cost: float
    p95_retrieval_ms: float
    case_results: tuple[dict, ...]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class AnswerJudgeResult:
    faithfulness: float
    answer_relevance: float
    citation_correctness: float
    refusal_correct: bool
    reason: str


def parse_answer_judge_response(response: str) -> AnswerJudgeResult:
    candidate = response.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        candidate = fenced.group(1)
    try:
        payload = json.loads(candidate)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("answer judge did not return valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("answer judge response must be an object")

    def score(name: str) -> float:
        value = payload.get(name)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"answer judge field {name} must be numeric")
        if not 0 <= float(value) <= 1:
            raise ValueError(f"answer judge field {name} must be within [0, 1]")
        return float(value)

    refusal_correct = payload.get("refusal_correct")
    reason = payload.get("reason")
    if not isinstance(refusal_correct, bool):
        raise ValueError("answer judge field refusal_correct must be boolean")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("answer judge field reason must be a non-empty string")
    return AnswerJudgeResult(
        faithfulness=score("faithfulness"),
        answer_relevance=score("answer_relevance"),
        citation_correctness=score("citation_correctness"),
        refusal_correct=refusal_correct,
        reason=reason.strip()[:1000],
    )


def answer_citations(answer: str) -> set[str]:
    return set(re.findall(r"\[([^\[\]]+#chunk-\d+)\]", answer))


def deterministic_citation_score(answer: str, allowed: set[str], *, answerable: bool) -> float:
    citations = answer_citations(answer)
    if not citations:
        return 0.0 if answerable else 1.0
    return 1.0 if citations.issubset(allowed) else 0.0


def compare_end_to_end_reports(
    baseline: dict,
    candidate: dict,
    *,
    min_primary_gain: float = 0.05,
    regression_tolerance: float = 0.01,
) -> dict:
    baseline_metrics = baseline.get("metrics")
    candidate_metrics = candidate.get("metrics")
    if not isinstance(baseline_metrics, dict) or not isinstance(candidate_metrics, dict):
        raise ValueError("baseline and candidate reports must contain metrics")
    if baseline.get("evaluation_errors"):
        raise ValueError("baseline report contains evaluation errors")
    if candidate.get("evaluation_errors"):
        raise ValueError("candidate report contains evaluation errors")

    guarded_metrics = (
        "recall_at_k",
        "mrr",
        "ndcg_at_k",
        "context_precision_at_k",
        "citation_target_accuracy",
        "faithfulness",
        "answer_relevance",
        "deterministic_citation_validity",
        "judge_citation_correctness",
        "refusal_accuracy",
    )
    deltas: dict[str, float] = {}
    failures: list[str] = []
    for metric in guarded_metrics:
        baseline_value = baseline_metrics.get(metric)
        candidate_value = candidate_metrics.get(metric)
        if not isinstance(baseline_value, (int, float)) or not isinstance(candidate_value, (int, float)):
            raise ValueError(f"report metric {metric} must be numeric")
        delta = float(candidate_value) - float(baseline_value)
        deltas[metric] = round(delta, 4)
        if delta < -regression_tolerance:
            failures.append(
                f"{metric} regressed by {abs(delta):.4f}, tolerance is {regression_tolerance:.4f}"
            )

    primary_metrics = ("recall_at_k", "mrr", "ndcg_at_k", "context_precision_at_k")
    best_primary_gain = max(deltas[metric] for metric in primary_metrics)
    if best_primary_gain < min_primary_gain:
        failures.append(
            f"best primary retrieval gain {best_primary_gain:.4f} < {min_primary_gain:.4f}"
        )
    return {
        "passed": not failures,
        "failures": failures,
        "deltas": deltas,
        "min_primary_gain": min_primary_gain,
        "regression_tolerance": regression_tolerance,
    }


def load_cases(path: Path) -> list[RetrievalCase]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [RetrievalCase(**row) for row in rows]


def load_documents(cases: list[RetrievalCase], directory: Path) -> dict[str, bytes]:
    filenames = sorted({case.document for case in cases if case.document is not None})
    return {filename: (directory / filename).read_bytes() for filename in filenames}


def legacy_candidates(documents: dict[str, bytes], token_count: Callable[[str], int]) -> list[CandidateChunk]:
    candidates: list[CandidateChunk] = []
    for filename, data in documents.items():
        text = data.decode("utf-8-sig")
        candidates.extend(
            CandidateChunk(filename, content, token_count(content), False)
            for content in split_text(text, chunk_size=900, overlap=140)
        )
    return candidates


def structural_candidates(
    documents: dict[str, bytes],
    chunker: StructuralChunker,
) -> list[CandidateChunk]:
    candidates: list[CandidateChunk] = []
    for filename, data in documents.items():
        parsed = parse_document_elements(filename, data)
        candidates.extend(
            CandidateChunk(filename, chunk.content, chunk.token_count, bool(chunk.heading_path))
            for chunk in chunker.chunk(parsed)
        )
    return candidates


def chonkie_sentence_candidates(
    documents: dict[str, bytes],
    *,
    chunk_tokens: int = 400,
    overlap_tokens: int = 100,
) -> list[CandidateChunk]:
    from chonkie import SentenceChunker

    chunker = SentenceChunker(
        tokenizer="cl100k_base",
        chunk_size=chunk_tokens,
        chunk_overlap=overlap_tokens,
        delim=["。", "！", "？", ". ", "! ", "? ", "\n"],
        include_delim="prev",
    )
    candidates: list[CandidateChunk] = []
    for filename, data in documents.items():
        text = data.decode("utf-8-sig")
        candidates.extend(
            CandidateChunk(filename, chunk.text, chunk.token_count, False)
            for chunk in chunker.chunk(text)
        )
    return candidates


def evaluate_candidates(
    strategy: str,
    documents: dict[str, bytes],
    candidates: list[CandidateChunk],
    cases: list[RetrievalCase],
    *,
    top_k: int = 5,
    min_score: float = 0.2,
    embedding_cost_per_million: float = 0.0,
    min_query_coverage: float = 0.15,
) -> ChunkingEvaluation:
    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    ndcgs: list[float] = []
    context_precisions: list[float] = []
    citation_targets: list[float] = []
    refusals: list[float] = []
    containment: list[float] = []
    latencies_ms: list[float] = []
    case_results: list[dict] = []
    contents = [candidate.content for candidate in candidates]
    for case in cases:
        started = perf_counter()
        relevant = {
            index
            for index, candidate in enumerate(candidates)
            if case.answerable
            and candidate.document == case.document
            and case.evidence is not None
            and case.evidence in candidate.content
        }
        scores = sparse_scores(case.query, contents)
        ranking = sorted(range(len(candidates)), key=lambda index: scores[index], reverse=True)
        retrieved = [
            index
            for index in ranking
            if scores[index] >= min_score
            and query_coverage(case.query, candidates[index].content) >= min_query_coverage
        ][:top_k]
        latencies_ms.append((perf_counter() - started) * 1000)
        if not case.answerable:
            refusals.append(1.0 if not retrieved else 0.0)
            case_results.append(
                {
                    "name": case.name,
                    "answerable": False,
                    "refused": not retrieved,
                    "retrieved": [candidates[index].document for index in retrieved],
                }
            )
            continue
        containment.append(1.0 if relevant else 0.0)
        relevant_retrieved = [rank for rank, index in enumerate(retrieved, start=1) if index in relevant]
        recalls.append(1.0 if relevant_retrieved else 0.0)
        context_precisions.append(len(relevant_retrieved) / max(len(retrieved), 1))
        citation_targets.append(1.0 if retrieved and retrieved[0] in relevant else 0.0)
        reciprocal_ranks.append(1 / relevant_retrieved[0] if relevant_retrieved else 0.0)
        dcg = sum(1 / math.log2(rank + 1) for rank in relevant_retrieved)
        ideal_count = min(len(relevant), top_k)
        ideal_dcg = sum(1 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
        ndcgs.append(dcg / ideal_dcg if ideal_dcg else 0.0)
        case_results.append(
            {
                "name": case.name,
                "answerable": True,
                "hit": bool(relevant_retrieved),
                "first_relevant_rank": relevant_retrieved[0] if relevant_retrieved else None,
                "retrieved": [candidates[index].document for index in retrieved],
                "coverages": [round(query_coverage(case.query, candidates[index].content), 4) for index in retrieved],
            }
        )
    token_counts = [candidate.token_count for candidate in candidates]
    sorted_latencies = sorted(latencies_ms)
    p95_index = max(0, math.ceil(len(sorted_latencies) * 0.95) - 1)
    index_tokens = sum(token_counts)
    return ChunkingEvaluation(
        strategy=strategy,
        documents=len(documents),
        chunks=len(candidates),
        cases=len(cases),
        recall_at_k=round(mean(recalls), 4) if recalls else 0.0,
        mrr=round(mean(reciprocal_ranks), 4) if reciprocal_ranks else 0.0,
        ndcg_at_k=round(mean(ndcgs), 4) if ndcgs else 0.0,
        context_precision_at_k=round(mean(context_precisions), 4) if context_precisions else 0.0,
        context_recall_at_k=round(mean(recalls), 4) if recalls else 0.0,
        citation_target_accuracy=round(mean(citation_targets), 4) if citation_targets else 0.0,
        refusal_accuracy=round(mean(refusals), 4) if refusals else 0.0,
        evidence_containment=round(mean(containment), 4) if containment else 0.0,
        heading_metadata_coverage=round(
            sum(candidate.has_heading_path for candidate in candidates) / max(len(candidates), 1),
            4,
        ),
        average_chunk_tokens=round(mean(token_counts), 2) if token_counts else 0.0,
        max_chunk_tokens=max(token_counts, default=0),
        index_tokens=index_tokens,
        estimated_embedding_cost=round(index_tokens * embedding_cost_per_million / 1_000_000, 8),
        p95_retrieval_ms=round(sorted_latencies[p95_index], 3) if sorted_latencies else 0.0,
        case_results=tuple(case_results),
    )
