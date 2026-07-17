from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings
from app.rag.parsers import DocumentParseError, parse_document_elements, rebase_parsed_document
from app.rag.types import ParsedDocument


logger = logging.getLogger(__name__)
settings = get_settings()


CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
}


def _find_markdown(payload: Any) -> str | None:
    if isinstance(payload, dict):
        for key in ("md_content", "markdown", "markdown_content"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
        for key in ("document", "documents", "result", "results", "data"):
            if key in payload:
                found = _find_markdown(payload[key])
                if found:
                    return found
    elif isinstance(payload, list):
        for item in payload:
            found = _find_markdown(item)
            if found:
                return found
    return None


class DoclingServeParser:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.transport = transport

    async def parse(self, filename: str, data: bytes) -> ParsedDocument:
        if not settings.docling_serve_url:
            raise DocumentParseError("Docling Serve URL is not configured")
        endpoint = settings.docling_serve_url.rstrip("/") + "/v1/convert/file"
        headers = {"Accept": "application/json"}
        if settings.docling_serve_api_key:
            headers["X-Api-Key"] = settings.docling_serve_api_key
        suffix = Path(filename).suffix.lower()
        try:
            async with httpx.AsyncClient(
                timeout=settings.docling_timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.post(
                    endpoint,
                    headers=headers,
                    files={"files": (filename, data, CONTENT_TYPES.get(suffix, "application/octet-stream"))},
                    data={
                        "to_formats": "md",
                        "do_ocr": str(settings.docling_do_ocr).lower(),
                        "do_table_structure": "true",
                        "table_mode": "accurate",
                        "abort_on_error": "true",
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise DocumentParseError("Docling Serve document conversion failed") from exc
        markdown = _find_markdown(payload)
        if not markdown:
            raise DocumentParseError("Docling Serve response contains no Markdown output")
        parsed = parse_document_elements(f"{Path(filename).stem}.md", markdown.encode("utf-8"))
        return rebase_parsed_document(
            parsed,
            filename=filename,
            content_hash=hashlib.sha256(data).hexdigest(),
            parser_name="docling-serve",
            parser_version="1.26",
            metadata={"docling_output": "markdown", "ocr_enabled": settings.docling_do_ocr},
        )

    async def healthcheck(self) -> None:
        parsed = await self.parse("connection-test.md", b"# Connection test")
        if not parsed.elements:
            raise RuntimeError("Docling Serve returned an empty conversion")


docling_parser = DoclingServeParser()


async def parse_document_with_backend(filename: str, data: bytes) -> ParsedDocument:
    backend = settings.rag_parser_backend
    use_docling = backend == "docling" or (backend == "auto" and bool(settings.docling_serve_url))
    if use_docling:
        try:
            return await docling_parser.parse(filename, data)
        except DocumentParseError:
            if not settings.rag_parser_fallback_enabled:
                raise
            logger.warning("Docling parsing failed; using native parser", exc_info=True)
            parsed = parse_document_elements(filename, data)
            return rebase_parsed_document(
                parsed,
                filename=filename,
                content_hash=parsed.content_hash,
                parser_name=parsed.parser_name,
                parser_version=parsed.parser_version,
                metadata={"parser_fallback_from": "docling-serve"},
            )
    return parse_document_elements(filename, data)
