import hashlib

import httpx
import pytest

from app.rag.advanced_parser import DoclingServeParser, parse_document_with_backend
from app.rag.parsers import DocumentParseError


@pytest.mark.asyncio
async def test_docling_serve_parser_converts_markdown_and_rebinds_source_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = b"fake-pdf-content"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/convert/file"
        assert request.headers["X-Api-Key"] == "docling-secret"
        assert b'filename="manual.pdf"' in request.content
        assert b"md" in request.content and b"json" in request.content
        return httpx.Response(
            200,
            json={
                "document": {
                    "md_content": "# Manual\n\n## Recovery\n\nRestore the database.",
                    "json_content": {
                        "schema_name": "DoclingDocument",
                        "body": {},
                        "texts": [],
                        "tables": [],
                    },
                }
            },
        )

    monkeypatch.setattr("app.rag.advanced_parser.settings.docling_serve_url", "https://docling.example")
    monkeypatch.setattr("app.rag.advanced_parser.settings.docling_serve_api_key", "docling-secret")
    parsed = await DoclingServeParser(httpx.MockTransport(handler)).parse("manual.pdf", source)

    assert parsed.filename == "manual.pdf"
    assert parsed.content_hash == hashlib.sha256(source).hexdigest()
    assert parsed.parser_name == "docling-serve"
    assert parsed.parser_version == "1.26-md-v1"
    assert parsed.elements[-1].heading_path == ("Manual", "Recovery")
    assert parsed.metadata["ocr_enabled"] is True


@pytest.mark.asyncio
async def test_docling_failure_uses_explicit_native_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail_parse(*_args, **_kwargs):
        raise DocumentParseError("unavailable")

    monkeypatch.setattr("app.rag.advanced_parser.settings.rag_parser_backend", "docling")
    monkeypatch.setattr("app.rag.advanced_parser.settings.rag_parser_fallback_enabled", True)
    monkeypatch.setattr("app.rag.advanced_parser.docling_parser.parse", fail_parse)

    parsed = await parse_document_with_backend("fallback.md", b"# Fallback\n\nNative parser remains available.")

    assert parsed.parser_name == "markdown-it-py"
    assert parsed.metadata["parser_fallback_from"] == "docling-serve"


@pytest.mark.asyncio
async def test_docling_json_preserves_reading_order_page_bbox_and_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = b"fake-pdf-content"
    json_content = {
        "schema_name": "DoclingDocument",
        "body": {
            "label": "group",
            "children": [
                {"$ref": "#/texts/0"},
                {"$ref": "#/texts/1"},
                {"$ref": "#/tables/0"},
            ],
        },
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "section_header",
                "level": 1,
                "text": "Recovery Manual",
                "prov": [{"page_no": 1, "bbox": {"l": 10, "t": 20, "r": 200, "b": 40}}],
            },
            {
                "self_ref": "#/texts/1",
                "label": "text",
                "text": "Restore PostgreSQL first.",
                "prov": [{"page_no": 1, "bbox": {"l": 10, "t": 50, "r": 250, "b": 80}}],
            },
        ],
        "tables": [
            {
                "self_ref": "#/tables/0",
                "label": "table",
                "prov": [{"page_no": 2, "bbox": {"l": 10, "t": 100, "r": 300, "b": 220}}],
                "data": {
                    "table_cells": [
                        {"start_row_offset_idx": 0, "start_col_offset_idx": 0, "text": "Step"},
                        {"start_row_offset_idx": 0, "start_col_offset_idx": 1, "text": "Owner"},
                        {"start_row_offset_idx": 1, "start_col_offset_idx": 0, "text": "Restore"},
                        {"start_row_offset_idx": 1, "start_col_offset_idx": 1, "text": "DBA"},
                    ]
                },
            }
        ],
        "pictures": [],
        "groups": [],
    }

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "document": {
                    "md_content": "# Recovery Manual\n\nRestore PostgreSQL first.",
                    "json_content": json_content,
                }
            },
        )

    monkeypatch.setattr("app.rag.advanced_parser.settings.docling_serve_url", "https://docling.example")
    parsed = await DoclingServeParser(httpx.MockTransport(handler)).parse("manual.pdf", source)

    assert [element.kind for element in parsed.elements] == ["title", "paragraph", "table"]
    assert parsed.elements[1].heading_path == ("Recovery Manual",)
    assert parsed.elements[-1].page_start == 2
    assert parsed.elements[-1].metadata["bbox"] == [10.0, 100.0, 300.0, 220.0]
    assert "| Step | Owner |" in parsed.elements[-1].content
    assert parsed.metadata["docling_output"] == "json"
    assert parsed.metadata["page_count"] == 2


@pytest.mark.asyncio
async def test_docling_oversized_json_table_falls_back_to_markdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    json_content = {
        "schema_name": "DoclingDocument",
        "body": {"children": [{"$ref": "#/tables/0"}]},
        "texts": [],
        "tables": [
            {
                "self_ref": "#/tables/0",
                "label": "table",
                "data": {
                    "table_cells": [
                        {
                            "start_row_offset_idx": 0,
                            "end_row_offset_idx": 100_001,
                            "start_col_offset_idx": 0,
                            "end_col_offset_idx": 1,
                            "text": "oversized",
                        }
                    ]
                },
            }
        ],
    }
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            json={
                "document": {
                    "md_content": "# Safe fallback\n\nTable JSON was rejected.",
                    "json_content": json_content,
                }
            },
        )
    )
    monkeypatch.setattr("app.rag.advanced_parser.settings.docling_serve_url", "https://docling.example")

    parsed = await DoclingServeParser(transport).parse("oversized.pdf", b"content")

    assert parsed.parser_version == "1.26-md-v1"
    assert parsed.metadata["docling_output"] == "markdown"
    assert parsed.elements[0].content == "Safe fallback"


@pytest.mark.asyncio
async def test_docling_healthcheck_requires_non_empty_conversion(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, json={"document": {"md_content": "# Connection test"}})
    )
    monkeypatch.setattr("app.rag.advanced_parser.settings.docling_serve_url", "https://docling.example")

    await DoclingServeParser(transport).healthcheck()
