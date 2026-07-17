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
        return httpx.Response(
            200,
            json={"document": {"md_content": "# Manual\n\n## Recovery\n\nRestore the database."}},
        )

    monkeypatch.setattr("app.rag.advanced_parser.settings.docling_serve_url", "https://docling.example")
    monkeypatch.setattr("app.rag.advanced_parser.settings.docling_serve_api_key", "docling-secret")
    parsed = await DoclingServeParser(httpx.MockTransport(handler)).parse("manual.pdf", source)

    assert parsed.filename == "manual.pdf"
    assert parsed.content_hash == hashlib.sha256(source).hexdigest()
    assert parsed.parser_name == "docling-serve"
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
async def test_docling_healthcheck_requires_non_empty_conversion(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, json={"document": {"md_content": "# Connection test"}})
    )
    monkeypatch.setattr("app.rag.advanced_parser.settings.docling_serve_url", "https://docling.example")

    await DoclingServeParser(transport).healthcheck()
