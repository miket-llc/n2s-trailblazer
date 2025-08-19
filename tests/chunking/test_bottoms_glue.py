"""
Test bottom-end glue functionality for chunking v2.2.
"""

from trailblazer.chunking.engine import chunk_document


def test_glue_raises_chunks_to_soft_min():
    """Test that glue pass raises most chunks to >= soft_min without breaking hard_max."""
    doc_text = """
# Test Document

This is a short paragraph.

Another short paragraph.

Yet another short paragraph.

Final short paragraph.
"""

    chunks = chunk_document(
        doc_id="test_doc",
        text_md=doc_text,
        title="Test Document",
        url="http://example.com/test",
        source_system="test",
        hard_max_tokens=800,
        min_tokens=120,
        soft_min_tokens=200,
        hard_min_tokens=80,
        orphan_heading_merge=True,
        small_tail_merge=True,
    )

    # Verify that most chunks are >= soft_min_tokens
    chunks_above_soft_min = [c for c in chunks if c.token_count >= 200]
    assert (
        len(chunks_above_soft_min) >= len(chunks) * 0.8
    )  # At least 80% should be above soft min

    # Verify no chunk exceeds hard_max
    for chunk in chunks:
        assert chunk.token_count <= 800

    # Verify no chunk below hard_min (unless tagged as exception)
    for chunk in chunks:
        if chunk.token_count < 80:
            # Should have an exception reason
            meta = chunk.meta or {}
            assert meta.get("tail_small") or "tiny_doc" in str(meta)


def test_orphan_heading_merge():
    """Test that orphan headings are merged with neighbors."""
    doc_text = """
# Main Title

Some content here.

## References

## See Also

More content here.
"""

    chunks = chunk_document(
        doc_id="test_doc",
        text_md=doc_text,
        title="Test Document",
        url="http://example.com/test",
        source_system="test",
        hard_max_tokens=800,
        min_tokens=120,
        soft_min_tokens=200,
        hard_min_tokens=80,
        orphan_heading_merge=True,
        small_tail_merge=True,
    )

    # Should not have pure-heading chunks
    for chunk in chunks:
        lines = chunk.text_md.strip().split("\n")
        non_empty_lines = [line.strip() for line in lines if line.strip()]

        # If it's a single line starting with #, it should have been merged
        if len(non_empty_lines) == 1 and non_empty_lines[0].startswith("#"):
            # This should only happen if it couldn't be merged due to size constraints
            assert (
                chunk.token_count + 200 > 800
            )  # Would exceed hard_max if merged


def test_small_tail_merge():
    """Test that small tail chunks are merged when possible or flagged."""
    doc_text = """
# Main Document

This is a substantial piece of content that should create a reasonably sized chunk.
It has multiple sentences and should be well above the minimum token count.
This ensures we have a good base chunk to work with.

Small tail.
"""

    chunks = chunk_document(
        doc_id="test_doc",
        text_md=doc_text,
        title="Test Document",
        url="http://example.com/test",
        source_system="test",
        hard_max_tokens=800,
        min_tokens=120,
        soft_min_tokens=200,
        hard_min_tokens=80,
        orphan_heading_merge=True,
        small_tail_merge=True,
    )

    # Check if there's a small tail
    last_chunk = chunks[-1] if chunks else None
    if last_chunk and last_chunk.token_count < 200:
        # Should either be merged (only one chunk) or flagged as tail_small
        if len(chunks) == 1:
            # Was merged successfully
            assert last_chunk.token_count >= 200
        else:
            # Should be flagged as small tail if couldn't merge
            meta = last_chunk.meta or {}
            if last_chunk.token_count < 80:
                assert meta.get("tail_small") is True


def test_glue_strategy_suffix():
    """Test that glued chunks have +glue suffix in split_strategy."""
    doc_text = """
# Test

Short para 1.

Short para 2.

Short para 3.
"""

    chunks = chunk_document(
        doc_id="test_doc",
        text_md=doc_text,
        title="Test Document",
        url="http://example.com/test",
        source_system="test",
        hard_max_tokens=800,
        min_tokens=120,
        soft_min_tokens=200,
        hard_min_tokens=80,
        orphan_heading_merge=True,
        small_tail_merge=True,
    )

    # Look for chunks with +glue suffix
    glued_chunks = [c for c in chunks if "+glue" in c.split_strategy]

    # Should have at least some glued chunks given the short paragraphs
    if len(chunks) < 3:  # If chunks were merged
        assert len(glued_chunks) > 0

        # Verify glued chunks have the metadata
        for chunk in glued_chunks:
            meta = chunk.meta or {}
            assert "glued_from" in meta
            assert isinstance(meta["glued_from"], list)
            assert len(meta["glued_from"]) == 2  # Should merge two chunks


def test_respects_hard_max_during_glue():
    """Test that glue pass never creates chunks exceeding hard_max."""
    # Create content that would exceed hard_max if naively glued
    large_paragraph = "This is a large paragraph. " * 50  # ~350 tokens
    doc_text = f"""
# Test Document

{large_paragraph}

{large_paragraph}

Short tail.
"""

    chunks = chunk_document(
        doc_id="test_doc",
        text_md=doc_text,
        title="Test Document",
        url="http://example.com/test",
        source_system="test",
        hard_max_tokens=500,  # Lower limit to force constraint
        min_tokens=120,
        soft_min_tokens=200,
        hard_min_tokens=80,
        orphan_heading_merge=True,
        small_tail_merge=True,
    )

    # Verify no chunk exceeds hard_max
    for chunk in chunks:
        assert chunk.token_count <= 500

    # The small tail should either be merged if possible or left small
    if len(chunks) > 1:
        last_chunk = chunks[-1]
        if last_chunk.token_count < 200:
            # Should have tried to merge but couldn't due to size constraints
            # Previous chunk should be close to max
            if len(chunks) >= 2:
                prev_chunk = chunks[-2]
                # If we couldn't merge, prev chunk should be reasonably large
                assert prev_chunk.token_count > 300  # Close to our 500 limit
