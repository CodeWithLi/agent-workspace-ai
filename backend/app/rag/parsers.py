from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, replace
from io import BytesIO
from pathlib import Path
from typing import Any

from app.rag.types import DocumentElement, ParsedDocument


class DocumentParseError(ValueError):
    pass


@dataclass(slots=True)
class _ElementDraft:
    kind: str
    content: str
    heading_path: tuple[str, ...] = ()
    page_start: int | None = None
    page_end: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def _stable_hash(*parts: object) -> str:
    source = "\x1f".join(str(part) for part in parts)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _assemble(
    filename: str,
    content_hash: str,
    parser_name: str,
    parser_version: str,
    drafts: list[_ElementDraft],
    metadata: dict[str, Any] | None = None,
) -> ParsedDocument:
    elements: list[DocumentElement] = []
    text_parts: list[str] = []
    cursor = 0
    for draft in drafts:
        content = draft.content.strip()
        if not content:
            continue
        if text_parts:
            cursor += 2
        char_start = cursor
        cursor += len(content)
        element_index = len(elements)
        elements.append(
            DocumentElement(
                stable_id=_stable_hash(
                    content_hash,
                    element_index,
                    draft.kind,
                    draft.page_start,
                    "/".join(draft.heading_path),
                    content,
                ),
                element_index=element_index,
                kind=draft.kind,
                content=content,
                heading_path=draft.heading_path,
                page_start=draft.page_start,
                page_end=draft.page_end,
                char_start=char_start,
                char_end=cursor,
                metadata=draft.metadata,
            )
        )
        text_parts.append(content)
    return ParsedDocument(
        filename=filename,
        content_hash=content_hash,
        text="\n\n".join(text_parts),
        elements=tuple(elements),
        parser_name=parser_name,
        parser_version=parser_version,
        metadata=metadata or {},
    )


def _paragraph_drafts(text: str, *, page: int | None = None) -> list[_ElementDraft]:
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    if not blocks and text.strip():
        blocks = [text.strip()]
    return [
        _ElementDraft(kind="paragraph", content=block, page_start=page, page_end=page)
        for block in blocks
    ]


def _parse_pdf(filename: str, data: bytes, content_hash: str) -> ParsedDocument:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data))
    drafts: list[_ElementDraft] = []
    for page_number, page in enumerate(reader.pages, start=1):
        drafts.extend(_paragraph_drafts(page.extract_text() or "", page=page_number))
    pdf_metadata = {
        str(key).lstrip("/"): str(value)
        for key, value in (reader.metadata or {}).items()
        if value is not None
    }
    pdf_metadata["page_count"] = len(reader.pages)
    return _assemble(filename, content_hash, "pypdf", "5", drafts, pdf_metadata)


def _heading_level(style_name: str) -> int | None:
    match = re.match(r"heading\s+(\d+)$", style_name.strip(), re.IGNORECASE)
    return int(match.group(1)) if match else None


def _table_to_markdown(table: Any) -> str:
    rows = [[cell.text.strip().replace("|", "\\|") for cell in row.cells] for row in table.rows]
    rows = [row for row in rows if any(row)]
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    header = "| " + " | ".join(normalized[0]) + " |"
    separator = "| " + " | ".join(["---"] * width) + " |"
    body = ["| " + " | ".join(row) + " |" for row in normalized[1:]]
    return "\n".join([header, separator, *body])


def _parse_docx(filename: str, data: bytes, content_hash: str) -> ParsedDocument:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = Document(BytesIO(data))
    drafts: list[_ElementDraft] = []
    headings: list[str] = []
    for block in document.iter_inner_content():
        if isinstance(block, Paragraph):
            content = block.text.strip()
            if not content:
                continue
            style_name = block.style.name if block.style else ""
            level = _heading_level(style_name)
            if level is not None:
                headings = headings[: level - 1]
                headings.append(content)
                drafts.append(
                    _ElementDraft(
                        kind="title",
                        content=content,
                        heading_path=tuple(headings),
                        metadata={"level": level, "style": style_name},
                    )
                )
                continue
            kind = "list_item" if style_name.lower().startswith("list") else "paragraph"
            drafts.append(
                _ElementDraft(
                    kind=kind,
                    content=content,
                    heading_path=tuple(headings),
                    metadata={"style": style_name} if style_name else {},
                )
            )
        elif isinstance(block, Table):
            drafts.append(
                _ElementDraft(
                    kind="table",
                    content=_table_to_markdown(block),
                    heading_path=tuple(headings),
                    metadata={"rows": len(block.rows), "columns": max((len(row.cells) for row in block.rows), default=0)},
                )
            )
    properties = document.core_properties
    metadata = {
        "title": properties.title or "",
        "subject": properties.subject or "",
        "author": properties.author or "",
    }
    return _assemble(filename, content_hash, "python-docx", "1.2", drafts, metadata)


