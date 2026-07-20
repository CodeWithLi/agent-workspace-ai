import hashlib
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.build_rag_business_corpus import (
    FACT_SPECS,
    SOURCE_SPECS,
    UNANSWERABLE_QUERIES,
    assert_sanitized,
    build_corpus,
    sanitize_text,
)


def tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_business_corpus_size_is_frozen() -> None:
    assert len(SOURCE_SPECS) == 30
    assert len(FACT_SPECS) == 30
    assert len(UNANSWERABLE_QUERIES) == 30
    assert len({spec.source for spec in SOURCE_SPECS}) == len(SOURCE_SPECS)
    assert len({spec.output for spec in SOURCE_SPECS}) == len(SOURCE_SPECS)
    assert {fact.source for fact in FACT_SPECS}.issubset({spec.source for spec in SOURCE_SPECS})


def test_business_corpus_sanitizer_removes_high_risk_values() -> None:
    source = """
phone: "17708216145"
email: operator@example.com
DATABASE_URL=mysql+pymysql://root:password@192.168.23.128:3306/private
LLM_API_KEY=sk-sensitive-value
account_id: store_secret
product: BD071A
domain: pdd.velunqwe.online
"""

    sanitized, counts = sanitize_text(source)

    assert "17708216145" not in sanitized
    assert "operator@example.com" not in sanitized
    assert "root:password" not in sanitized
    assert "192.168.23.128" not in sanitized
    assert "sk-sensitive-value" not in sanitized
    assert "store_secret" not in sanitized
    assert "BD071A" not in sanitized
    assert "velunqwe.online" not in sanitized
    assert counts["phone"] == 1
    assert counts["credential_url"] == 1
    assert counts["secret_assignment"] >= 2
    assert_sanitized(sanitized, label="unit-test")


def test_business_corpus_sanitization_validator_rejects_leaks() -> None:
    with pytest.raises(ValueError, match="sanitization failed"):
        assert_sanitized("call 17708216145", label="unsafe")


def test_business_corpus_force_rejects_unmanaged_output(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    output_root = tmp_path / "unmanaged"
    source_root.mkdir()
    output_root.mkdir()
    (output_root / "personal.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="valid corpus manifest"):
        build_corpus(source_root, output_root, force=True)

    assert (output_root / "personal.txt").read_text(encoding="utf-8") == "keep"


def test_business_corpus_build_is_deterministic_and_traceable(tmp_path: Path) -> None:
    pytest.importorskip("docx")
    pytest.importorskip("PIL")
    pytest.importorskip("reportlab")
    source_root = tmp_path / "business-source"
    evidence_by_source: dict[str, list[str]] = {}
    for fact in FACT_SPECS:
        evidence_by_source.setdefault(fact.source, []).append(fact.evidence)
    for spec in SOURCE_SPECS:
        path = source_root / spec.source
        path.parent.mkdir(parents=True, exist_ok=True)
        evidence = evidence_by_source.get(spec.source, ["真实业务干扰文档"])
        if path.suffix == ".py":
            body = "\n".join(f"# {line}" for line in evidence)
        else:
            body = "# 真实业务规则\n\n" + "\n".join(f"- {line}" for line in evidence)
        path.write_text(body + "\n", encoding="utf-8")

    first = tmp_path / "release-one"
    second = tmp_path / "release-two"
    first_summary = build_corpus(source_root, first)
    second_summary = build_corpus(source_root, second)

    assert first_summary["documents"] == 33
    assert first_summary["cases"] == 120
    assert first_summary["answerable_cases"] == 90
    assert first_summary["unanswerable_cases"] == 30
    assert tree_hashes(first) == tree_hashes(second)
    manifest = json.loads((first / "documents" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["document_count"] == 33
    assert len(manifest["provenance"]) == 33
    assert all(len(row["output_sha256"]) == 64 for row in manifest["provenance"])
    assert all(
        "source_sha256" in row or all("source_sha256" in source for source in row["sources"])
        for row in manifest["provenance"]
    )
