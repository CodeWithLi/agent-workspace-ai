from __future__ import annotations

import hashlib
import html
import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from typing import Any


@dataclass(slots=True, frozen=True)
class BenchmarkElement:
    kind: str
    content: str
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None


@dataclass(slots=True, frozen=True)
class BenchmarkExpectation:
    filename: str
    markers: tuple[str, ...]
    ordered_markers: tuple[str, ...]
    required_kinds: tuple[str, ...]
    require_page_metadata: bool = False
    require_bbox_metadata: bool = False


def normalize_text(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", html.unescape(value))
    return re.sub(r"\s+", " ", without_tags).strip().casefold()


def resolve_corpus_file(corpus_dir: Path, filename: str) -> Path:
    root = corpus_dir.resolve()
    candidate = (root / filename).resolve()
    if candidate == root or not candidate.is_relative_to(root):
        raise ValueError(f"benchmark sample escapes corpus directory: {filename}")
    if not candidate.is_file():
        raise FileNotFoundError(f"benchmark sample does not exist: {filename}")
    return candidate


def corpus_fingerprint(corpus_dir: Path, expectations: list[BenchmarkExpectation]) -> str:
    digest = hashlib.sha256()
    for expectation in sorted(expectations, key=lambda item: item.filename):
        path = resolve_corpus_file(corpus_dir, expectation.filename)
        digest.update(expectation.filename.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
        digest.update(json.dumps(asdict(expectation), sort_keys=True).encode("utf-8"))
    return digest.hexdigest()


def score_document(
    expectation: BenchmarkExpectation,
    elements: list[BenchmarkElement],
    *,
    latency_ms: float,
    error: str = "",
) -> dict[str, Any]:
    content = normalize_text("\n".join(element.content for element in elements))
    markers = [normalize_text(marker) for marker in expectation.markers]
    marker_hits = [marker in content for marker in markers]
    positions = [content.find(normalize_text(marker)) for marker in expectation.ordered_markers]
    order_correct = not positions or (
        all(position >= 0 for position in positions) and positions == sorted(positions)
    )
    kinds = {element.kind for element in elements}
    required_kinds = set(expectation.required_kinds)
    page_candidates = [element for element in elements if element.content.strip()]
    bbox_candidates = [element for element in elements if element.content.strip()]
    return {
        "filename": expectation.filename,
        "success": not error and bool(elements),
        "error": error[:1000],
        "elements": len(elements),
        "marker_recall": round(sum(marker_hits) / max(len(marker_hits), 1), 4),
        "missing_markers": [
            marker for marker, hit in zip(expectation.markers, marker_hits) if not hit
        ],
        "structure_recall": round(len(kinds & required_kinds) / max(len(required_kinds), 1), 4),
        "missing_kinds": sorted(required_kinds - kinds),
        "reading_order_accuracy": 1.0 if order_correct else 0.0,
        "page_metadata_coverage": round(
            sum(element.page is not None for element in page_candidates) / max(len(page_candidates), 1),
            4,
        ),
        "bbox_metadata_coverage": round(
            sum(element.bbox is not None for element in bbox_candidates) / max(len(bbox_candidates), 1),
            4,
        ),
        "requires_page_metadata": expectation.require_page_metadata,
        "requires_bbox_metadata": expectation.require_bbox_metadata,
        "latency_ms": round(latency_ms, 3),
    }


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * quantile) - 1)]


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _aggregate_document_metrics(documents: list[dict[str, Any]]) -> dict[str, float]:
    page_required = [row for row in documents if row["requires_page_metadata"]]
    bbox_required = [row for row in documents if row["requires_bbox_metadata"]]
    return {
        "parse_success_rate": round(mean(row["success"] for row in documents), 4)
        if documents
        else 0.0,
        "marker_recall": round(mean(row["marker_recall"] for row in documents), 4)
        if documents
        else 0.0,
        "structure_recall": round(mean(row["structure_recall"] for row in documents), 4)
        if documents
        else 0.0,
        "reading_order_accuracy": round(
            mean(row["reading_order_accuracy"] for row in documents), 4
        )
        if documents
        else 0.0,
        "page_metadata_coverage": round(
            mean(row["page_metadata_coverage"] for row in page_required), 4
        )
        if page_required
        else 0.0,
        "bbox_metadata_coverage": round(
            mean(row["bbox_metadata_coverage"] for row in bbox_required), 4
        )
        if bbox_required
        else 0.0,
        "p95_latency_ms": round(
            percentile([row["latency_ms"] for row in documents], 0.95), 3
        ),
    }


