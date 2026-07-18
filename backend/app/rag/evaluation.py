from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from statistics import mean
from time import perf_counter
from typing import Callable

from app.rag.chunking import StructuralChunker, TokenCounter
from app.rag.parsers import parse_document_elements
from app.rag.service import query_coverage, sparse_scores, split_text


JUDGE_CONTEXT_MAX_TOKENS = 2200
EVALUATION_DOCUMENT_SUFFIXES = {".pdf", ".docx", ".md", ".markdown", ".txt"}
judge_context_tokens = TokenCounter("cl100k_base")


@dataclass(slots=True, frozen=True)
class RetrievalCase:
    name: str
    query: str
    document: str | None
    evidence: str | None
    answerable: bool = True
    answer_required_groups: tuple[tuple[str, ...], ...] = ()
    answer_forbidden_terms: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class CandidateChunk:
    document: str
    content: str
    token_count: int
    has_heading_path: bool
    parent_id: str


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


def bounded_judge_context(rows: list[dict], max_tokens: int = JUDGE_CONTEXT_MAX_TOKENS) -> str:
    if not rows:
        return "(no context)"
    prefixes = [f"[{row['citation']}]\n" for row in rows]
    wrapper_tokens = sum(judge_context_tokens.count(prefix) + 4 for prefix in prefixes)
    available = max(0, max_tokens - wrapper_tokens)
    per_row, remainder = divmod(available, len(rows))
    blocks: list[str] = []
    for index, (prefix, row) in enumerate(zip(prefixes, rows)):
        content_budget = per_row + (1 if index < remainder else 0)
        encoded = judge_context_tokens.encoding.encode(str(row.get("content") or ""), disallowed_special=())
        content = judge_context_tokens.encoding.decode(encoded[:content_budget]).strip()
        blocks.append(f"{prefix}{content}")
    return "\n\n".join(blocks)


def answer_judge_prompt(case: RetrievalCase, answer: str, rows: list[dict]) -> str:
    context = bounded_judge_context(rows)
    evidence = case.evidence or "(the corpus contains no answer)"
    return (
        "Evaluate only the supplied answer against the supplied context and reference evidence. "
        "Return one JSON object with exactly these fields: faithfulness, answer_relevance, "
        "citation_correctness (numbers from 0 to 1), refusal_correct (boolean), and reason (string). "
        "Faithfulness is the fraction of factual claims supported by context. Citation correctness requires each "
        "citation to support its adjacent claim. refusal_correct is true when an unanswerable question is refused, "
        "or when an answerable question is answered instead of refused. Do not use outside knowledge.\n\n"
        f"Question: {case.query}\nExpected answerable: {str(case.answerable).lower()}\n"
        f"Reference evidence: {evidence}\n\nRetrieved context:\n{context}\n\nAnswer:\n{answer}"
    )


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


def first_relevant_rank(matches: Iterable[bool]) -> int | None:
    """Rank one evidence target once, even when overlapping chunks repeat it."""
    return next((rank for rank, matched in enumerate(matches, start=1) if matched), None)


def deterministic_answer_assertion_score(
    answer: str,
    required_groups: Iterable[Iterable[str]],
    forbidden_terms: Iterable[str],
) -> float:
    normalized = answer.casefold()
    required = tuple(tuple(term.casefold() for term in group if term) for group in required_groups)
    forbidden = tuple(term.casefold() for term in forbidden_terms if term)
    required_match = all(group and any(term in normalized for term in group) for group in required)
    forbidden_match = any(term in normalized for term in forbidden)
    return 1.0 if required and required_match and not forbidden_match else 0.0


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
    baseline_corpus = (baseline.get("dataset") or {}).get("corpus_sha256")
    candidate_corpus = (candidate.get("dataset") or {}).get("corpus_sha256")
    if bool(baseline_corpus) != bool(candidate_corpus):
        raise ValueError("baseline and candidate reports must both identify their corpus")
    if baseline_corpus and baseline_corpus != candidate_corpus:
        raise ValueError("baseline and candidate reports use different corpora")
    baseline_parsed_corpus = (baseline.get("parsing") or {}).get("parsed_corpus_sha256")
    candidate_parsed_corpus = (candidate.get("parsing") or {}).get("parsed_corpus_sha256")
    if bool(baseline_parsed_corpus) != bool(candidate_parsed_corpus):
        raise ValueError("baseline and candidate reports must both identify their parsed corpus")
    if baseline_parsed_corpus and baseline_parsed_corpus != candidate_parsed_corpus:
        raise ValueError("baseline and candidate reports use different parsed corpora")
    if baseline_parsed_corpus:
        baseline_parsing = baseline["parsing"]
        candidate_parsing = candidate["parsing"]
        for field in ("backend", "fallback_enabled"):
            if baseline_parsing.get(field) != candidate_parsing.get(field):
                raise ValueError("baseline and candidate reports use different parsing configurations")

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
        "answer_assertion_accuracy",
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
            failures.append(f"{metric} regressed by {abs(delta):.4f}, tolerance is {regression_tolerance:.4f}")

    primary_metrics = ("recall_at_k", "mrr", "ndcg_at_k", "context_precision_at_k")
    best_primary_gain = max(deltas[metric] for metric in primary_metrics)
    if best_primary_gain < min_primary_gain:
        failures.append(f"best primary retrieval gain {best_primary_gain:.4f} < {min_primary_gain:.4f}")
    return {
        "passed": not failures,
        "failures": failures,
        "deltas": deltas,
        "min_primary_gain": min_primary_gain,
        "regression_tolerance": regression_tolerance,
    }


