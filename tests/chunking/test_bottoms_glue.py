"""
Test bottom-end glue functionality for chunking v2.2.
"""

from trailblazer.pipeline.steps.chunk.engine import chunk_document


def test_glue_raises_chunks_to_soft_min():
    """Test that glue pass raises most chunks to >= soft_min without breaking hard_max."""
    # Create multiple paragraphs that will be split, then glued
    doc_text = """
# Test Document

This is a short paragraph with some content to make it a bit longer for testing purposes.

Another short paragraph with different content to test the chunking and gluing behavior properly.

Yet another short paragraph with more text to ensure we have enough content for proper testing.

Final short paragraph with additional content to complete the test document and verify gluing works.

Extra paragraph to ensure we have multiple chunks that can be glued together according to the soft minimum requirements.

One more paragraph to make absolutely sure we have enough content for comprehensive testing of the glue functionality.
"""

    chunks = chunk_document(
        doc_id="test_doc",
        text_md=doc_text,
        title="Test Document",
        url="http://example.com/test",
        source_system="test",
        hard_max_tokens=100,  # Lower limit to force splitting
        min_tokens=50,
        soft_min_tokens=80,  # Lower soft min for testing
        hard_min_tokens=40,  # Lower hard min for testing
        orphan_heading_merge=True,
        small_tail_merge=True,
    )

    # Verify that most chunks are >= soft_min_tokens (excluding small tails)
    chunks_above_soft_min = [c for c in chunks if c.token_count >= 80]
    small_tails = [c for c in chunks if c.meta and c.meta.get("tail_small")]

    # At least 80% of non-tail chunks should be above soft min
    non_tail_chunks = len(chunks) - len(small_tails)
    if non_tail_chunks > 0:
        assert len(chunks_above_soft_min) >= non_tail_chunks * 0.8
    else:
        # If all chunks are small tails, that's acceptable
        assert len(small_tails) == len(chunks)

    # Verify no chunk exceeds hard_max
    for chunk in chunks:
        assert chunk.token_count <= 100

    # Verify no chunk below hard_min (unless tagged as exception)
    for chunk in chunks:
        if chunk.token_count < 40:
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
        hard_max_tokens=100,  # Lower limit to force splitting
        min_tokens=50,
        soft_min_tokens=80,  # Lower soft min for testing
        hard_min_tokens=40,  # Lower hard min for testing
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
        hard_max_tokens=100,  # Lower limit to force splitting
        min_tokens=50,
        soft_min_tokens=80,  # Lower soft min for testing
        hard_min_tokens=40,  # Lower hard min for testing
        orphan_heading_merge=True,
        small_tail_merge=True,
    )

    # Check if there's a small tail
    last_chunk = chunks[-1] if chunks else None
    if last_chunk and last_chunk.token_count < 80:
        # Should either be merged with previous chunks or flagged as tail_small
        if len(chunks) > 1:
            # Multiple chunks - last one should be flagged as small tail if couldn't merge
            meta = last_chunk.meta or {}
            assert meta.get("tail_small") is True
        else:
            # Single chunk that's small - this is acceptable for small documents
            # No assertion needed - small documents are allowed to have small chunks
            pass


def test_glue_strategy_suffix():
    """Test that glued chunks have +glue suffix in split_strategy."""
    doc_text = """
# Test

Short para 1 with enough content to make it longer for testing purposes and ensure proper splitting behavior.

Short para 2 with additional content to test the gluing functionality and verify that chunks are merged properly.

Short para 3 with more text to ensure we have enough content for comprehensive testing of the glue strategy suffix.

Short para 4 to make sure we have multiple paragraphs that can be split and then glued together.

Short para 5 with final content to complete the test and verify the glue functionality works as expected.
"""

    chunks = chunk_document(
        doc_id="test_doc",
        text_md=doc_text,
        title="Test Document",
        url="http://example.com/test",
        source_system="test",
        hard_max_tokens=100,  # Lower limit to force splitting
        min_tokens=50,
        soft_min_tokens=80,  # Lower soft min for testing
        hard_min_tokens=40,  # Lower hard min for testing
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
        min_tokens=50,
        soft_min_tokens=80,  # Lower soft min for testing
        hard_min_tokens=40,  # Lower hard min for testing
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
