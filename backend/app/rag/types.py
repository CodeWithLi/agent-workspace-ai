from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class DocumentElement:
    stable_id: str
    element_index: int
    kind: str
    content: str
    heading_path: tuple[str, ...] = ()
    page_start: int | None = None
    page_end: int | None = None
    char_start: int = 0
    char_end: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ParsedDocument:
    filename: str
    content_hash: str
    text: str
    elements: tuple[DocumentElement, ...]
    parser_name: str
    parser_version: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class KnowledgeChunk:
    stable_id: str
    chunk_index: int
    content: str
    parent_stable_id: str
    parent_content: str
    token_count: int
    element_ids: tuple[str, ...]
    element_indexes: tuple[int, ...]
    element_kinds: tuple[str, ...]
    heading_path: tuple[str, ...] = ()
    page_start: int | None = None
    page_end: int | None = None
    char_start: int = 0
    char_end: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
