# Test constants for magic numbers
EXPECTED_COUNT_2 = 2
EXPECTED_COUNT_3 = 3
EXPECTED_COUNT_4 = 4

"""Test that embed loader bootstraps documents when enriched.jsonl is missing."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from trailblazer.pipeline.steps.embed.loader import load_chunks_to_db

# Mark all tests as integration tests (need database)
pytestmark = pytest.mark.integration


@pytest.fixture
def mock_session_factory():
    """Mock database session factory."""
    mock_session = MagicMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_factory.return_value.__exit__ = MagicMock(return_value=None)
    return mock_factory, mock_session


@pytest.fixture
def mock_embedder():
    """Mock embedding provider."""
    mock_embedder = MagicMock()
    mock_embedder.provider_name = "dummy"
    mock_embedder.dim = 1536
    mock_embedder.embed_texts.return_value = [[0.1] * 1536]
    return mock_embedder


def create_run_without_enriched(temp_dir: Path, run_id: str):
    """Create a test run with chunks but no enriched.jsonl."""
    run_dir = temp_dir / "var" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Create chunks.ndjson with traceability info
    chunk_dir = run_dir / "chunk"
    chunk_dir.mkdir()
    chunks_file = chunk_dir / "chunks.ndjson"

    chunk_data = {
        "chunk_id": "confluence:123:chunk1",
        "text_md": "This is the content of the document chunk",
        "token_count": 15,
        "traceability": {
            "title": "Test Document Title",
            "url": "https://confluence.example.com/display/SPACE/Test+Document",
            "source_system": "confluence",
            "space_key": "TESTSPACE",
            "labels": ["important", "documentation"],
            "space": "Test Space",
        },
    }

    with open(chunks_file, "w") as f:
        f.write(json.dumps(chunk_data) + "\n")

    # Deliberately do NOT create enrich directory or enriched.jsonl
    return chunks_file


def create_run_with_mismatched_enriched(temp_dir: Path, run_id: str):
    """Create a test run where enriched.jsonl doesn't contain the doc from chunks."""
    run_dir = temp_dir / "var" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Create chunks.ndjson
    chunk_dir = run_dir / "chunk"
    chunk_dir.mkdir()
    chunks_file = chunk_dir / "chunks.ndjson"

    chunk_data = {
        "chunk_id": "doc_missing:chunk1",
        "text_md": "Content from document not in enriched.jsonl",
        "token_count": 12,
        "traceability": {
            "title": "Missing Document",
            "url": "https://example.com/missing",
            "source_system": "confluence",
            "space_key": "MISSING",
        },
    }

    with open(chunks_file, "w") as f:
        f.write(json.dumps(chunk_data) + "\n")

    # Create enriched.jsonl but with different document
    enrich_dir = run_dir / "enrich"
    enrich_dir.mkdir()
    enriched_file = enrich_dir / "enriched.jsonl"

    different_doc = {
        "id": "doc_different",  # Different from doc_missing
        "title": "Different Document",
        "quality_score": 0.9,
        "text_md": "This is a different document entirely",
        "source_system": "confluence",
    }

    with open(enriched_file, "w") as f:
        f.write(json.dumps(different_doc) + "\n")

    return chunks_file, enriched_file


