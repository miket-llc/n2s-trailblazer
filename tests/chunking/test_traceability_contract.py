"""
Test traceability contract enforcement for chunking v2.2.
"""

from trailblazer.pipeline.steps.chunk.engine import chunk_document
from trailblazer.pipeline.steps.chunk.verify import verify_chunks
import tempfile
import json
from pathlib import Path


def test_every_chunk_carries_required_fields():
    """Test that every chunk carries title|url and source_system."""
    doc_text = """
# Test Document

This is the first paragraph.

This is the second paragraph.

This is the third paragraph.
"""

    chunks = chunk_document(
        doc_id="test_doc",
        text_md=doc_text,
        title="Test Document Title",
        url="https://example.com/test-doc",
        source_system="confluence",
        labels=["test", "documentation"],
        space={"key": "TEST", "name": "Test Space"},
        hard_max_tokens=800,
        min_tokens=120,
        soft_min_tokens=200,
        hard_min_tokens=80,
        orphan_heading_merge=True,
        small_tail_merge=True,
    )

    assert len(chunks) > 0, "Should create at least one chunk"

    for chunk in chunks:
        # Every chunk must have source_system
        assert (
            chunk.source_system
        ), f"Chunk {chunk.chunk_id} missing source_system"
        assert chunk.source_system == "confluence"

        # Every chunk must have either title or url (or both)
        has_title = bool(chunk.title and chunk.title.strip())
        has_url = bool(chunk.url and chunk.url.strip())
        assert (
            has_title or has_url
        ), f"Chunk {chunk.chunk_id} missing both title and url"

        # Verify specific values are carried through
        if has_title:
            assert chunk.title == "Test Document Title"
        if has_url:
            assert chunk.url == "https://example.com/test-doc"

        # Verify optional fields are carried through
        assert chunk.labels == ["test", "documentation"]
        assert chunk.space == {"key": "TEST", "name": "Test Space"}


def test_missing_title_and_url_fails_verification():
    """Test that chunks missing both title and url fail verification."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Create test run with chunks missing traceability
        run_dir = temp_path / "runs" / "test_run"
        chunk_dir = run_dir / "chunk"
        chunk_dir.mkdir(parents=True, exist_ok=True)

        # Create chunks with missing traceability fields
        bad_chunks = [
            {
                "chunk_id": "test_doc:0001",
                "text_md": "Chunk with no title or url",
                "token_count": 250,
                "char_count": 26,
                "source_system": "test",  # Has source_system but no title/url
                "split_strategy": "paragraph",
            },
            {
                "chunk_id": "test_doc:0002",
                "text_md": "Chunk with empty title and url",
                "token_count": 250,
                "char_count": 31,
                "title": "",  # Empty title
                "url": "",  # Empty url
                "source_system": "test",
                "split_strategy": "paragraph",
            },
        ]

        chunks_file = chunk_dir / "chunks.ndjson"
        with open(chunks_file, "w") as f:
            for chunk in bad_chunks:
                f.write(json.dumps(chunk) + "\n")

        # Run verification with traceability required
        result = verify_chunks(
            runs_glob=str(temp_path / "runs" / "*"),
            max_tokens=800,
            soft_min=200,
            hard_min=80,
            require_traceability=True,
            out_dir=str(temp_path / "verify_output"),
        )

        # Should fail due to missing traceability
        assert result["status"] == "FAIL"
        assert result["violations"]["missing_traceability"] == 2

        # Check that missing_traceability.json was created
        output_dirs = list(Path(temp_path / "verify_output").glob("*"))
        assert len(output_dirs) == 1
        output_dir = output_dirs[0]

        missing_file = output_dir / "missing_traceability.json"
        assert missing_file.exists()

        with open(missing_file) as f:
            missing_data = json.load(f)
            assert len(missing_data) == 2

            # Check specific missing fields are identified
            for item in missing_data:
                assert "missing_fields" in item
                fields = item["missing_fields"]
                # Should identify that title and url are missing (but not source_system)
                assert fields.get("title") is True
                assert fields.get("url") is True
                assert fields.get("source_system") is False


def test_missing_source_system_fails_verification():
    """Test that chunks missing source_system fail verification."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Create test run with chunks missing source_system
        run_dir = temp_path / "runs" / "test_run"
        chunk_dir = run_dir / "chunk"
        chunk_dir.mkdir(parents=True, exist_ok=True)

        # Create chunk with title/url but no source_system
        bad_chunks = [
            {
                "chunk_id": "test_doc:0001",
                "text_md": "Chunk with title but no source_system",
                "token_count": 250,
                "char_count": 37,
                "title": "Test Document",
                "url": "https://example.com/test",
                # Missing source_system
                "split_strategy": "paragraph",
            }
        ]

        chunks_file = chunk_dir / "chunks.ndjson"
        with open(chunks_file, "w") as f:
            for chunk in bad_chunks:
                f.write(json.dumps(chunk) + "\n")

        # Run verification
        result = verify_chunks(
            runs_glob=str(temp_path / "runs" / "*"),
            max_tokens=800,
            soft_min=200,
            hard_min=80,
            require_traceability=True,
            out_dir=str(temp_path / "verify_output"),
        )

        # Should fail due to missing source_system
        assert result["status"] == "FAIL"
        assert result["violations"]["missing_traceability"] == 1


