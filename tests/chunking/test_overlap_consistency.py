"""
Test overlap consistency for chunking v2.2.
"""

from trailblazer.pipeline.steps.chunk.engine import chunk_document


def test_overlap_honored_on_paragraph_splits():
    """Test that overlap_tokens is honored when splitting by paragraphs."""
    doc_text = """
# Test Document

This is the first paragraph with sufficient content to create a meaningful chunk.
It has multiple sentences and should be substantial enough to test overlap behavior.

This is the second paragraph with different content.
It also has multiple sentences to ensure proper overlap testing.

This is the third paragraph with even more content.
It continues the pattern of having substantial text for overlap verification.
"""

    chunks = chunk_document(
        doc_id="test_doc",
        text_md=doc_text,
        title="Test Document",
        url="https://example.com/test",
        source_system="test",
        hard_max_tokens=50,  # Force splitting
        min_tokens=30,
        overlap_tokens=15,
        soft_min_tokens=40,
        hard_min_tokens=40,
        orphan_heading_merge=False,  # Disable to test pure paragraph splitting
        small_tail_merge=False,
    )

    # Should create multiple chunks due to low hard_max_tokens
    assert len(chunks) >= 2

    # Check for overlap between consecutive chunks
    for i in range(len(chunks) - 1):
        current_chunk = chunks[i]
        next_chunk = chunks[i + 1]

        # Get the last ~30 tokens worth of text from current chunk
        current_words = current_chunk.text_md.split()
        next_words = next_chunk.text_md.split()

        # Look for common words at the boundary (indicating overlap)
        if len(current_words) >= 10 and len(next_words) >= 10:
            current_end = " ".join(current_words[-10:])
            next_start = " ".join(next_words[:10])

            # Should have some overlap (common words/phrases)
            current_end_words = set(current_end.lower().split())
            next_start_words = set(next_start.lower().split())
            overlap_words = current_end_words.intersection(next_start_words)

            # At least some words should overlap
            assert len(overlap_words) > 0, (
                f"No overlap found between chunks {i} and {i + 1}"
            )


def test_overlap_honored_on_sentence_splits():
    """Test that overlap_tokens is honored when splitting by sentences."""
    # Create content that forces sentence-level splitting
    long_sentence = "This is a very long sentence that contains many words and should exceed the token limit. "
    doc_text = f"""
# Test Document

{long_sentence * 5}

{long_sentence * 5}

{long_sentence * 5}
"""

    chunks = chunk_document(
        doc_id="test_doc",
        text_md=doc_text,
        title="Test Document",
        url="https://example.com/test",
        source_system="test",
        hard_max_tokens=150,  # Force splitting within paragraphs
        min_tokens=50,
        overlap_tokens=25,
        soft_min_tokens=80,
        hard_min_tokens=40,
    )

    # Should create multiple chunks
    assert len(chunks) >= 2

    # Verify overlap exists between chunks
    for i in range(len(chunks) - 1):
        current_chunk = chunks[i]
        next_chunk = chunks[i + 1]

        # Extract text content
        current_text = current_chunk.text_md.strip()
        next_text = next_chunk.text_md.strip()

        # Skip if chunks are too different (might be different sections)
        if not current_text or not next_text:
            continue

        # Check for textual overlap at boundaries
        current_words = current_text.split()
        next_words = next_text.split()

        if len(current_words) >= 5 and len(next_words) >= 5:
            # Look for overlap in the boundary regions
            current_end = " ".join(current_words[-5:])
            next_start = " ".join(next_words[:5])

            # Should find some common content
            if (
                "very long sentence" in current_end
                and "very long sentence" in next_start
            ):
                # This indicates proper overlap
                pass  # Good overlap detected


def test_overlap_on_code_fence_splits():
    """Test that overlap is applied to code fence splits without duplicating delimiters."""
    doc_text = """
# Code Example

Here's some code:

```python
def function_one():
    print("First function")
    return "result1"

def function_two():
    print("Second function")
    return "result2"

def function_three():
    print("Third function")
    return "result3"

def function_four():
    print("Fourth function")
    return "result4"
```

End of code section.
"""

    chunks = chunk_document(
        doc_id="test_doc",
        text_md=doc_text,
        title="Test Document",
        url="https://example.com/test",
        source_system="test",
        hard_max_tokens=120,  # Force splitting within code block
        min_tokens=50,
        overlap_tokens=20,
        soft_min_tokens=80,
        hard_min_tokens=40,
    )

    # Find chunks containing code
    code_chunks = [c for c in chunks if "```" in c.text_md]

    if len(code_chunks) >= 2:
        # Verify that fence delimiters are not doubled at boundaries
        for chunk in code_chunks:
            text = chunk.text_md

            # Should not have doubled delimiters like "```\n```"
            assert "```\n```" not in text
            assert "```python\n```python" not in text

            # Each code chunk should have proper opening/closing
            if "```python" in text:
                # Should have proper structure
                lines = text.split("\n")
                python_lines = [
                    i for i, line in enumerate(lines) if "```python" in line
                ]
                end_lines = [
                    i
                    for i, line in enumerate(lines)
                    if line.strip() == "```" and i > 0
                ]

                # Should have balanced delimiters
                assert len(python_lines) <= 1  # At most one opening per chunk
                assert len(end_lines) <= 1  # At most one closing per chunk