def build_backend_report(
    *,
    backend: str,
    version: str,
    corpus_hash: str,
    documents: list[dict[str, Any]],
    peak_memory_mb: float | None,
    artifact_size_mb: float | None,
    memory_scope: str,
    artifact_scope: str,
) -> dict[str, Any]:
    metrics = {
        **_aggregate_document_metrics(documents),
        "peak_memory_mb": round(peak_memory_mb, 2) if peak_memory_mb is not None else None,
        "artifact_size_mb": round(artifact_size_mb, 2) if artifact_size_mb is not None else None,
    }
    return {
        "schema_version": 1,
        "backend": backend,
        "version": version,
        "corpus_hash": corpus_hash,
        "memory_scope": memory_scope,
        "artifact_scope": artifact_scope,
        "metrics": metrics,
        "documents": documents,
    }


def compare_backend_reports(
    reports: list[dict[str, Any]],
    *,
    required_backends: tuple[str, ...] = ("native", "docling", "unstructured", "mineru"),
    min_success_rate: float = 1.0,
    min_marker_recall: float = 0.9,
    min_structure_recall: float = 0.5,
    min_reading_order_accuracy: float = 1.0,
    min_page_metadata_coverage: float = 0.9,
    min_bbox_metadata_coverage: float = 0.9,
) -> dict[str, Any]:
    failures: list[str] = []
    typed_reports: list[dict[str, Any]] = []
    for index, report in enumerate(reports):
        if not isinstance(report, dict):
            failures.append(f"report {index} is not an object")
            continue
        typed_reports.append(report)
    backend_names = [str(report.get("backend") or "") for report in typed_reports]
    if any(not backend for backend in backend_names):
        failures.append("one or more reports are missing a backend name")
    duplicates = sorted(
        backend for backend in set(backend_names) if backend and backend_names.count(backend) > 1
    )
    if duplicates:
        failures.append(f"duplicate backend reports: {', '.join(duplicates)}")
    unexpected = sorted(set(backend_names) - set(required_backends) - {""})
    if unexpected:
        failures.append(f"unexpected backend reports: {', '.join(unexpected)}")
    by_backend = {
        backend: report
        for backend, report in zip(backend_names, typed_reports)
        if backend
    }
    missing = sorted(set(required_backends) - set(by_backend))
    if missing:
        failures.append(f"missing backend reports: {', '.join(missing)}")
    hash_values = [report.get("corpus_hash") for report in typed_reports]
    same_corpus = (
        bool(hash_values)
        and all(isinstance(value, str) and value for value in hash_values)
        and len(set(hash_values)) == 1
    )
    if not same_corpus:
        failures.append("backend reports do not use one identical corpus hash")

    quality_metrics = (
        "marker_recall",
        "structure_recall",
        "reading_order_accuracy",
        "page_metadata_coverage",
        "bbox_metadata_coverage",
    )
    valid_quality: dict[str, dict[str, float]] = {}
    document_names: dict[str, set[str]] = {}
    for backend, report in by_backend.items():
        if report.get("schema_version") != 1:
            failures.append(f"{backend} has unsupported report schema")
        if not isinstance(report.get("version"), str) or not report["version"].strip():
            failures.append(f"{backend} is missing parser version")
        documents = report.get("documents")
        if not isinstance(documents, list) or not documents:
            failures.append(f"{backend} report contains no documents")
            documents = []
        rows_valid = True
        filenames: list[str] = []
        for index, row in enumerate(documents):
            if not isinstance(row, dict):
                failures.append(f"{backend} document {index} is not an object")
                rows_valid = False
                continue
            filename = row.get("filename")
            if not isinstance(filename, str) or not filename.strip():
                failures.append(f"{backend} document {index} is missing filename")
                rows_valid = False
            else:
                filenames.append(filename)
            if not isinstance(row.get("success"), bool):
                failures.append(f"{backend} document {index} has invalid success")
                rows_valid = False
            if not isinstance(row.get("requires_page_metadata"), bool) or not isinstance(
                row.get("requires_bbox_metadata"), bool
            ):
                failures.append(f"{backend} document {index} has invalid metadata requirements")
                rows_valid = False
            for metric in quality_metrics:
                value = row.get(metric)
                if not _finite_number(value) or not 0 <= float(value) <= 1:
                    failures.append(f"{backend} document {index} has invalid {metric}")
                    rows_valid = False
            latency = row.get("latency_ms")
            if not _finite_number(latency) or float(latency) < 0:
                failures.append(f"{backend} document {index} has invalid latency_ms")
                rows_valid = False
        if len(filenames) != len(set(filenames)):
            failures.append(f"{backend} report contains duplicate document filenames")
            rows_valid = False
        document_names[backend] = set(filenames)
        if not isinstance(report.get("memory_scope"), str) or not report["memory_scope"].strip():
            failures.append(f"{backend} is missing memory scope")
        if not isinstance(report.get("artifact_scope"), str) or not report["artifact_scope"].strip():
            failures.append(f"{backend} is missing artifact scope")
        metrics = report.get("metrics")
        if not isinstance(metrics, dict):
            failures.append(f"{backend} report has no metrics object")
            continue
        required_numeric = ("parse_success_rate", *quality_metrics, "p95_latency_ms")
        invalid = [
            metric
            for metric in required_numeric
            if not _finite_number(metrics.get(metric))
            or (
                metric != "p95_latency_ms"
                and not 0 <= float(metrics[metric]) <= 1
            )
            or (metric == "p95_latency_ms" and float(metrics[metric]) < 0)
        ]
        if invalid:
            failures.append(f"{backend} has invalid metrics: {', '.join(invalid)}")
            continue
        if rows_valid:
            aggregated = _aggregate_document_metrics(documents)
            mismatched = [
                metric
                for metric, expected in aggregated.items()
                if not math.isclose(float(metrics[metric]), expected, abs_tol=0.0005)
            ]
            if mismatched:
                failures.append(
                    f"{backend} summary does not match document rows: {', '.join(mismatched)}"
                )
                continue
        valid_quality[backend] = {
            metric: float(metrics[metric]) for metric in quality_metrics
        }

    comparable_sets = {
        backend: document_names[backend]
        for backend in required_backends
        if backend in document_names
    }
    if comparable_sets and len({frozenset(names) for names in comparable_sets.values()}) != 1:
        failures.append("backend reports do not contain one identical document set")

    guarded = set(required_backends) - {"native"}
    for backend in sorted(guarded & set(by_backend)):
        metrics = by_backend[backend].get("metrics", {})
        if not isinstance(metrics, dict):
            continue
        for metric, minimum in (
            ("parse_success_rate", min_success_rate),
            ("marker_recall", min_marker_recall),
            ("structure_recall", min_structure_recall),
            ("reading_order_accuracy", min_reading_order_accuracy),
            ("page_metadata_coverage", min_page_metadata_coverage),
            ("bbox_metadata_coverage", min_bbox_metadata_coverage),
        ):
            value = metrics.get(metric)
            if (
                not _finite_number(value)
                or float(value) < minimum
            ):
                failures.append(f"{backend} {metric} {value!r} < {minimum:.4f}")
        for metric in ("peak_memory_mb", "artifact_size_mb"):
            value = metrics.get(metric)
            if (
                not _finite_number(value)
                or float(value) <= 0
            ):
                failures.append(f"{backend} is missing {metric}")

    ranked = sorted(
        (
            {
                "backend": backend,
                "quality_score": round(
                    0.35 * metrics["marker_recall"]
                    + 0.25 * metrics["structure_recall"]
                    + 0.15 * metrics["reading_order_accuracy"]
                    + 0.125 * metrics["page_metadata_coverage"]
                    + 0.125 * metrics["bbox_metadata_coverage"],
                    4,
                ),
            }
            for backend, metrics in valid_quality.items()
        ),
        key=lambda row: (-row["quality_score"], row["backend"]),
    )
    return {
        "passed": not failures,
        "failures": failures,
        "corpus_hash": hash_values[0] if same_corpus else None,
        "thresholds": {
            "min_success_rate": min_success_rate,
            "min_marker_recall": min_marker_recall,
            "min_structure_recall": min_structure_recall,
            "min_reading_order_accuracy": min_reading_order_accuracy,
            "min_page_metadata_coverage": min_page_metadata_coverage,
            "min_bbox_metadata_coverage": min_bbox_metadata_coverage,
        },
        "ranking": ranked,
        "reports": reports,
    }
