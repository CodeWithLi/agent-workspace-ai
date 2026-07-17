from hypothesis import given, settings as hypothesis_settings, strategies as st

from app.rag.chunking import ChunkingConfig, StructuralChunker, TokenCounter
from app.rag.parsers import parse_document_elements


safe_text = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 中文数据库恢复备份向量检索",
    min_size=1,
    max_size=160,
).filter(lambda value: bool(value.strip()))


@given(heading=safe_text, paragraphs=st.lists(safe_text, min_size=1, max_size=12))
@hypothesis_settings(max_examples=35, deadline=None)
def test_structural_chunking_is_deterministic_and_token_bounded_for_unicode(
    heading: str,
    paragraphs: list[str],
) -> None:
    source = f"# {heading.strip()}\n\n" + "\n\n".join(paragraph.strip() for paragraph in paragraphs)
    parsed = parse_document_elements("property.md", source.encode("utf-8"))
    chunker = StructuralChunker(
        ChunkingConfig(child_tokens=96, parent_tokens=240, overlap_tokens=20, min_chunk_tokens=5)
    )

    first = chunker.chunk(parsed)
    second = chunker.chunk(parsed)

    assert first
    assert [chunk.stable_id for chunk in first] == [chunk.stable_id for chunk in second]
    assert [chunk.content for chunk in first] == [chunk.content for chunk in second]
    assert all(0 < chunk.token_count <= chunker.config.child_tokens for chunk in first)
    assert all(chunk.parent_content for chunk in first)
    assert all(chunk.heading_path == (heading.strip(),) for chunk in first)
    assert len({chunk.stable_id for chunk in first}) == len(first)


@given(text=safe_text, tail_tokens=st.integers(min_value=1, max_value=80))
@hypothesis_settings(max_examples=50, deadline=None)
def test_token_tail_never_exceeds_requested_budget(text: str, tail_tokens: int) -> None:
    counter = TokenCounter("cl100k_base")
    tail = counter.tail(text, tail_tokens)

    assert counter.count(tail) <= tail_tokens
    assert counter.count(tail) <= counter.count(text)
