from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings
from app.rag.parsers import DocumentParseError, parse_document_elements, rebase_parsed_document
from app.rag.types import DocumentElement, ParsedDocument


logger = logging.getLogger(__name__)
settings = get_settings()


CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
}
DOCLING_JSON_ADAPTER_VERSION = "1.26-json-v1"
DOCLING_MARKDOWN_ADAPTER_VERSION = "1.26-md-v1"


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


def _find_docling_json(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        value = payload.get("json_content")
        if isinstance(value, dict) and value.get("schema_name") == "DoclingDocument":
            return value
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                decoded = None
            if isinstance(decoded, dict) and decoded.get("schema_name") == "DoclingDocument":
                return decoded
        for key in ("document", "documents", "result", "results", "data"):
            if key in payload:
                found = _find_docling_json(payload[key])
                if found:
                    return found
    elif isinstance(payload, list):
        for item in payload:
            found = _find_docling_json(item)
            if found:
                return found
    return None


def _docling_bbox(item: dict[str, Any]) -> tuple[float, float, float, float] | None:
    provenance = item.get("prov")
    if not isinstance(provenance, list):
        return None
    for entry in provenance:
        bbox = entry.get("bbox") if isinstance(entry, dict) else None
        if isinstance(bbox, dict) and all(isinstance(bbox.get(key), (int, float)) for key in ("l", "t", "r", "b")):
            return (float(bbox["l"]), float(bbox["t"]), float(bbox["r"]), float(bbox["b"]))
        if isinstance(bbox, list) and len(bbox) == 4 and all(isinstance(value, (int, float)) for value in bbox):
            return tuple(float(value) for value in bbox)
    return None


def _docling_pages(item: dict[str, Any]) -> tuple[int | None, int | None]:
    provenance = item.get("prov")
    pages = [
        int(entry["page_no"])
        for entry in provenance if isinstance(entry, dict) and isinstance(entry.get("page_no"), int)
    ] if isinstance(provenance, list) else []
    return (min(pages), max(pages)) if pages else (None, None)


def _docling_table_markdown(item: dict[str, Any]) -> str:
    data = item.get("data")
    cells = data.get("table_cells") if isinstance(data, dict) else None
    if not isinstance(cells, list) or not cells:
        return ""
    row_count = max(
        (
            int(
                cell.get(
                    "end_row_offset_idx",
                    int(cell.get("start_row_offset_idx", 0))
                    + max(int(cell.get("row_span", 1)), 1),
                )
            )
            for cell in cells
            if isinstance(cell, dict)
        ),
        default=0,
    )
    column_count = max(
        (
            int(
                cell.get(
                    "end_col_offset_idx",
                    int(cell.get("start_col_offset_idx", 0))
                    + max(int(cell.get("col_span", 1)), 1),
                )
            )
            for cell in cells
            if isinstance(cell, dict)
        ),
        default=0,
    )
    if not row_count or not column_count:
        return ""
    if row_count > 1000 or column_count > 1000 or row_count * column_count > 100_000:
        raise DocumentParseError("Docling table dimensions exceed parser limits")
    rows = [["" for _column in range(column_count)] for _row in range(row_count)]
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        row = int(cell.get("start_row_offset_idx", 0))
        column = int(cell.get("start_col_offset_idx", 0))
        if 0 <= row < row_count and 0 <= column < column_count:
            rows[row][column] = str(cell.get("text", "")).strip().replace("|", "\\|")
    header = "| " + " | ".join(rows[0]) + " |"
    separator = "| " + " | ".join("---" for _column in range(column_count)) + " |"
    body = ["| " + " | ".join(row) + " |" for row in rows[1:]]
    return "\n".join([header, separator, *body])


def _parsed_from_docling_json(
    filename: str,
    data: bytes,
    document: dict[str, Any],
    *,
    parser_version: str,
) -> ParsedDocument:
    objects: dict[str, dict[str, Any]] = {}
    for collection_name in ("texts", "tables", "pictures", "key_value_items", "form_items", "groups"):
        collection = document.get(collection_name)
        if not isinstance(collection, list):
            continue
        for item in collection:
            if isinstance(item, dict) and isinstance(item.get("self_ref"), str):
                objects[item["self_ref"]] = item
    if len(objects) > settings.rag_max_elements:
        raise DocumentParseError("Docling JSON contains too many document elements")

    ordered: list[dict[str, Any]] = []
    visited: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict) and isinstance(value.get("$ref"), str):
            reference = value["$ref"]
            if reference in visited:
                return
            visited.add(reference)
            target = objects.get(reference)
            if target is not None:
                walk(target)
            return
        if not isinstance(value, dict):
            return
        children = value.get("children")
        label = str(value.get("label", ""))
        if label == "group" or (isinstance(children, list) and not value.get("text") and not value.get("data")):
            if isinstance(children, list):
                for child in children:
                    walk(child)
            return
        ordered.append(value)
        if isinstance(children, list):
            for child in children:
                walk(child)

    walk(document.get("body", {}))
    for reference, item in objects.items():
        if reference not in visited:
            walk({"$ref": reference})

    content_hash = hashlib.sha256(data).hexdigest()
    headings: list[str] = []
    elements: list[DocumentElement] = []
    text_parts: list[str] = []
    cursor = 0
    furniture_labels = {"page_header", "page_footer", "page_number"}
    for item in ordered:
        label = str(item.get("label", "text"))
        if label in furniture_labels:
            continue
        content = _docling_table_markdown(item) if label == "table" else str(item.get("text") or item.get("orig") or "").strip()
        if not content:
            continue
        if label in {"title", "section_header"}:
            kind = "title"
            level = max(1, int(item.get("level", 1) or 1))
            headings = headings[: level - 1]
            headings.append(content)
        elif label == "table":
            kind = "table"
        elif label in {"code", "formula"}:
            kind = "code"
        elif label in {"list_item", "list"}:
            kind = "list_item"
        else:
            kind = "paragraph"
        if text_parts:
            cursor += 2
        char_start = cursor
        cursor += len(content)
        page_start, page_end = _docling_pages(item)
        bbox = _docling_bbox(item)
        element_index = len(elements)
        stable_source = "\x1f".join(
            str(part) for part in (content_hash, element_index, kind, page_start, "/".join(headings), content)
        )
        metadata: dict[str, Any] = {"docling_label": label}
        if bbox is not None:
            metadata["bbox"] = list(bbox)
        if isinstance(item.get("prov"), list):
            metadata["provenance"] = item["prov"]
        elements.append(
            DocumentElement(
                stable_id=hashlib.sha256(stable_source.encode("utf-8")).hexdigest(),
                element_index=element_index,
                kind=kind,
                content=content,
                heading_path=tuple(headings),
                page_start=page_start,
                page_end=page_end,
                char_start=char_start,
                char_end=cursor,
                metadata=metadata,
            )
        )
        text_parts.append(content)
    if not elements:
        raise DocumentParseError("Docling JSON output contains no readable elements")
    pages = [element.page_end for element in elements if element.page_end is not None]
    return ParsedDocument(
        filename=filename,
        content_hash=content_hash,
        text="\n\n".join(text_parts),
        elements=tuple(elements),
        parser_name="docling-serve",
        parser_version=parser_version,
        metadata={
            "docling_output": "json",
            "ocr_enabled": settings.docling_do_ocr,
            "page_count": max(pages, default=0),
        },
    )


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
                        "to_formats": ["md", "json"],
                        "ocr": str(settings.docling_do_ocr).lower(),
                        "table_mode": "accurate",
                        "abort_on_error": "true",
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise DocumentParseError("Docling Serve document conversion failed") from exc
        markdown = _find_markdown(payload)
        json_content = _find_docling_json(payload)
        if json_content:
            try:
                return _parsed_from_docling_json(
                    filename,
                    data,
                    json_content,
                    parser_version=DOCLING_JSON_ADAPTER_VERSION,
                )
            except (DocumentParseError, TypeError, ValueError, OverflowError):
                if not markdown:
                    raise DocumentParseError("Docling JSON output is invalid")
                logger.warning("Docling JSON adaptation failed; using Markdown output", exc_info=True)
        if not markdown:
            raise DocumentParseError("Docling Serve response contains no Markdown output")
        parsed = parse_document_elements(f"{Path(filename).stem}.md", markdown.encode("utf-8"))
        return rebase_parsed_document(
            parsed,
            filename=filename,
            content_hash=hashlib.sha256(data).hexdigest(),
            parser_name="docling-serve",
            parser_version=DOCLING_MARKDOWN_ADAPTER_VERSION,
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