def _line_offsets(text: str) -> tuple[list[str], list[int]]:
    lines = text.splitlines()
    offsets: list[int] = []
    cursor = 0
    for line in text.splitlines(keepends=True):
        offsets.append(cursor)
        cursor += len(line)
    if len(offsets) < len(lines):
        offsets.append(cursor)
    return lines, offsets


def _parse_markdown(filename: str, data: bytes, content_hash: str) -> ParsedDocument:
    from markdown_it import MarkdownIt

    text = data.decode("utf-8-sig")
    lines, offsets = _line_offsets(text)
    tokens = MarkdownIt("commonmark").enable("table").parse(text)
    drafts: list[_ElementDraft] = []
    headings: list[str] = []
    list_depth = 0
    skip_until = -1
    for index, token in enumerate(tokens):
        if token.type == "list_item_open":
            list_depth += 1
            continue
        if token.type == "list_item_close":
            list_depth = max(0, list_depth - 1)
            continue
        if index <= skip_until or not token.map:
            continue
        start_line, end_line = token.map
        raw = "\n".join(lines[start_line:end_line]).strip()
        source_start = offsets[start_line] if start_line < len(offsets) else 0
        source_end = source_start + len(raw)
        source_metadata = {"source_start": source_start, "source_end": source_end}
        if token.type == "heading_open":
            level = int(token.tag[1:])
            title = tokens[index + 1].content.strip() if index + 1 < len(tokens) else raw.lstrip("# ")
            headings = headings[: level - 1]
            headings.append(title)
            drafts.append(
                _ElementDraft(
                    kind="title",
                    content=title,
                    heading_path=tuple(headings),
                    metadata={**source_metadata, "level": level},
                )
            )
        elif token.type in {"fence", "code_block"}:
            drafts.append(
                _ElementDraft(
                    kind="code",
                    content=raw,
                    heading_path=tuple(headings),
                    metadata={**source_metadata, "language": token.info.strip()},
                )
            )
        elif token.type == "table_open":
            close_index = next(
                (position for position in range(index + 1, len(tokens)) if tokens[position].type == "table_close"),
                index,
            )
            skip_until = close_index
            drafts.append(
                _ElementDraft(
                    kind="table",
                    content=raw,
                    heading_path=tuple(headings),
                    metadata=source_metadata,
                )
            )
        elif token.type == "paragraph_open":
            drafts.append(
                _ElementDraft(
                    kind="list_item" if list_depth else "paragraph",
                    content=raw,
                    heading_path=tuple(headings),
                    metadata=source_metadata,
                )
            )
    return _assemble(filename, content_hash, "markdown-it-py", "3", drafts)


def _parse_text(filename: str, data: bytes, content_hash: str) -> ParsedDocument:
    text = data.decode("utf-8-sig")
    return _assemble(filename, content_hash, "plain-text", "1", _paragraph_drafts(text))


def parse_document_elements(filename: str, data: bytes) -> ParsedDocument:
    suffix = Path(filename).suffix.lower()
    content_hash = hashlib.sha256(data).hexdigest()
    try:
        if suffix == ".pdf":
            return _parse_pdf(filename, data, content_hash)
        if suffix == ".docx":
            return _parse_docx(filename, data, content_hash)
        if suffix in {".md", ".markdown"}:
            return _parse_markdown(filename, data, content_hash)
        if suffix == ".txt":
            return _parse_text(filename, data, content_hash)
    except (UnicodeDecodeError, ValueError) as exc:
        raise DocumentParseError("文件解析失败，请确认文件未损坏且编码正确") from exc
    except Exception as exc:
        raise DocumentParseError(f"{suffix or '未知格式'} 文档解析失败") from exc
    raise DocumentParseError(f"不支持的文档格式：{suffix or '无扩展名'}")


def rebase_parsed_document(
    parsed: ParsedDocument,
    *,
    filename: str,
    content_hash: str,
    parser_name: str,
    parser_version: str,
    metadata: dict[str, Any] | None = None,
) -> ParsedDocument:
    elements = tuple(
        replace(
            element,
            stable_id=_stable_hash(
                content_hash,
                element.element_index,
                element.kind,
                element.page_start,
                "/".join(element.heading_path),
                element.content,
            ),
        )
        for element in parsed.elements
    )
    return replace(
        parsed,
        filename=filename,
        content_hash=content_hash,
        elements=elements,
        parser_name=parser_name,
        parser_version=parser_version,
        metadata={**parsed.metadata, **(metadata or {})},
    )