def load_cases(path: Path) -> list[RetrievalCase]:
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"unable to load evaluation cases: {exc}") from exc
    if not isinstance(rows, list) or not rows:
        raise ValueError("evaluation cases must be a non-empty JSON array")
    cases: list[RetrievalCase] = []
    seen_names: set[str] = set()
    for index, source in enumerate(rows):
        if not isinstance(source, dict):
            raise ValueError(f"evaluation case {index} must be an object")
        row = dict(source)
        name = row.get("name")
        query = row.get("query")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"evaluation case {index} must have a non-empty name")
        if name in seen_names:
            raise ValueError(f"duplicate evaluation case name: {name}")
        seen_names.add(name)
        if not isinstance(query, str) or not query.strip():
            raise ValueError(f"evaluation case {name} must have a non-empty query")
        document = row.get("document")
        if document is not None:
            if not isinstance(document, str) or not document.strip():
                raise ValueError(f"evaluation case {name} has an invalid document path")
            normalized = PurePosixPath(document.replace("\\", "/"))
            if normalized.is_absolute() or ".." in normalized.parts:
                raise ValueError(f"evaluation case {name} document must stay inside the corpus")
            row["document"] = normalized.as_posix()
        groups = row.get("answer_required_groups", [])
        if not isinstance(groups, list) or any(
            not isinstance(group, list)
            or not group
            or any(not isinstance(term, str) or not term for term in group)
            for group in groups
        ):
            raise ValueError(f"evaluation case {name} has invalid answer_required_groups")
        forbidden = row.get("answer_forbidden_terms", [])
        if not isinstance(forbidden, list) or any(
            not isinstance(term, str) or not term for term in forbidden
        ):
            raise ValueError(f"evaluation case {name} has invalid answer_forbidden_terms")
        row["answer_required_groups"] = tuple(tuple(group) for group in groups)
        row["answer_forbidden_terms"] = tuple(forbidden)
        try:
            case = RetrievalCase(**row)
        except TypeError as exc:
            raise ValueError(f"evaluation case {name} has invalid fields: {exc}") from exc
        if case.answerable and (
            not case.document
            or not isinstance(case.evidence, str)
            or not case.evidence.strip()
            or not case.answer_required_groups
        ):
            raise ValueError(
                f"answerable evaluation case {name} requires document, evidence, and answer assertions"
            )
        cases.append(case)
    return cases


def load_documents(cases: list[RetrievalCase], directory: Path) -> dict[str, bytes]:
    filenames = sorted({case.document for case in cases if case.document is not None})
    return {filename: (directory / filename).read_bytes() for filename in filenames}


def load_document_directory(directory: Path) -> dict[str, bytes]:
    if not directory.is_dir():
        raise ValueError(f"evaluation documents directory does not exist: {directory}")
    if directory.is_symlink():
        raise ValueError(f"evaluation corpus cannot be a symlink: {directory}")
    documents: dict[str, bytes] = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"evaluation corpus cannot contain symlinks: {path}")
        if not path.is_file() or path.suffix.lower() not in EVALUATION_DOCUMENT_SUFFIXES:
            continue
        relative = path.relative_to(directory).as_posix()
        data = path.read_bytes()
        if not data:
            raise ValueError(f"evaluation document is empty: {relative}")
        documents[relative] = data
    if not documents:
        supported = ", ".join(sorted(EVALUATION_DOCUMENT_SUFFIXES))
        raise ValueError(f"evaluation corpus contains no supported documents ({supported})")
    return documents