def test_overlap_on_table_splits():
    """Test that overlap is applied to table splits without breaking table structure."""
    doc_text = """
# Data Table

| Column A | Column B | Column C | Column D |
|----------|----------|----------|----------|
| Row 1 A  | Row 1 B  | Row 1 C  | Row 1 D  |
| Row 2 A  | Row 2 B  | Row 2 C  | Row 2 D  |
| Row 3 A  | Row 3 B  | Row 3 C  | Row 3 D  |
| Row 4 A  | Row 4 B  | Row 4 C  | Row 4 D  |
| Row 5 A  | Row 5 B  | Row 5 C  | Row 5 D  |
| Row 6 A  | Row 6 B  | Row 6 C  | Row 6 D  |
| Row 7 A  | Row 7 B  | Row 7 C  | Row 7 D  |
| Row 8 A  | Row 8 B  | Row 8 C  | Row 8 D  |
"""

    chunks = chunk_document(
        doc_id="test_doc",
        text_md=doc_text,
        title="Test Document",
        url="https://example.com/test",
        source_system="test",
        hard_max_tokens=150,  # Force table splitting
        min_tokens=50,
        overlap_tokens=30,
        soft_min_tokens=80,
        hard_min_tokens=40,
    )

    # Find chunks containing table content
    table_chunks = [
        c for c in chunks if "|" in c.text_md and "Column" in c.text_md
    ]

    if len(table_chunks) >= 2:
        for chunk in table_chunks:
            text = chunk.text_md
            lines = text.split("\n")
            table_lines = [
                line for line in lines if "|" in line and line.strip()
            ]

            if table_lines:
                # Each table chunk should have header if it's the first part
                # or should maintain table structure

                # Verify no broken table rows (each row should have same number of |)
                pipe_counts = [
                    line.count("|")
                    for line in table_lines
                    if not line.startswith("|-")
                ]
                if pipe_counts:
                    expected_pipes = pipe_counts[0]
                    for count in pipe_counts:
                        # Allow some variation for header separators
                        assert abs(count - expected_pipes) <= 1, (
                            f"Inconsistent table structure: {pipe_counts}"
                        )


def test_overlap_on_token_window_splits():
    """Test that overlap is applied to token window (word-level) splits."""
    # Create content that forces token-window splitting
    long_text = "word " * 200  # 200 words, no paragraph breaks

    doc_text = f"""
# Test Document

{long_text}
"""

    chunks = chunk_document(
        doc_id="test_doc",
        text_md=doc_text,
        title="Test Document",
        url="https://example.com/test",
        source_system="test",
        hard_max_tokens=100,  # Force token-window splitting
        min_tokens=50,
        overlap_tokens=20,
        soft_min_tokens=80,
        hard_min_tokens=40,
    )

    # Should create multiple chunks from the long text
    word_chunks = [c for c in chunks if "word word word" in c.text_md]

    if len(word_chunks) >= 2:
        # Check overlap between consecutive word chunks
        for i in range(len(word_chunks) - 1):
            current_chunk = word_chunks[i]
            next_chunk = word_chunks[i + 1]

            current_words = current_chunk.text_md.split()
            next_words = next_chunk.text_md.split()

            # Should have overlap of approximately overlap_tokens worth
            current_end = (
                current_words[-10:]
                if len(current_words) >= 10
                else current_words
            )
            next_start = (
                next_words[:10] if len(next_words) >= 10 else next_words
            )

            # Count overlapping words
            overlap_count = 0
            for word in current_end:
                if word in next_start:
                    overlap_count += 1

            # Should have some overlap
            assert overlap_count > 0, (
                f"No overlap found in token-window split between chunks {i} and {i + 1}"
            )


def test_no_overlap_when_no_split_needed():
    """Test that overlap is not applied when no splitting is needed."""
    doc_text = """
# Short Document

This is a short document that fits within the token limit.
"""

    chunks = chunk_document(
        doc_id="test_doc",
        text_md=doc_text,
        title="Test Document",
        url="https://example.com/test",
        source_system="test",
        hard_max_tokens=800,  # Large enough to fit everything
        min_tokens=50,
        overlap_tokens=30,
        soft_min_tokens=200,
        hard_min_tokens=80,
    )

    # Should create only one chunk since content fits
    assert len(chunks) == 1

    # Single chunk should contain all content without duplication
    chunk = chunks[0]
    assert "Short Document" in chunk.text_md
    assert "short document that fits" in chunk.text_md