def test_bootstrap_doc_missing_enriched(mock_session_factory, mock_embedder):
    """Test document bootstrap when enriched.jsonl is missing entirely."""
    mock_factory, mock_session = mock_session_factory

    # Mock database queries to simulate no existing document
    mock_session.query.return_value.filter_by.return_value.first.return_value = None

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        run_id = "test_bootstrap_missing"

        create_run_without_enriched(temp_path, run_id)

        # Patch dependencies
        with (
            patch(
                "trailblazer.core.paths.runs",
                return_value=temp_path / "var" / "runs",
            ),
            patch(
                "trailblazer.pipeline.steps.embed.loader.get_session_factory",
                return_value=mock_factory,
            ),
            patch(
                "trailblazer.pipeline.steps.embed.loader.get_embedding_provider",
                return_value=mock_embedder,
            ),
            patch("trailblazer.pipeline.steps.embed.loader.upsert_document") as mock_upsert_doc,
            patch("trailblazer.pipeline.steps.embed.loader.upsert_chunk_embedding") as mock_upsert_chunk,
            patch("trailblazer.core.progress.get_progress") as mock_progress,
            patch("trailblazer.obs.events.EventEmitter") as mock_event_emitter,
        ):
            mock_progress.return_value.enabled = False
            mock_event_emitter_instance = MagicMock()
            mock_event_emitter.return_value = mock_event_emitter_instance
            mock_event_emitter.return_value.__enter__ = MagicMock(return_value=mock_event_emitter_instance)
            mock_event_emitter.return_value.__exit__ = MagicMock(return_value=None)

            # Run loader
            result = load_chunks_to_db(
                run_id=run_id,
                provider_name="dummy",
                dimension=1536,
                batch_size=10,
            )

            # Should successfully embed the chunk
            assert result["chunks_embedded"] == 1, f"Expected 1 chunk embedded, got {result['chunks_embedded']}"

            # Verify document was bootstrapped
            mock_upsert_doc.assert_called_once()
            doc_call_args = mock_upsert_doc.call_args[0][1]  # Second arg is doc_data

            # Verify bootstrapped document data
            assert doc_call_args["doc_id"] == "confluence:123"
            assert doc_call_args["title"] == "Test Document Title"
            assert doc_call_args["url"] == "https://confluence.example.com/display/SPACE/Test+Document"
            assert doc_call_args["source_system"] == "confluence"
            assert doc_call_args["space_key"] == "TESTSPACE"
            assert doc_call_args["meta"]["bootstrapped"] is True
            assert doc_call_args["meta"]["labels"] == [
                "important",
                "documentation",
            ]
            assert doc_call_args["meta"]["space"] == "Test Space"

            # Verify content hash is deterministic (based on text_md)
            import hashlib

            expected_hash = hashlib.sha256(b"This is the content of the document chunk").hexdigest()
            assert doc_call_args["content_sha256"] == expected_hash

            # Verify chunk embedding was created
            mock_upsert_chunk.assert_called_once()


def test_bootstrap_doc_mismatched_enriched(mock_session_factory, mock_embedder):
    """Test document bootstrap when enriched.jsonl exists but doesn't contain the doc."""
    mock_factory, mock_session = mock_session_factory

    # Mock database queries to simulate no existing document
    mock_session.query.return_value.filter_by.return_value.first.return_value = None

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        run_id = "test_bootstrap_mismatch"

        chunks_file, enriched_file = create_run_with_mismatched_enriched(temp_path, run_id)

        # Patch dependencies
        with (
            patch(
                "trailblazer.core.paths.runs",
                return_value=temp_path / "var" / "runs",
            ),
            patch(
                "trailblazer.pipeline.steps.embed.loader.get_session_factory",
                return_value=mock_factory,
            ),
            patch(
                "trailblazer.pipeline.steps.embed.loader.get_embedding_provider",
                return_value=mock_embedder,
            ),
            patch("trailblazer.pipeline.steps.embed.loader.upsert_document") as mock_upsert_doc,
            patch("trailblazer.pipeline.steps.embed.loader.upsert_chunk_embedding"),
            patch("trailblazer.core.progress.get_progress") as mock_progress,
            patch("trailblazer.obs.events.EventEmitter") as mock_event_emitter,
        ):
            mock_progress.return_value.enabled = False
            mock_event_emitter_instance = MagicMock()
            mock_event_emitter.return_value = mock_event_emitter_instance
            mock_event_emitter.return_value.__enter__ = MagicMock(return_value=mock_event_emitter_instance)
            mock_event_emitter.return_value.__exit__ = MagicMock(return_value=None)

            # Run loader
            result = load_chunks_to_db(
                run_id=run_id,
                provider_name="dummy",
                dimension=1536,
                batch_size=10,
            )

            # Should successfully embed the chunk
            assert result["chunks_embedded"] == 1, f"Expected 1 chunk embedded, got {result['chunks_embedded']}"

            # Verify document was bootstrapped (not using enriched.jsonl data)
            mock_upsert_doc.assert_called_once()
            doc_call_args = mock_upsert_doc.call_args[0][1]

            # Should use traceability data, not enriched.jsonl data
            assert doc_call_args["doc_id"] == "doc_missing"
            assert doc_call_args["title"] == "Missing Document"
            assert doc_call_args["url"] == "https://example.com/missing"
            assert doc_call_args["source_system"] == "confluence"
            assert doc_call_args["space_key"] == "MISSING"
            assert doc_call_args["meta"]["bootstrapped"] is True


