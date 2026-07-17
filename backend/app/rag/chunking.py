from __future__ import annotations

import hashlib
from dataclasses import dataclass

import tiktoken
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.types import DocumentElement, KnowledgeChunk, ParsedDocument


SEPARATORS = [
    "\n\n",
    "\n",
    "。",
    "！",
    "？",
    "；",
    ". ",
    "! ",
    "? ",
    "; ",
    "，",
    ", ",
    " ",
    "",
]
PROMPT_INJECTION_PATTERNS = (
    "ignore previous instructions",
    "ignore all instructions",
    "system prompt",
    "developer message",
    "忽略之前的指令",
    "忽略以上指令",
    "你现在是",
    "</document>",
)


@dataclass(slots=True, frozen=True)
class ChunkingConfig:
    child_tokens: int = 400
    parent_tokens: int = 1200
    overlap_tokens: int = 60
    min_chunk_tokens: int = 30
    encoding_name: str = "cl100k_base"
    include_heading_context: bool = True

    def __post_init__(self) -> None:
        if self.child_tokens < 64:
            raise ValueError("child_tokens must be at least 64")
        if self.parent_tokens < self.child_tokens:
            raise ValueError("parent_tokens must not be smaller than child_tokens")
        if self.overlap_tokens < 0 or self.overlap_tokens >= self.child_tokens:
            raise ValueError("overlap_tokens must be smaller than child_tokens")
        if self.min_chunk_tokens < 1 or self.min_chunk_tokens > self.child_tokens:
            raise ValueError("min_chunk_tokens must be within the child token budget")


@dataclass(slots=True, frozen=True)
class _Segment:
    content: str
    elements: tuple[DocumentElement, ...]
    overlap: bool = False


class TokenCounter:
    def __init__(self, encoding_name: str) -> None:
        self.encoding = tiktoken.get_encoding(encoding_name)

    def count(self, text: str) -> int:
        return len(self.encoding.encode(text, disallowed_special=()))

    def tail(self, text: str, tokens: int) -> str:
        if tokens <= 0:
            return ""
        encoded = self.encoding.encode(text, disallowed_special=())
        return self.encoding.decode(encoded[-tokens:]).strip()


def _hash(*parts: object) -> str:
    source = "\x1f".join(str(part) for part in parts)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