def test_good_traceability_passes_verification():
    """Test that chunks with proper traceability pass verification."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Create test run with good chunks
        run_dir = temp_path / "runs" / "test_run"
        chunk_dir = run_dir / "chunk"
        chunk_dir.mkdir(parents=True, exist_ok=True)

        # Create chunks with all required traceability fields
        good_chunks = [
            {
                "chunk_id": "test_doc:0001",
                "text_md": "Well-traced chunk with all fields",
                "token_count": 250,
                "char_count": 33,
                "title": "Test Document",
                "url": "https://example.com/test",
                "source_system": "confluence",
                "labels": ["test"],
                "space": {"key": "TEST"},
                "split_strategy": "paragraph",
            },
            {
                "chunk_id": "test_doc:0002",
                "text_md": "Another well-traced chunk",
                "token_count": 220,
                "char_count": 25,
                "title": "Test Document",  # Has title, no URL needed
                "source_system": "dita",
                "split_strategy": "paragraph",
            },
            {
                "chunk_id": "test_doc:0003",
                "text_md": "URL-only traced chunk",
                "token_count": 200,
                "char_count": 21,
                "url": "https://example.com/test/page3",  # Has URL, no title needed
                "source_system": "confluence",
                "split_strategy": "paragraph",
            },
        ]

        chunks_file = chunk_dir / "chunks.ndjson"
        with open(chunks_file, "w") as f:
            for chunk in good_chunks:
                f.write(json.dumps(chunk) + "\n")

        # Run verification
        result = verify_chunks(
            runs_glob=str(temp_path / "runs" / "*"),
            max_tokens=800,
            soft_min=200,
            hard_min=80,
            require_traceability=True,
            out_dir=str(temp_path / "verify_output"),
        )

        # Should pass traceability checks
        assert result["violations"]["missing_traceability"] == 0

        # Overall status depends on other factors (like coverage gaps)
        # but traceability should not be the cause of failure


def test_optional_fields_preserved():
    """Test that optional traceability fields (labels, space, media_refs) are preserved."""
    doc_text = "Test document content for traceability testing."

    chunks = chunk_document(
        doc_id="test_doc",
        text_md=doc_text,
        title="Test Document",
        url="https://example.com/test",
        source_system="confluence",
        labels=["important", "testing", "v2.2"],
        space={"key": "PROJ", "name": "Project Space", "id": 12345},
        media_refs=[
            {"type": "image", "ref": "diagram.png"},
            {"type": "attachment", "ref": "spec.pdf"},
        ],
        hard_max_tokens=800,
        min_tokens=120,
        soft_min_tokens=200,
        hard_min_tokens=80,
    )

    assert len(chunks) > 0

    for chunk in chunks:
        # Verify optional fields are preserved exactly
        assert chunk.labels == ["important", "testing", "v2.2"]
        assert chunk.space == {
            "key": "PROJ",
            "name": "Project Space",
            "id": 12345,
        }
        assert chunk.media_refs == [
            {"type": "image", "ref": "diagram.png"},
            {"type": "attachment", "ref": "spec.pdf"},
        ]


def test_traceability_with_empty_optional_fields():
    """Test that chunks work correctly with empty optional fields."""
    doc_text = "Test document with minimal traceability."

    chunks = chunk_document(
        doc_id="test_doc",
        text_md=doc_text,
        title="Test Document",
        url="https://example.com/test",
        source_system="dita",
        labels=[],  # Empty labels
        space=None,  # No space
        media_refs=[],  # No media refs
        hard_max_tokens=800,
        min_tokens=120,
        soft_min_tokens=200,
        hard_min_tokens=80,
    )

    assert len(chunks) > 0

    for chunk in chunks:
        # Required fields should be present
        assert chunk.title == "Test Document"
        assert chunk.url == "https://example.com/test"
        assert chunk.source_system == "dita"

        # Optional fields should be empty but not cause errors
        assert chunk.labels == []
        assert chunk.space is None
        assert chunk.media_refs == []