def test_bootstrap_doc_minimal_traceability(mock_session_factory, mock_embedder):
    """Test document bootstrap with minimal traceability information."""
    mock_factory, mock_session = mock_session_factory
    mock_session.query.return_value.filter_by.return_value.first.return_value = None

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        run_id = "test_bootstrap_minimal"

        # Create chunk with minimal traceability
        run_dir = temp_path / "var" / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        chunk_dir = run_dir / "chunk"
        chunk_dir.mkdir()
        chunks_file = chunk_dir / "chunks.ndjson"

        chunk_data = {
            "chunk_id": "minimal_doc:chunk1",
            "text_md": "Minimal content",
            "token_count": 5,
            "traceability": {},  # Empty traceability
        }

        with open(chunks_file, "w") as f:
            f.write(json.dumps(chunk_data) + "\n")

        # Patch dependencies
        with (
            patch(
                "trailblazer.core.paths.runs",
                return_value=temp_path / "var" / "runs",
            ),
            patch(
                "trailblazer.pipeline.steps.embed.loader.get_session_factory",
                return_value=mock_factory,
            ),
            patch(
                "trailblazer.pipeline.steps.embed.loader.get_embedding_provider",
                return_value=mock_embedder,
            ),
            patch("trailblazer.pipeline.steps.embed.loader.upsert_document") as mock_upsert_doc,
            patch("trailblazer.core.progress.get_progress") as mock_progress,
            patch("trailblazer.obs.events.EventEmitter") as mock_event_emitter,
        ):
            mock_progress.return_value.enabled = False
            mock_event_emitter_instance = MagicMock()
            mock_event_emitter.return_value = mock_event_emitter_instance
            mock_event_emitter.return_value.__enter__ = MagicMock(return_value=mock_event_emitter_instance)
            mock_event_emitter.return_value.__exit__ = MagicMock(return_value=None)

            # Run loader
            result = load_chunks_to_db(
                run_id=run_id,
                provider_name="dummy",
                dimension=1536,
                batch_size=10,
            )

            # Should still work with minimal data
            assert result["chunks_embedded"] == 1

            # Verify document was bootstrapped with defaults
            mock_upsert_doc.assert_called_once()
            doc_call_args = mock_upsert_doc.call_args[0][1]

            assert doc_call_args["doc_id"] == "minimal_doc"
            assert doc_call_args["title"] == "Document minimal_doc"  # Default title
            assert doc_call_args["source_system"] == "unknown"  # Default source
            assert doc_call_args["url"] is None
            assert doc_call_args["space_key"] is None
            assert doc_call_args["meta"]["bootstrapped"] is True