class StructuralChunker:
    name = "structural-parent-child"
    version = "1"

    def __init__(self, config: ChunkingConfig | None = None) -> None:
        self.config = config or ChunkingConfig()
        self.tokens = TokenCounter(self.config.encoding_name)
    def chunk(self, document: ParsedDocument) -> list[KnowledgeChunk]:
        chunks: list[KnowledgeChunk] = []
        for heading_path, elements in self._sections(document.elements):
            base_segments = self._segments(elements, heading_path)
            for parent_segments in self._pack(base_segments, self.config.parent_tokens, 0, heading_path):
                parent_content = self._render(parent_segments, heading_path)
                parent_id = _hash(document.content_hash, "parent", heading_path, parent_content)
                child_groups = self._pack(
                    parent_segments,
                    self.config.child_tokens,
                    self.config.overlap_tokens,
                    heading_path,
                )
                for child_position, group in enumerate(child_groups):
                    content = self._render(group, heading_path)
                    elements_in_group = self._unique_elements(group)
                    chunk_index = len(chunks)
                    chunks.append(
                        KnowledgeChunk(
                            stable_id=_hash(document.content_hash, "child", parent_id, child_position, content),
                            chunk_index=chunk_index,
                            content=content,
                            parent_stable_id=parent_id,
                            parent_content=parent_content,
                            token_count=self.tokens.count(content),
                            element_ids=tuple(element.stable_id for element in elements_in_group),
                            element_indexes=tuple(element.element_index for element in elements_in_group),
                            element_kinds=tuple(sorted({element.kind for element in elements_in_group})),
                            heading_path=heading_path,
                            page_start=self._page_start(elements_in_group),
                            page_end=self._page_end(elements_in_group),
                            char_start=min((element.char_start for element in elements_in_group), default=0),
                            char_end=max((element.char_end for element in elements_in_group), default=0),
                            metadata={
                                "chunker": self.name,
                                "chunker_version": self.version,
                                "has_overlap": any(segment.overlap for segment in group),
                                "prompt_injection_suspected": any(
                                    pattern in content.lower() for pattern in PROMPT_INJECTION_PATTERNS
                                ),
                            },
                        )
                    )
        return chunks

    def _sections(
        self, elements: tuple[DocumentElement, ...]
    ) -> list[tuple[tuple[str, ...], tuple[DocumentElement, ...]]]:
        sections: list[tuple[tuple[str, ...], tuple[DocumentElement, ...]]] = []
        current_path: tuple[str, ...] | None = None
        current: list[DocumentElement] = []
        pending_title: DocumentElement | None = None
        for element in elements:
            if element.kind == "title":
                if current:
                    sections.append((current_path or (), tuple(current)))
                    current = []
                current_path = element.heading_path
                pending_title = element
                continue
            if current_path is None:
                current_path = element.heading_path
            if element.heading_path != current_path and current:
                sections.append((current_path, tuple(current)))
                current = []
                current_path = element.heading_path
            current.append(element)
            pending_title = None
        if current:
            sections.append((current_path or (), tuple(current)))
        elif pending_title is not None:
            sections.append((pending_title.heading_path, (pending_title,)))
        return sections

    def _segments(
        self,
        elements: tuple[DocumentElement, ...],
        heading_path: tuple[str, ...],
    ) -> list[_Segment]:
        segments: list[_Segment] = []
        heading_budget = self.tokens.count(self._heading_prefix(heading_path))
        content_budget = max(1, self.config.child_tokens - heading_budget)
        splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
            encoding_name=self.config.encoding_name,
            chunk_size=content_budget,
            chunk_overlap=0,
            separators=SEPARATORS,
            keep_separator="end",
            strip_whitespace=True,
        )
        for element in elements:
            content = element.content.strip()
            if self.tokens.count(content) + heading_budget <= self.config.child_tokens:
                segments.append(_Segment(content, (element,)))
                continue
            pieces = splitter.split_text(content)
            segments.extend(_Segment(piece, (element,)) for piece in pieces if piece.strip())
        return segments

    def _pack(
        self,
        segments: list[_Segment],
        limit: int,
        overlap_tokens: int,
        heading_path: tuple[str, ...],
    ) -> list[list[_Segment]]:
        groups: list[list[_Segment]] = []
        current: list[_Segment] = []
        for segment in segments:
            candidate = [*current, segment]
            if current and self.tokens.count(self._render(candidate, heading_path)) > limit:
                groups.append(current)
                overlap = self.tokens.tail(self._body(current), overlap_tokens)
                current = [_Segment(overlap, current[-1].elements, overlap=True)] if overlap else []
                if current and self.tokens.count(self._render([*current, segment], heading_path)) > limit:
                    current = []
            current.append(segment)
        if current:
            groups.append(current)
        return self._merge_small_tail(groups, limit, heading_path)

    def _merge_small_tail(
        self,
        groups: list[list[_Segment]],
        limit: int,
        heading_path: tuple[str, ...],
    ) -> list[list[_Segment]]:
        if len(groups) < 2:
            return groups
        tail = groups[-1]
        if self.tokens.count(self._render(tail, heading_path)) >= self.config.min_chunk_tokens:
            return groups
        merged = [*groups[-2], *tail]
        if self.tokens.count(self._render(merged, heading_path)) <= limit:
            return [*groups[:-2], merged]
        return groups

    def _render(self, segments: list[_Segment], heading_path: tuple[str, ...]) -> str:
        body = self._body(segments)
        return f"{self._heading_prefix(heading_path)}{body}"

    def _heading_prefix(self, heading_path: tuple[str, ...]) -> str:
        if self.config.include_heading_context and heading_path:
            return f"标题路径：{' / '.join(heading_path)}\n\n"
        return ""

    @staticmethod
    def _body(segments: list[_Segment]) -> str:
        return "\n\n".join(segment.content.strip() for segment in segments if segment.content.strip())

    @staticmethod
    def _unique_elements(segments: list[_Segment]) -> tuple[DocumentElement, ...]:
        by_id: dict[str, DocumentElement] = {}
        for segment in segments:
            for element in segment.elements:
                by_id.setdefault(element.stable_id, element)
        return tuple(sorted(by_id.values(), key=lambda item: item.element_index))

    @staticmethod
    def _page_start(elements: tuple[DocumentElement, ...]) -> int | None:
        pages = [element.page_start for element in elements if element.page_start is not None]
        return min(pages) if pages else None

    @staticmethod
    def _page_end(elements: tuple[DocumentElement, ...]) -> int | None:
        pages = [element.page_end for element in elements if element.page_end is not None]
        return max(pages) if pages else None
