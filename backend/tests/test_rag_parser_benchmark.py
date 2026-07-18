import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.rag.parser_benchmark import (
    BenchmarkElement,
    BenchmarkExpectation,
    build_backend_report,
    compare_backend_reports,
    corpus_fingerprint,
    resolve_corpus_file,
    score_document,
)


def expectation() -> BenchmarkExpectation:
    return BenchmarkExpectation(
        filename="sample.pdf",
        markers=("RECOVERY 100", "TABLE 200"),
        ordered_markers=("RECOVERY 100", "TABLE 200"),
        required_kinds=("title", "table"),
        require_page_metadata=True,
        require_bbox_metadata=True,
    )


def test_parser_benchmark_scores_evidence_structure_order_and_metadata() -> None:
    row = score_document(
        expectation(),
        [
            BenchmarkElement("title", "Recovery   100", page=1, bbox=(0, 0, 10, 10)),
            BenchmarkElement("table", "<table><td>TABLE 200</td></table>", page=1, bbox=(0, 20, 10, 30)),
        ],
        latency_ms=12.3456,
    )

    assert row["success"] is True
    assert row["marker_recall"] == 1.0
    assert row["structure_recall"] == 1.0
    assert row["reading_order_accuracy"] == 1.0
    assert row["page_metadata_coverage"] == 1.0
    assert row["bbox_metadata_coverage"] == 1.0
    assert row["latency_ms"] == 12.346

    no_order_constraint = score_document(
        BenchmarkExpectation(
            filename="sample.pdf",
            markers=("RECOVERY 100",),
            ordered_markers=(),
            required_kinds=("title",),
        ),
        [BenchmarkElement("title", "RECOVERY 100")],
        latency_ms=1,
    )
    assert no_order_constraint["reading_order_accuracy"] == 1.0


def report(backend: str, *, corpus_hash: str = "same", marker_recall: float = 1.0) -> dict:
    row = score_document(
        expectation(),
        [
            BenchmarkElement("title", "RECOVERY 100", page=1, bbox=(0, 0, 10, 10)),
            BenchmarkElement("table", "TABLE 200", page=1, bbox=(0, 20, 10, 30)),
        ],
        latency_ms=10,
    )
    row["marker_recall"] = marker_recall
    return build_backend_report(
        backend=backend,
        version="test",
        corpus_hash=corpus_hash,
        documents=[row],
        peak_memory_mb=100,
        artifact_size_mb=200,
        memory_scope="process",
        artifact_scope="isolated-environment",
    )


def test_parser_comparison_requires_all_backends_same_corpus_and_quality() -> None:
    reports = [report(backend) for backend in ("native", "docling", "unstructured", "mineru")]
    passed = compare_backend_reports(reports)
    mismatched = compare_backend_reports([*reports[:-1], report("mineru", corpus_hash="different")])
    weak = compare_backend_reports([*reports[:-1], report("mineru", marker_recall=0.2)])
    missing_metadata = report("mineru")
    missing_metadata["metrics"]["bbox_metadata_coverage"] = 0.0
    metadata_failure = compare_backend_reports([*reports[:-1], missing_metadata])

    assert passed["passed"] is True
    assert {row["backend"] for row in passed["ranking"]} == {
        "native",
        "docling",
        "unstructured",
        "mineru",
    }
    assert mismatched["passed"] is False
    assert "one identical corpus hash" in mismatched["failures"][0]
    assert weak["passed"] is False
    assert any("mineru marker_recall" in failure for failure in weak["failures"])
    assert metadata_failure["passed"] is False
    assert any("bbox_metadata_coverage" in failure for failure in metadata_failure["failures"])


def test_parser_comparison_rejects_duplicate_and_malformed_reports_without_crashing() -> None:
    reports = [report(backend) for backend in ("native", "docling", "unstructured", "mineru")]
    duplicate = compare_backend_reports([*reports, report("mineru")])
    malformed = report("docling")
    malformed["metrics"]["marker_recall"] = float("nan")
    malformed["metrics"].pop("structure_recall")
    invalid = compare_backend_reports([reports[0], malformed, *reports[2:]])
    invalid_type = compare_backend_reports([*reports, []])

    assert duplicate["passed"] is False
    assert any("duplicate backend" in failure for failure in duplicate["failures"])
    assert invalid["passed"] is False
    assert any("invalid metrics" in failure for failure in invalid["failures"])
    assert invalid_type["passed"] is False
    assert any("not an object" in failure for failure in invalid_type["failures"])
    assert {row["backend"] for row in invalid["ranking"]} == {
        "native",
        "unstructured",
        "mineru",
    }


def test_parser_comparison_rejects_inconsistent_document_sets_and_summaries() -> None:
    reports = [report(backend) for backend in ("native", "docling", "unstructured", "mineru")]
    missing_document = report("mineru")
    missing_document["documents"][0]["filename"] = "different.pdf"
    mismatched_set = compare_backend_reports([*reports[:-1], missing_document])
    stale_summary = report("mineru")
    stale_summary["metrics"]["marker_recall"] = 0.95
    mismatched_summary = compare_backend_reports([*reports[:-1], stale_summary])

    assert mismatched_set["passed"] is False
    assert any("identical document set" in failure for failure in mismatched_set["failures"])
    assert mismatched_summary["passed"] is False
    assert any("summary does not match" in failure for failure in mismatched_summary["failures"])


def test_parser_comparison_rejects_unknown_backend_and_out_of_range_metrics() -> None:
    reports = [report(backend) for backend in ("native", "docling", "unstructured", "mineru")]
    unknown = report("unknown")
    out_of_range = report("mineru")
    out_of_range["metrics"]["marker_recall"] = 1.1

    unexpected = compare_backend_reports([*reports, unknown])
    invalid = compare_backend_reports([*reports[:-1], out_of_range])

    assert unexpected["passed"] is False
    assert any("unexpected backend" in failure for failure in unexpected["failures"])
    assert invalid["passed"] is False
    assert any("invalid metrics" in failure for failure in invalid["failures"])


def test_corpus_fingerprint_changes_with_source_bytes(tmp_path: Path) -> None:
    sample = tmp_path / "sample.pdf"
    sample.write_bytes(b"first")
    first = corpus_fingerprint(tmp_path, [expectation()])
    sample.write_bytes(b"second")
    second = corpus_fingerprint(tmp_path, [expectation()])

    assert first != second


def test_corpus_paths_cannot_escape_manifest_directory(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.pdf"
    outside.write_bytes(b"outside")

    try:
        with pytest.raises(ValueError, match="escapes corpus directory"):
            resolve_corpus_file(tmp_path, "../outside.pdf")
    finally:
        outside.unlink()


def test_compare_cli_writes_failure_report_for_malformed_input(tmp_path: Path) -> None:
    valid_path = tmp_path / "native.json"
    invalid_path = tmp_path / "invalid.json"
    output_path = tmp_path / "comparison.json"
    valid_path.write_text(json.dumps(report("native")), encoding="utf-8")
    invalid_path.write_text("{not-json", encoding="utf-8")
    script = Path(__file__).resolve().parents[2] / "scripts" / "benchmark_rag_parsers.py"

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "compare",
            "--reports",
            str(valid_path),
            str(invalid_path),
            "--required-backends",
            "native",
            "--output",
            str(output_path),
            "--enforce-gates",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert completed.returncode == 1
    assert payload["passed"] is False
    assert any("invalid.json" in failure for failure in payload["failures"])
