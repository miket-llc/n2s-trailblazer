import pytest
from trailblazer.pipeline.steps.chunk.engine import (
    chunk_document,
    inject_media_placeholders,
)
from trailblazer.pipeline.steps.chunk.boundaries import normalize_text


def chunk_normalized_record(record):
    """Helper function to chunk a normalized record."""
    doc_id = record.get("id", "")
    title = record.get("title", "")
    text_md = record.get("text_md", "")
    attachments = record.get("attachments", [])

    if not doc_id:
        raise ValueError("Record missing required 'id' field")

    text_with_media = inject_media_placeholders(text_md, attachments)
    return chunk_document(
        doc_id=doc_id,
        text_md=text_with_media,
        title=title,
        source_system=record.get("source_system", ""),
        labels=record.get("labels", []),
        space=record.get("space"),
        media_refs=attachments,
    )


def test_chunker_determinism():
    """Test that chunker produces deterministic results."""
    doc_id = "test-doc-123"
    title = "Test Document"
    text_md = """# Introduction

This is a test document with multiple sections and some content.

## Section 1

Here's some content for section 1. It has enough text to make sure we can test chunking behavior properly.

```python
def example_code():
    return "code blocks should not be split"
```

## Section 2

This is another section with different content. We want to ensure that the chunker handles this correctly and produces consistent results.

### Subsection 2.1

More content here to make the document longer and test overlap behavior.

## Conclusion

Final section of the document."""

    # Run chunking multiple times
    chunks1 = chunk_document(doc_id, text_md, title)
    chunks2 = chunk_document(doc_id, text_md, title)

    # Should produce identical results
    assert len(chunks1) == len(chunks2)

    for c1, c2 in zip(chunks1, chunks2):
        assert c1.chunk_id == c2.chunk_id
        assert c1.text_md == c2.text_md
        assert c1.char_count == c2.char_count
        assert c1.token_count == c2.token_count
        assert c1.ord == c2.ord


def test_chunk_id_format():
    """Test that chunk IDs follow the expected format."""
    doc_id = "doc-456"
    text_md = "Short content that should produce one chunk."

    chunks = chunk_document(doc_id, text_md)

    assert len(chunks) == 1
    assert chunks[0].chunk_id == "doc-456:0000"
    assert chunks[0].ord == 0


def test_no_triple_blank_lines():
    """Test that chunks don't contain triple blank lines."""
    doc_id = "test-whitespace"
    text_md = """# Title

Some content.


Too many blank lines above.



Even more blank lines.

Final content."""

    chunks = chunk_document(doc_id, text_md)

    for chunk in chunks:
        # Should not contain triple blank lines
        assert "\n\n\n" not in chunk.text_md
        # Should not start or end with whitespace
        assert chunk.text_md == chunk.text_md.strip()


def test_overlap_maintained():
    """Test that overlap is maintained between chunks."""
    doc_id = "test-overlap"
    # Create a longer document that will be split
    sections = [
        f"## Section {i}\n\nThis is section {i} with enough content to trigger chunking behavior. "
        * 20
        for i in range(10)
    ]
    text_md = "\n\n".join(sections)

    chunks = chunk_document(
        doc_id,
        text_md,
        hard_max_tokens=800,
        min_tokens=200,
        overlap_tokens=100,
    )

    if len(chunks) > 1:
        # Check that there's some overlap between consecutive chunks
        for i in range(len(chunks) - 1):
            current_chunk = chunks[i].text_md
            next_chunk = chunks[i + 1].text_md

            # Should have some overlapping content (at least some words)
            current_words = set(current_chunk.split()[-20:])  # Last 20 words
            next_words = set(next_chunk.split()[:20])  # First 20 words

            # Should have at least some overlap
            overlap = current_words.intersection(next_words)
            assert (
                len(overlap) > 0
            ), f"No overlap found between chunks {i} and {i + 1}"


def test_code_block_preservation():
    """Test that code blocks are not split across chunks."""
    doc_id = "test-code"
    text_md = """# Document with Code

Some intro text.

```python
def important_function():
    # This code block should not be split
    for i in range(100):
        print(f"Line {i}")
    return "done"
```

More content after the code block."""

    chunks = chunk_document(doc_id, text_md)

    # Find chunk containing the code block
    code_chunks = [c for c in chunks if "```python" in c.text_md]
    assert len(code_chunks) == 1, "Code block should be in exactly one chunk"

    code_chunk = code_chunks[0]
    # Code block should be complete
    assert "```python" in code_chunk.text_md
    assert (
        "```" in code_chunk.text_md[code_chunk.text_md.find("```python") + 9 :]
    )


def test_chunk_normalized_record():
    """Test chunking a normalized record."""
    record = {
        "id": "record-789",
        "title": "Test Record",
        "text_md": "# Test\n\nThis is test content.",
    }

    chunks = chunk_normalized_record(record)

    assert len(chunks) >= 1
    assert chunks[0].chunk_id == "record-789:0000"
    assert "# Test Record" in chunks[0].text_md  # Title should be prepended


def test_empty_content():
    """Test handling of empty content."""
    chunks1 = chunk_document("empty-1", "")
    chunks2 = chunk_document("empty-2", "   \n\n  ")

    assert len(chunks1) == 0
    assert len(chunks2) == 0


def test_normalize_text():
    """Test text normalization function."""
    # CRLF normalization
    assert normalize_text("line1\r\nline2") == "line1\nline2"
    assert normalize_text("line1\rline2") == "line1\nline2"

    # Triple blank line reduction
    assert normalize_text("para1\n\n\n\npara2") == "para1\n\npara2"
    assert normalize_text("para1\n\n\n\n\n\npara2") == "para1\n\npara2"

    # Whitespace stripping
    assert normalize_text("  \n  content  \n  ") == "content"


def test_missing_record_id():
    """Test error handling for missing record ID."""
    record = {"title": "No ID", "text_md": "Content"}

    with pytest.raises(ValueError, match="Record missing required 'id' field"):
        chunk_normalized_record(record)
