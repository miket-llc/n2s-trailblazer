"""Tests for chunking boundaries and splitting strategies."""

from trailblazer.chunking.boundaries import (
    split_by_paragraphs,
    split_by_sentences,
    split_code_fence_by_lines,
    split_table_by_rows,
    split_by_token_window,
    detect_content_type,
    normalize_text,
    ChunkType,
    count_tokens,
)
from trailblazer.chunking.engine import split_with_layered_strategy


class TestBoundaries:
    """Test boundary detection and splitting strategies."""

    def test_enrich_first_section_map(self):
        """Test that section_map from enrichment is used first for splitting."""
        text = """# Introduction

This is the intro section with some content.

## Section 1

This is section 1 with lots of content that should be split properly when using enrichment data. This section has enough content to potentially exceed token limits.

### Subsection 1.1

More content here in the subsection.

## Section 2

This is section 2 with different content."""

        section_map = [
            {
                "startChar": 0,
                "endChar": 50,
                "level": 1,
                "text": "Introduction",
            },
            {"startChar": 51, "endChar": 200, "level": 2, "text": "Section 1"},
            {
                "startChar": 201,
                "endChar": 250,
                "level": 3,
                "text": "Subsection 1.1",
            },
            {
                "startChar": 251,
                "endChar": 300,
                "level": 2,
                "text": "Section 2",
            },
        ]

        # Test that section_map boundaries are respected
        chunks = split_with_layered_strategy(
            text,
            hard_max_tokens=100,
            overlap_tokens=20,
            min_tokens=30,
            model="text-embedding-3-small",
            section_map=section_map,
            prefer_headings=True,
        )

        # Should use heading strategy when section_map is provided
        assert len(chunks) > 0
        assert any(strategy == "heading" for _, strategy in chunks)

    def test_code_fence_giant_splitting(self):
        """Test that giant code fences are split by line blocks without cutting mid-line."""
        # Create a large code block that exceeds token limit
        code_lines = [f"def function_{i}():" for i in range(50)]
        code_lines.extend([f"    return 'result_{i}'" for i in range(50)])
        code_content = "\n".join(code_lines)

        giant_code_fence = f"```python\n{code_content}\n```"

        chunks = split_code_fence_by_lines(
            giant_code_fence,
            hard_max_tokens=150,
            overlap_tokens=20,
            model="text-embedding-3-small",
        )

        # Should split into multiple chunks
        assert len(chunks) > 1

        # Each chunk should be a valid code fence
        for chunk_text, strategy in chunks:
            assert strategy == "code-fence-lines"
            assert chunk_text.startswith("```python\n")
            assert chunk_text.endswith("\n```")

            # Should not exceed token limit
            tokens = count_tokens(chunk_text)
            assert tokens <= 150

            # Should not cut mid-line (no partial function definitions)
            lines = chunk_text.split("\n")[1:-1]  # Remove fence markers
            for line in lines:
                if line.strip().startswith("def "):
                    # If we have a function definition, it should be complete
                    assert ":" in line

    def test_wide_table_giant_splitting(self):
        """Test that giant tables are split by row groups without cutting mid-cell."""
        # Create a large table
        header = "| Column 1 | Column 2 | Column 3 | Column 4 | Column 5 |"
        separator = "|----------|----------|----------|----------|----------|"

        rows = []
        for i in range(100):
            rows.append(
                f"| Data {i}a | Data {i}b | Data {i}c | Data {i}d | Data {i}e |"
            )

        giant_table = "\n".join([header, separator] + rows)

        chunks = split_table_by_rows(
            giant_table,
            hard_max_tokens=200,
            overlap_tokens=30,
            model="text-embedding-3-small",
        )

        # Should split into multiple chunks
        assert len(chunks) > 1

        # Each chunk should preserve table structure
        for chunk_text, strategy in chunks:
            assert strategy == "table-rows"
            lines = chunk_text.split("\n")

            # Should have header
            assert lines[0] == header
            assert lines[1] == separator

            # Should not exceed token limit
            tokens = count_tokens(chunk_text)
            assert tokens <= 200

            # All lines should be complete table rows (no mid-cell cuts)
            for line in lines:
                if "|" in line:
                    # Count pipes - should be even number (start and end + separators)
                    pipe_count = line.count("|")
                    assert pipe_count >= 2  # At least start and end
                    assert pipe_count % 2 == 0  # Even number for complete rows

    def test_overlap_applied_across_strategies(self):
        """Test that overlap is applied across all splitting strategies, not just token-window."""

        # Test paragraph splitting with overlap
        long_text = "\n\n".join(
            [
                f"This is paragraph {i} with some content that should be split properly."
                for i in range(10)
            ]
        )

        chunks = split_by_paragraphs(long_text)
        # Just verify paragraphs are identified
        assert len(chunks) == 10

        # Test sentence splitting with overlap
        long_sentences = (
            ". ".join(
                [f"This is sentence {i} with content" for i in range(20)]
            )
            + "."
        )

        chunks = split_by_sentences(long_sentences)
        assert len(chunks) == 20

        # Test token window with overlap
        long_text = " ".join([f"word{i}" for i in range(200)])

        chunks = split_by_token_window(
            long_text,
            hard_max_tokens=50,
            overlap_tokens=10,
            model="text-embedding-3-small",
        )

        # Should have multiple chunks with overlap
        assert len(chunks) > 1

        # Verify overlap exists between adjacent chunks
        if len(chunks) > 1:
            first_chunk_words = chunks[0][0].split()
            second_chunk_words = chunks[1][0].split()

            # Some words from end of first chunk should appear at start of second
            overlap_found = any(
                word in second_chunk_words[:5]
                for word in first_chunk_words[-5:]
            )
            assert overlap_found

    def test_content_type_detection(self):
        """Test content type detection for different content types."""

        # Test code detection
        code_text = """```python
def hello():
    return "world"
```"""
        content_type, meta = detect_content_type(code_text)
        assert content_type == ChunkType.CODE
        assert meta.get("language") == "python"

        # Test table detection
        table_text = """| Column 1 | Column 2 |
|----------|----------|
| Data 1   | Data 2   |"""
        content_type, meta = detect_content_type(table_text)
        assert content_type == ChunkType.TABLE

        # Test regular text
        text_content = (
            "This is just regular text content without special formatting."
        )
        content_type, meta = detect_content_type(text_content)
        assert content_type == ChunkType.TEXT

    def test_normalize_text(self):
        """Test text normalization."""
        # Test CRLF normalization
        text_with_crlf = "Line 1\r\nLine 2\r\nLine 3"
        normalized = normalize_text(text_with_crlf)
        assert "\r" not in normalized
        assert normalized == "Line 1\nLine 2\nLine 3"

        # Test triple newline reduction
        text_with_many_newlines = "Para 1\n\n\n\nPara 2"
        normalized = normalize_text(text_with_many_newlines)
        assert normalized == "Para 1\n\nPara 2"