def test_bootstrap_doc_existing_document_updates_hash(mock_session_factory, mock_embedder):
    """Test that bootstrap updates content hash when document exists but content changed."""
    mock_factory, mock_session = mock_session_factory

    # Mock existing document with different content hash
    mock_existing_doc = MagicMock()
    mock_existing_doc.content_sha256 = "old_hash_value"
    mock_session.query.return_value.filter_by.return_value.first.return_value = mock_existing_doc

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        run_id = "test_bootstrap_update"

        create_run_without_enriched(temp_path, run_id)

        # Patch dependencies
        with (
            patch(
                "trailblazer.core.paths.runs",
                return_value=temp_path / "var" / "runs",
            ),
            patch(
                "trailblazer.pipeline.steps.embed.loader.get_session_factory",
                return_value=mock_factory,
            ),
            patch(
                "trailblazer.pipeline.steps.embed.loader.get_embedding_provider",
                return_value=mock_embedder,
            ),
            patch("trailblazer.pipeline.steps.embed.loader.upsert_document") as mock_upsert_doc,
            patch("trailblazer.core.progress.get_progress") as mock_progress,
            patch("trailblazer.obs.events.EventEmitter") as mock_event_emitter,
        ):
            mock_progress.return_value.enabled = False
            mock_event_emitter_instance = MagicMock()
            mock_event_emitter.return_value = mock_event_emitter_instance
            mock_event_emitter.return_value.__enter__ = MagicMock(return_value=mock_event_emitter_instance)
            mock_event_emitter.return_value.__exit__ = MagicMock(return_value=None)

            # Run loader
            result = load_chunks_to_db(
                run_id=run_id,
                provider_name="dummy",
                dimension=1536,
                batch_size=10,
            )

            # Should embed the chunk
            assert result["chunks_embedded"] == 1

            # Should not create new document (already exists)
            mock_upsert_doc.assert_not_called()

            # Should update existing document's content hash
            import hashlib

            expected_hash = hashlib.sha256(b"This is the content of the document chunk").hexdigest()
            assert mock_existing_doc.content_sha256 == expected_hash

            # Should commit the change
            mock_session.commit.assert_called()


def test_bootstrap_doc_no_traceability_chunk_id_fallback(mock_session_factory, mock_embedder):
    """Test bootstrap when chunk has no traceability but chunk_id can be parsed."""
    mock_factory, mock_session = mock_session_factory
    mock_session.query.return_value.filter_by.return_value.first.return_value = None

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        run_id = "test_bootstrap_no_trace"

        # Create chunk without traceability field at all
        run_dir = temp_path / "var" / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        chunk_dir = run_dir / "chunk"
        chunk_dir.mkdir()
        chunks_file = chunk_dir / "chunks.ndjson"

        chunk_data = {
            "chunk_id": "system:docid:chunk1",
            "text_md": "Content without traceability",
            "token_count": 8,
            # No traceability field
        }

        with open(chunks_file, "w") as f:
            f.write(json.dumps(chunk_data) + "\n")

        # Patch dependencies
        with (
            patch(
                "trailblazer.core.paths.runs",
                return_value=temp_path / "var" / "runs",
            ),
            patch(
                "trailblazer.pipeline.steps.embed.loader.get_session_factory",
                return_value=mock_factory,
            ),
            patch(
                "trailblazer.pipeline.steps.embed.loader.get_embedding_provider",
                return_value=mock_embedder,
            ),
            patch("trailblazer.pipeline.steps.embed.loader.upsert_document") as mock_upsert_doc,
            patch("trailblazer.core.progress.get_progress") as mock_progress,
            patch("trailblazer.obs.events.EventEmitter") as mock_event_emitter,
        ):
            mock_progress.return_value.enabled = False
            mock_event_emitter_instance = MagicMock()
            mock_event_emitter.return_value = mock_event_emitter_instance
            mock_event_emitter.return_value.__enter__ = MagicMock(return_value=mock_event_emitter_instance)
            mock_event_emitter.return_value.__exit__ = MagicMock(return_value=None)

            # Run loader
            result = load_chunks_to_db(
                run_id=run_id,
                provider_name="dummy",
                dimension=1536,
                batch_size=10,
            )

            # Should still work
            assert result["chunks_embedded"] == 1

            # Verify document was bootstrapped with minimal data
            mock_upsert_doc.assert_called_once()
            doc_call_args = mock_upsert_doc.call_args[0][1]

            assert doc_call_args["doc_id"] == "system:docid"
            assert doc_call_args["title"] == "Document system:docid"
            assert doc_call_args["source_system"] == "unknown"
            assert doc_call_args["meta"]["bootstrapped"] is True