def load_evaluation_corpus(
    cases_path: Path,
    documents_directory: Path,
) -> tuple[list[RetrievalCase], dict[str, bytes], dict]:
    cases = load_cases(cases_path)
    documents = load_document_directory(documents_directory)
    missing = sorted(
        {
            case.document
            for case in cases
            if case.answerable and case.document not in documents
        }
    )
    if missing:
        raise ValueError(f"evaluation cases reference missing documents: {', '.join(missing)}")
    if not any(case.answerable for case in cases) or not any(not case.answerable for case in cases):
        raise ValueError("evaluation corpus must contain answerable and unanswerable cases")

    cases_bytes = cases_path.read_bytes()
    cases_sha256 = hashlib.sha256(cases_bytes).hexdigest()
    document_digest = hashlib.sha256()
    document_rows: list[dict] = []
    for name, data in sorted(documents.items()):
        name_bytes = name.encode("utf-8")
        digest = hashlib.sha256(data).hexdigest()
        document_digest.update(len(name_bytes).to_bytes(8, "big"))
        document_digest.update(name_bytes)
        document_digest.update(len(data).to_bytes(8, "big"))
        document_digest.update(data)
        document_rows.append({"name": name, "bytes": len(data), "sha256": digest})
    documents_sha256 = document_digest.hexdigest()
    corpus_digest = hashlib.sha256()
    corpus_digest.update(bytes.fromhex(cases_sha256))
    corpus_digest.update(bytes.fromhex(documents_sha256))
    metadata = {
        "case_count": len(cases),
        "answerable_cases": sum(1 for case in cases if case.answerable),
        "unanswerable_cases": sum(1 for case in cases if not case.answerable),
        "document_count": len(documents),
        "cases_sha256": cases_sha256,
        "documents_sha256": documents_sha256,
        "corpus_sha256": corpus_digest.hexdigest(),
        "documents": document_rows,
    }
    return cases, documents, metadata


def legacy_candidates(documents: dict[str, bytes], token_count: Callable[[str], int]) -> list[CandidateChunk]:
    candidates: list[CandidateChunk] = []
    for filename, data in documents.items():
        text = data.decode("utf-8-sig")
        for chunk_index, content in enumerate(split_text(text, chunk_size=900, overlap=140)):
            candidates.append(
                CandidateChunk(
                    filename,
                    content,
                    token_count(content),
                    False,
                    f"{filename}:{chunk_index}",
                )
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
            CandidateChunk(
                filename,
                chunk.content,
                chunk.token_count,
                bool(chunk.heading_path),
                chunk.parent_stable_id,
            )
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
            CandidateChunk(
                filename,
                chunk.text,
                chunk.token_count,
                False,
                f"{filename}:{chunk_index}",
            )
            for chunk_index, chunk in enumerate(chunker.chunk(text))
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
        retrieved: list[int] = []
        seen_parents: set[tuple[str, str]] = set()
        for index in ranking:
            candidate = candidates[index]
            if scores[index] < min_score:
                continue
            if query_coverage(case.query, candidate.content) < min_query_coverage:
                continue
            parent_key = (candidate.document, candidate.parent_id)
            if parent_key in seen_parents:
                continue
            seen_parents.add(parent_key)
            retrieved.append(index)
            if len(retrieved) >= top_k:
                break
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
        relevant_rank = first_relevant_rank(index in relevant for index in retrieved)
        recalls.append(1.0 if relevant_rank is not None else 0.0)
        context_precisions.append((1.0 if relevant_rank is not None else 0.0) / max(len(retrieved), 1))
        citation_targets.append(1.0 if retrieved and retrieved[0] in relevant else 0.0)
        reciprocal_ranks.append(1 / relevant_rank if relevant_rank is not None else 0.0)
        ndcgs.append(1 / math.log2(relevant_rank + 1) if relevant_rank is not None else 0.0)
        case_results.append(
            {
                "name": case.name,
                "answerable": True,
                "hit": relevant_rank is not None,
                "first_relevant_rank": relevant_rank,
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
