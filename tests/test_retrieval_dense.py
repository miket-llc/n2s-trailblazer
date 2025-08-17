"""Tests for dense retrieval functionality."""

from unittest.mock import patch, MagicMock

import pytest

from trailblazer.pipeline.steps.retrieve.retriever import (
    DenseRetriever,
    SearchHit,
    pack_context,
)


@pytest.fixture
def sample_hits():
    """Sample search hits for testing."""
    return [
        SearchHit(
            chunk_id="doc1:0000",
            doc_id="doc1",
            title="Test Document 1",
            url="http://example.com/doc1",
            text_md="# Introduction\n\nThis is a test document with some content.",
            score=0.95,
            source_system="confluence",
        ),
        SearchHit(
            chunk_id="doc1:0001",
            doc_id="doc1",
            title="Test Document 1",
            url="http://example.com/doc1",
            text_md="More content from the same document.\n\n```python\nprint('code')\n```",
            score=0.85,
            source_system="confluence",
        ),
        SearchHit(
            chunk_id="doc2:0000",
            doc_id="doc2",
            title="Test Document 2",
            url="http://example.com/doc2",
            text_md="![media: image.png]\n\nThis document has media content.",
            score=0.75,
            source_system="dita",
        ),
    ]


def test_search_hit_to_dict():
    """Test SearchHit.to_dict() method."""
    hit = SearchHit(
        chunk_id="test:0000",
        doc_id="test",
        title="Test Title",
        url="http://test.com",
        text_md="Test content",
        score=0.9,
        source_system="test",
    )

    expected = {
        "chunk_id": "test:0000",
        "doc_id": "test",
        "title": "Test Title",
        "url": "http://test.com",
        "text_md": "Test content",
        "score": 0.9,
        "source_system": "test",
    }

    assert hit.to_dict() == expected


def test_pack_context_basic(sample_hits):
    """Test basic context packing functionality."""
    context_str, selected_hits = pack_context(sample_hits, max_chars=1000)

    # Should include all hits since they fit in 1000 chars
    assert len(selected_hits) == 3
    assert "Test Document 1" in context_str
    assert "Test Document 2" in context_str
    assert "confluence" in context_str
    assert "dita" in context_str


def test_pack_context_char_limit(sample_hits):
    """Test context packing respects character limit."""
    context_str, selected_hits = pack_context(sample_hits, max_chars=200)

    # Should only include first hit due to character limit
    assert len(selected_hits) == 1
    assert selected_hits[0].chunk_id == "doc1:0000"
    assert len(context_str) <= 200


def test_pack_context_max_chunks_per_doc(sample_hits):
    """Test context packing respects max chunks per document."""
    context_str, selected_hits = pack_context(
        sample_hits, max_chars=6000, max_chunks_per_doc=1
    )

    # Should only include 2 hits (1 per document)
    assert len(selected_hits) == 2
    assert selected_hits[0].doc_id == "doc1"
    assert selected_hits[1].doc_id == "doc2"


def test_pack_context_preserves_code_blocks(sample_hits):
    """Test that context packing doesn't split code blocks."""
    # Create a hit with a code block that would be truncated
    hits_with_code = [
        SearchHit(
            chunk_id="code:0000",
            doc_id="code",
            title="Code Document",
            url="http://example.com/code",
            text_md="Start of text\n\n```python\ndef function():\n    return True\n```\n\nEnd of text",
            score=0.9,
            source_system="test",
        )
    ]

    # Set a limit that would truncate in the middle of the code block
    context_str, selected_hits = pack_context(hits_with_code, max_chars=50)

    # Should either include the full hit or exclude it entirely
    if selected_hits:
        assert "```python" in context_str
        assert (
            "```" in context_str[context_str.find("```python") + 9 :]
        )  # Closing ```


def test_pack_context_includes_media_placeholder(sample_hits):
    """Test that media placeholders are preserved and enhanced."""
    context_str, selected_hits = pack_context(sample_hits, max_chars=6000)

    # Should include the media placeholder from doc2
    assert "![media: image.png]" in context_str


def test_pack_context_empty_hits():
    """Test context packing with empty hits list."""
    context_str, selected_hits = pack_context([], max_chars=1000)

    assert context_str == ""
    assert selected_hits == []


def test_dense_retriever_initialization():
    """Test DenseRetriever initialization."""
    test_db_url = "postgresql://test:test@localhost:5432/test"
    retriever = DenseRetriever(test_db_url, "dummy")

    assert retriever.db_url == test_db_url
    assert retriever.provider == "dummy"


def test_dense_retriever_embed_query():
    """Test query embedding functionality."""
    with patch(
        "trailblazer.pipeline.steps.retrieve.retriever.get_embedding_provider"
    ) as mock_provider:
        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = [0.1, 0.2, 0.3]
        mock_provider.return_value = mock_embedder

        retriever = DenseRetriever(
            "postgresql://test:test@localhost:5432/test", "dummy"
        )
        result = retriever.embed_query("test query")

        assert result == [0.1, 0.2, 0.3]
        mock_embedder.embed.assert_called_once_with("test query")


def test_deterministic_ranking(sample_hits):
    """Test that ranking is deterministic."""
    # Create hits with same scores to test tie-breaking
    tied_hits = [
        SearchHit(
            "doc2:0001", "doc2", "Title B", "", "Content B", 0.8, "test"
        ),
        SearchHit(
            "doc1:0001", "doc1", "Title A", "", "Content A", 0.8, "test"
        ),
        SearchHit(
            "doc1:0000", "doc1", "Title A", "", "Content A", 0.8, "test"
        ),
        SearchHit(
            "doc2:0000", "doc2", "Title B", "", "Content B", 0.8, "test"
        ),
    ]

    # Sort hits to simulate what the retriever would do (score DESC, doc_id ASC, chunk_id ASC)
    sorted_hits = sorted(
        tied_hits, key=lambda h: (-h.score, h.doc_id, h.chunk_id)
    )
    context_str, selected_hits = pack_context(sorted_hits, max_chars=6000)

    assert len(selected_hits) == 4
    assert selected_hits[0].chunk_id == "doc1:0000"
    assert selected_hits[1].chunk_id == "doc1:0001"
    assert selected_hits[2].chunk_id == "doc2:0000"
    assert selected_hits[3].chunk_id == "doc2:0001"


def test_context_includes_metadata(sample_hits):
    """Test that context includes document metadata."""
    context_str, selected_hits = pack_context(sample_hits, max_chars=6000)

    # Should include document titles, sources, and URLs
    assert "Test Document 1" in context_str
    assert "Test Document 2" in context_str
    assert "confluence" in context_str
    assert "dita" in context_str
    assert "http://example.com/doc1" in context_str
    assert "http://example.com/doc2" in context_str

    # Should include scores
    assert "0.9500" in context_str
    assert "0.8500" in context_str
    assert "0.7500" in context_str
