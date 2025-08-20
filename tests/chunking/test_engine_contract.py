"""Tests for chunking engine contracts and guarantees."""

from trailblazer.pipeline.steps.chunk.engine import chunk_document
from trailblazer.pipeline.steps.chunk.boundaries import count_tokens


class TestEngineContract:
    """Test engine contracts and guarantees."""

    def test_required_traceability_fields(self):
        """Test that every chunk has required traceability fields."""
        doc_id = "test-doc-123"
        text = "This is a test document with some content."
        title = "Test Document"
        url = "https://example.com/doc/123"
        source_system = "confluence"
        labels = ["test", "documentation"]
        space = {"id": "SPACE123", "key": "TEST"}
        media_refs = [{"type": "image", "ref": "image1.png"}]

        chunks = chunk_document(
            doc_id=doc_id,
            text_md=text,
            title=title,
            url=url,
            source_system=source_system,
            labels=labels,
            space=space,
            media_refs=media_refs,
            hard_max_tokens=800,
        )

        assert len(chunks) > 0

        for chunk in chunks:
            # Required traceability fields
            assert chunk.doc_id == doc_id
            assert chunk.title == title
            assert chunk.url == url
            assert chunk.source_system == source_system
            assert chunk.labels == labels
            assert chunk.space == space
            assert chunk.media_refs == media_refs

            # Must have either title or url
            assert chunk.title or chunk.url

            # Must have source_system
            assert chunk.source_system

    def test_chunk_id_deterministic(self):
        """Test that chunk IDs are deterministic across runs."""
        doc_id = "test-doc-456"
        text = "This is test content for deterministic chunk ID testing."

        # Run chunking multiple times
        chunks1 = chunk_document(
            doc_id=doc_id, text_md=text, source_system="test"
        )
        chunks2 = chunk_document(
            doc_id=doc_id, text_md=text, source_system="test"
        )
        chunks3 = chunk_document(
            doc_id=doc_id, text_md=text, source_system="test"
        )

        # Should produce identical chunk IDs
        assert len(chunks1) == len(chunks2) == len(chunks3)

        for i in range(len(chunks1)):
            assert (
                chunks1[i].chunk_id
                == chunks2[i].chunk_id
                == chunks3[i].chunk_id
            )
            assert chunks1[i].ord == chunks2[i].ord == chunks3[i].ord

    def test_overlap_tokens_applied_all_strategies(self):
        """Test that overlap_tokens is actually present across all split strategies."""

        # Test with content that will trigger different strategies
        test_cases = [
            # Paragraph splitting
            {
                "text": "\n\n".join(
                    [
                        f"This is paragraph number {i} with sufficient content to test overlap behavior in paragraph-based splitting."
                        for i in range(10)
                    ]
                ),
                "expected_strategy": "paragraph",
            },
            # Sentence splitting
            {
                "text": ". ".join(
                    [
                        f"This is sentence number {i} with content to test overlap"
                        for i in range(15)
                    ]
                )
                + ".",
                "expected_strategy": "sentence",
            },
            # Token window fallback
            {
                "text": " ".join([f"word{i}" for i in range(100)]),
                "expected_strategy": "token-window",
            },
        ]

        for case in test_cases:
            chunks = chunk_document(
                doc_id="overlap-test",
                text_md=case["text"],
                source_system="test",
                hard_max_tokens=100,  # Force splitting
                overlap_tokens=20,
            )

            if len(chunks) > 1:
                # Verify overlap exists between adjacent chunks
                for i in range(len(chunks) - 1):
                    chunk1_text = chunks[i].text_md
                    chunk2_text = chunks[i + 1].text_md

                    # Extract words from end of first chunk and start of second
                    chunk1_words = chunk1_text.split()[-10:]  # Last 10 words
                    chunk2_words = chunk2_text.split()[:10]  # First 10 words

                    # Should have some overlap
                    overlap_found = any(
                        word in chunk2_words for word in chunk1_words
                    )
                    assert (
                        overlap_found
                    ), f"No overlap found between chunks {i} and {i + 1} for strategy {case['expected_strategy']}"

    def test_hard_token_cap_never_exceeded(self):
        """Test that hard_max_tokens is never exceeded, even with edge cases."""

        # Test various challenging content types
        test_cases = [
            # Very long single sentence
            "This is an extremely long sentence that goes on and on and on with lots of words and content that should definitely exceed the token limit but must be handled properly by the chunker without ever exceeding the hard cap even in edge cases.",
            # Giant code block
            "```python\n"
            + "\n".join(
                [
                    f"def function_{i}(): return 'very long result string that takes many tokens'"
                    for i in range(50)
                ]
            )
            + "\n```",
            # Large table
            "| Col1 | Col2 | Col3 |\n|------|------|------|\n"
            + "\n".join(
                [
                    f"| Very long data entry {i} | Another long entry | Third column data |"
                    for i in range(30)
                ]
            ),
            # Mixed content
            "# Title\n\nSome text.\n\n```code\nfunction() { return 'long string'; }\n```\n\n| Table | Data |\n|-------|------|\n| Row1  | Data |\n\nMore text content.",
        ]

        hard_cap = 50  # Very restrictive to force edge cases

        for i, text in enumerate(test_cases):
            chunks = chunk_document(
                doc_id=f"hard-cap-test-{i}",
                text_md=text,
                source_system="test",
                hard_max_tokens=hard_cap,
                overlap_tokens=10,
            )

            assert len(chunks) > 0, f"No chunks produced for test case {i}"

            for j, chunk in enumerate(chunks):
                # Re-tokenize to verify
                actual_tokens = count_tokens(chunk.text_md)

                assert (
                    actual_tokens <= hard_cap
                ), f"Chunk {j} in test case {i} has {actual_tokens} tokens, exceeding hard cap of {hard_cap}"
                assert (
                    chunk.token_count <= hard_cap
                ), f"Reported token count {chunk.token_count} exceeds hard cap"

    def test_chunk_metadata_complete(self):
        """Test that all chunk metadata is properly populated."""
        chunks = chunk_document(
            doc_id="metadata-test",
            text_md="# Test\n\nThis is test content.",
            title="Test Document",
            url="https://example.com",
            source_system="confluence",
            labels=["test"],
            space={"id": "123", "key": "TEST"},
            media_refs=[{"type": "image", "ref": "test.png"}],
        )

        assert len(chunks) == 1
        chunk = chunks[0]

        # Basic fields
        assert chunk.chunk_id == "metadata-test:0000"
        assert chunk.ord == 0
        assert chunk.char_count > 0
        assert chunk.token_count > 0
        assert chunk.split_strategy in [
            "no-split",
            "heading",
            "paragraph",
            "sentence",
            "token-window",
        ]

        # Traceability fields
        assert chunk.doc_id == "metadata-test"
        assert chunk.title == "Test Document"
        assert chunk.url == "https://example.com"
        assert chunk.source_system == "confluence"
        assert chunk.labels == ["test"]
        assert chunk.space == {"id": "123", "key": "TEST"}
        assert chunk.media_refs == [{"type": "image", "ref": "test.png"}]
