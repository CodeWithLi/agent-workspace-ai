import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[2]


def load_benchmark_script() -> ModuleType:
    path = ROOT / "scripts" / "benchmark_rag_parsers.py"
    spec = importlib.util.spec_from_file_location("benchmark_rag_parsers", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mineru_v1_content_list_preserves_kind_page_bbox_and_text(tmp_path: Path) -> None:
    module = load_benchmark_script()
    content_list = tmp_path / "sample_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {
                    "type": "text",
                    "text": "Recovery Manual",
                    "text_level": 1,
                    "page_idx": 0,
                    "bbox": [10, 20, 200, 40],
                },
                {
                    "type": "table",
                    "table_body": "<table><td>Restore</td></table>",
                    "page_idx": 1,
                    "bbox": [10, 100, 300, 220],
                },
            ]
        ),
        encoding="utf-8",
    )

    elements = module.mineru_content_list_elements(content_list)

    assert [element.kind for element in elements] == ["title", "table"]
    assert [element.page for element in elements] == [1, 2]
    assert elements[0].bbox == (10.0, 20.0, 200.0, 40.0)
    assert "Restore" in elements[1].content


def test_mineru_v2_content_list_preserves_nested_text(tmp_path: Path) -> None:
    module = load_benchmark_script()
    content_list = tmp_path / "sample_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                [
                    {
                        "type": "title",
                        "content": {
                            "title_content": [
                                {"type": "text", "content": "Quarterly Recovery"}
                            ],
                            "level": 1,
                        },
                        "bbox": [1, 2, 3, 4],
                    }
                ]
            ]
        ),
        encoding="utf-8",
    )

    elements = module.mineru_content_list_elements(content_list)

    assert len(elements) == 1
    assert elements[0].kind == "title"
    assert elements[0].page == 1
    assert "Quarterly Recovery" in elements[0].content


def test_unstructured_tuple_coordinates_are_normalized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_benchmark_script()

    class Metadata:
        def to_dict(self) -> dict:
            return {
                "page_number": 2.0,
                "coordinates": {"points": ((10, 20), (30, 20), (30, 40), (10, 40))},
            }

    class Element:
        category = "Title"
        metadata = Metadata()

        def __str__(self) -> str:
            return "Recovery title"

    unstructured = ModuleType("unstructured")
    partition_package = ModuleType("unstructured.partition")
    auto = ModuleType("unstructured.partition.auto")
    auto.partition = lambda **_kwargs: [Element()]
    monkeypatch.setitem(sys.modules, "unstructured", unstructured)
    monkeypatch.setitem(sys.modules, "unstructured.partition", partition_package)
    monkeypatch.setitem(sys.modules, "unstructured.partition.auto", auto)
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"pdf")

    elements, _version = module.unstructured_elements(source)

    assert elements[0].kind == "title"
    assert elements[0].page == 2
    assert elements[0].bbox == (10.0, 20.0, 30.0, 40.0)


def test_generated_parser_corpus_is_byte_deterministic(tmp_path: Path) -> None:
    module = load_benchmark_script()
    first = tmp_path / "first"
    second = tmp_path / "second"

    module.generate_corpus(first)
    module.generate_corpus(second)
    first_expectations = module.load_expectations(first)
    second_expectations = module.load_expectations(second)

    assert module.corpus_fingerprint(first, first_expectations) == module.corpus_fingerprint(
        second, second_expectations
    )
