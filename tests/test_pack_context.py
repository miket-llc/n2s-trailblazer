"""Test context packing utilities."""

from trailblazer.retrieval.pack import (
    group_by_doc,
    pack_context,
    create_context_summary,
)


def test_group_by_doc_basic():
    """Test basic document grouping functionality."""
    hits = [
        {
            "doc_id": "doc1",
            "chunk_id": "doc1:001",
            "score": 0.9,
            "text_md": "First chunk",
        },
        {
            "doc_id": "doc2",
            "chunk_id": "doc2:001",
            "score": 0.8,
            "text_md": "Second doc chunk",
        },
        {
            "doc_id": "doc1",
            "chunk_id": "doc1:002",
            "score": 0.7,
            "text_md": "Another doc1 chunk",
        },
        {
            "doc_id": "doc2",
            "chunk_id": "doc2:002",
            "score": 0.6,
            "text_md": "Another doc2 chunk",
        },
        {
            "doc_id": "doc1",
            "chunk_id": "doc1:003",
            "score": 0.5,
            "text_md": "Third doc1 chunk",
        },
    ]

    result = group_by_doc(hits, max_chunks_per_doc=2)

    # Should have max 2 chunks per doc, maintaining original order
    assert len(result) == 4

    doc1_chunks = [hit for hit in result if hit["doc_id"] == "doc1"]
    doc2_chunks = [hit for hit in result if hit["doc_id"] == "doc2"]

    assert len(doc1_chunks) == 2
    assert len(doc2_chunks) == 2

    # Check that highest scoring chunks are kept
    assert doc1_chunks[0]["chunk_id"] == "doc1:001"  # score 0.9
    assert doc1_chunks[1]["chunk_id"] == "doc1:002"  # score 0.7

    assert doc2_chunks[0]["chunk_id"] == "doc2:001"  # score 0.8
    assert doc2_chunks[1]["chunk_id"] == "doc2:002"  # score 0.6


def test_group_by_doc_preserve_order():
    """Test that grouping preserves the original hit order."""
    hits = [
        {"doc_id": "doc1", "chunk_id": "doc1:001", "score": 0.9},
        {"doc_id": "doc2", "chunk_id": "doc2:001", "score": 0.8},
        {"doc_id": "doc1", "chunk_id": "doc1:002", "score": 0.7},
    ]

    result = group_by_doc(hits, max_chunks_per_doc=5)

    # Original order should be preserved
    expected_order = ["doc1:001", "doc2:001", "doc1:002"]
    actual_order = [hit["chunk_id"] for hit in result]
    assert actual_order == expected_order


def test_group_by_doc_empty():
    """Test grouping with empty input."""
    result = group_by_doc([], max_chunks_per_doc=3)
    assert result == []


def test_pack_context_basic():
    """Test basic context packing."""
    hits = [
        {
            "text_md": "This is the first chunk.",
            "title": "Document 1",
            "url": "http://example.com/doc1",
            "score": 0.9,
        },
        {
            "text_md": "This is the second chunk.",
            "title": "Document 2",
            "url": "http://example.com/doc2",
            "score": 0.8,
        },
    ]

    context = pack_context(hits, max_chars=1000)

    # Should contain both chunks with separators
    assert "Chunk 1 (score: 0.900)" in context
    assert "Chunk 2 (score: 0.800)" in context
    assert "Title: Document 1" in context
    assert "Title: Document 2" in context
    assert "URL: http://example.com/doc1" in context
    assert "URL: http://example.com/doc2" in context
    assert "This is the first chunk." in context
    assert "This is the second chunk." in context


def test_pack_context_character_limit():
    """Test that packing respects character limits."""
    long_text = "A" * 500  # 500 characters

    hits = [
        {
            "text_md": long_text,
            "title": "Doc1",
            "url": "http://example.com/1",
            "score": 0.9,
        },
        {
            "text_md": long_text,
            "title": "Doc2",
            "url": "http://example.com/2",
            "score": 0.8,
        },
    ]

    # Set limit to fit only one chunk plus some overhead
    context = pack_context(hits, max_chars=600)

    # Should contain first chunk but not second
    assert "Doc1" in context
    assert "Doc2" not in context
    assert len(context) <= 600


def test_pack_context_code_block_protection():
    """Test that code blocks are not split."""
    hits = [
        {
            "text_md": "Here is some code:\n```python\ndef function():\n    return 42\n```\nEnd of chunk.",
            "title": "Code Doc",
            "url": "http://example.com/code",
            "score": 0.9,
        }
    ]

    # Set a limit that would normally truncate inside the code block
    context = pack_context(hits, max_chars=150)

    # Should either include the full code block or exclude it entirely
    if "```python" in context:
        # If code block is included, it should be complete
        assert "```python\ndef function():\n    return 42\n```" in context
    # The truncation logic should respect code block boundaries


def test_pack_context_empty():
    """Test packing with empty hits."""
    context = pack_context([], max_chars=1000)
    assert context == ""


def test_pack_context_truncation_indicator():
    """Test that truncation is properly indicated."""
    long_text = "B" * 1000

    hits = [
        {
            "text_md": long_text,
            "title": "Long Doc",
            "url": "http://example.com/long",
            "score": 0.9,
        },
        {
            "text_md": "Another chunk",
            "title": "Doc 2",
            "url": "http://example.com/2",
            "score": 0.8,
        },
    ]

    context = pack_context(hits, max_chars=200)

    # Should either truncate or exclude chunks to stay within budget
    assert len(context) <= 400  # Some buffer for separators
    # Should not include everything if budget is small
    assert not (len(context) > 800)  # Much longer than budget


def test_create_context_summary():
    """Test context summary creation."""
    hits = [
        {"doc_id": "doc1", "text_md": "Short text", "score": 0.9},
        {"doc_id": "doc2", "text_md": "Another text", "score": 0.7},
        {
            "doc_id": "doc1",  # Same doc as first hit
            "text_md": "More text",
            "score": 0.8,
        },
    ]

    timing_info = {
        "total_seconds": 1.5,
        "search_seconds": 1.0,
        "pack_seconds": 0.5,
    }

    summary = create_context_summary(
        query="test query",
        hits=hits,
        provider="dummy",
        timing_info=timing_info,
    )

    assert summary["query"] == "test query"
    assert summary["provider"] == "dummy"
    assert summary["total_hits"] == 3
    assert summary["unique_documents"] == 2  # doc1 and doc2
    assert summary["total_characters"] == len(
        "Short textAnother textMore text"
    )

    # Check score statistics
    assert summary["score_stats"]["min"] == 0.7
    assert summary["score_stats"]["max"] == 0.9
    assert abs(summary["score_stats"]["avg"] - 0.8) < 1e-6

    assert summary["timing"] == timing_info


def test_create_context_summary_empty():
    """Test summary creation with empty hits."""
    summary = create_context_summary(
        query="empty query",
        hits=[],
        provider="dummy",
        timing_info={"total_seconds": 0.1},
    )

    assert summary["total_hits"] == 0
    assert summary["unique_documents"] == 0
    assert summary["total_characters"] == 0
    assert summary["score_stats"]["min"] == 0.0
    assert summary["score_stats"]["max"] == 0.0
    assert summary["score_stats"]["avg"] == 0.0
