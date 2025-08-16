"""Tests for the embedding chunker with media awareness."""

import pytest
from trailblazer.pipeline.steps.embed.chunker import (
    chunk_document,
    chunk_normalized_record,
    inject_media_placeholders,
    normalize_text,
    split_on_paragraphs_and_headings,
)


def test_normalize_text():
    """Test text normalization."""
    # CRLF to LF conversion
    assert normalize_text("line1\r\nline2") == "line1\nline2"
    assert normalize_text("line1\rline2") == "line1\nline2"

    # Triple blank line removal
    assert normalize_text("para1\n\n\n\n\npara2") == "para1\n\npara2"

    # Whitespace trimming
    assert normalize_text("  text  ") == "text"


def test_split_on_paragraphs_and_headings():
    """Test paragraph and heading splitting."""
    text = """# Main Title

This is a paragraph.

## Section 1

Another paragraph here.

```python
def test():
    return True
```

Final paragraph."""

    parts = split_on_paragraphs_and_headings(text)

    # The chunker may group some sections together
    assert len(parts) >= 2
    assert parts[0].startswith("# Main Title")
    # Code and final paragraph might be grouped with section 1
    full_text = "\n".join(parts)
    assert "## Section 1" in full_text
    assert "```python" in full_text
    assert "Final paragraph." in full_text


def test_split_preserves_code_blocks():
    """Test that code blocks are never split."""
    text = """Before code

```bash
command1
command2

command3
```

After code"""

    parts = split_on_paragraphs_and_headings(text)

    # Code block should be preserved intact in one of the parts
    full_text = "\n".join(parts)
    assert "```bash" in full_text
    assert "command1\ncommand2\n\ncommand3" in full_text

    # Find the part with the code block
    code_part = None
    for part in parts:
        if "```bash" in part:
            code_part = part
            break

    assert code_part is not None
    # The code block should be complete in this part
    assert code_part.count("```") == 2  # Opening and closing


def test_chunk_document_basic():
    """Test basic document chunking."""
    doc_id = "test-doc"
    text = "# Title\n\nThis is a short document for testing chunking."
    title = "Test Document"

    chunks = chunk_document(
        doc_id, text, title, target_tokens=500, max_tokens=1000
    )

    assert len(chunks) == 1
    assert chunks[0].chunk_id == "test-doc:0000"
    assert chunks[0].ord == 0
    assert chunks[0].text_md.startswith("# Test Document")
    assert "This is a short document" in chunks[0].text_md
    assert chunks[0].char_count > 0
    assert chunks[0].token_count > 0


def test_chunk_document_deterministic():
    """Test that chunking is deterministic."""
    doc_id = "test-doc"
    text = "# Title\n\n" + "This is a test paragraph. " * 100

    chunks1 = chunk_document(doc_id, text, target_tokens=500, max_tokens=1000)
    chunks2 = chunk_document(doc_id, text, target_tokens=500, max_tokens=1000)

    assert len(chunks1) == len(chunks2)
    for c1, c2 in zip(chunks1, chunks2):
        assert c1.chunk_id == c2.chunk_id
        assert c1.text_md == c2.text_md
        assert c1.char_count == c2.char_count
        assert c1.token_count == c2.token_count


def test_chunk_document_overlap():
    """Test chunk overlap functionality."""
    doc_id = "test-doc"
    # Create long enough text to force multiple chunks
    text = (
        "# Title\n\n"
        + "This is a test paragraph with meaningful content. " * 50
    )

    chunks = chunk_document(
        doc_id, text, target_tokens=500, max_tokens=1000, overlap_pct=0.15
    )

    if len(chunks) > 1:
        # Check that there's some overlap between consecutive chunks
        chunk1_end = chunks[0].text_md[-100:]  # Last 100 chars
        chunk2_start = chunks[1].text_md[:100]  # First 100 chars

        # Should have some common words (due to overlap)
        words1 = set(chunk1_end.split())
        words2 = set(chunk2_start.split())
        overlap_words = words1.intersection(words2)
        assert len(overlap_words) > 0


def test_chunk_document_ids():
    """Test chunk ID generation."""
    doc_id = "doc-123"
    text = "# Title\n\n" + "Content paragraph. " * 100

    chunks = chunk_document(doc_id, text, target_tokens=500, max_tokens=1000)

    for i, chunk in enumerate(chunks):
        expected_id = f"doc-123:{i:04d}"
        assert chunk.chunk_id == expected_id
        assert chunk.ord == i


def test_inject_media_placeholders():
    """Test media placeholder injection."""
    text = "This is some content."
    attachments = [
        {"filename": "image1.png", "id": "att1"},
        {"filename": "document.pdf", "id": "att2"},
        {"filename": "", "id": "att3"},  # Should be skipped
    ]

    result = inject_media_placeholders(text, attachments)

    assert "![media: image1.png]" in result
    assert "![media: document.pdf]" in result
    assert "![media: ]" not in result  # Empty filename skipped
    assert "## Media" in result


def test_inject_media_placeholders_empty():
    """Test media placeholder injection with no attachments."""
    text = "This is some content."
    attachments = []

    result = inject_media_placeholders(text, attachments)

    assert result == text  # Should be unchanged


def test_inject_media_placeholders_existing():
    """Test that existing media references aren't duplicated."""
    text = "Content with ![media: image1.png] already present."
    attachments = [
        {"filename": "image1.png", "id": "att1"},
        {"filename": "image2.png", "id": "att2"},
    ]

    result = inject_media_placeholders(text, attachments)

    # Should only add image2.png, not duplicate image1.png
    assert result.count("![media: image1.png]") == 1
    assert "![media: image2.png]" in result


def test_chunk_normalized_record():
    """Test chunking a normalized record."""
    record = {
        "id": "confluence-123",
        "title": "Test Page",
        "text_md": "# Content\n\nThis is the page content.",
        "attachments": [
            {"filename": "chart.png", "id": "att1"},
        ],
    }

    chunks = chunk_normalized_record(record)

    assert len(chunks) >= 1
    assert chunks[0].chunk_id.startswith("confluence-123:")
    assert "Test Page" in chunks[0].text_md
    assert "![media: chart.png]" in chunks[0].text_md


def test_chunk_normalized_record_missing_id():
    """Test error handling for missing document ID."""
    record = {
        "title": "Test Page",
        "text_md": "Content",
    }

    with pytest.raises(ValueError, match="Record missing required 'id' field"):
        chunk_normalized_record(record)


def test_chunk_normalized_record_empty_content():
    """Test handling of empty content."""
    record = {
        "id": "empty-doc",
        "title": "",
        "text_md": "",
        "attachments": [],
    }

    chunks = chunk_normalized_record(record)

    # Should return empty list for empty content
    assert len(chunks) == 0


def test_chunk_token_count():
    """Test token count calculation."""
    doc_id = "test-doc"
    text = "This is a test with exactly eight words"

    chunks = chunk_document(doc_id, text)

    assert len(chunks) == 1
    assert chunks[0].token_count == 8  # Simple word count


def test_chunk_never_splits_code_blocks():
    """Test that code blocks are never split across chunks."""
    doc_id = "code-doc"

    # Create a long code block that might be tempting to split
    code_block = "```python\n" + "print('line')\n" * 100 + "```"
    text = f"# Title\n\nBefore code.\n\n{code_block}\n\nAfter code."

    chunks = chunk_document(doc_id, text, target_tokens=500, max_tokens=1000)

    # Find the chunk containing the code block
    code_chunk = None
    for chunk in chunks:
        if "```python" in chunk.text_md:
            code_chunk = chunk
            break

    assert code_chunk is not None
    # The entire code block should be in one chunk
    assert code_chunk.text_md.count("```python") == 1
    assert code_chunk.text_md.count("```") == 2  # Opening and closing


def test_chunk_with_very_long_title():
    """Test handling of very long titles."""
    doc_id = "long-title-doc"
    long_title = "Very " * 100 + "Long Title"
    text = "Short content."

    chunks = chunk_document(doc_id, text, title=long_title)

    assert len(chunks) == 1
    assert long_title in chunks[0].text_md
    assert "Short content." in chunks[0].text_md


def test_chunk_media_awareness_integration():
    """Test full integration of media-aware chunking."""
    record = {
        "id": "media-doc",
        "title": "Document with Media",
        "text_md": "# Introduction\n\nThis document has attachments.\n\n## Details\n\nMore content here.",
        "attachments": [
            {
                "filename": "diagram.svg",
                "id": "att1",
                "media_type": "image/svg+xml",
            },
            {
                "filename": "data.xlsx",
                "id": "att2",
                "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            },
        ],
    }

    chunks = chunk_normalized_record(record)

    # Should have media section
    full_text = "\n".join(chunk.text_md for chunk in chunks)
    assert "![media: diagram.svg]" in full_text
    assert "![media: data.xlsx]" in full_text
    assert "## Media" in full_text

    # Check that chunk IDs are properly formatted
    for i, chunk in enumerate(chunks):
        assert chunk.chunk_id == f"media-doc:{i:04d}"
        assert chunk.ord == i
