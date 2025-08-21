"""Test that embed loader honors doc_skiplist.json from preflight."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from trailblazer.pipeline.steps.embed.loader import load_chunks_to_db


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
    mock_embedder.embed_texts.return_value = [[0.1] * 1536, [0.2] * 1536]
    return mock_embedder


def create_test_run_with_skiplist(
    temp_dir: Path, run_id: str, skipped_docs: list
):
    """Create a test run directory with chunks and skiplist."""
    run_dir = temp_dir / "var" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Create chunks.ndjson with multiple documents
    chunk_dir = run_dir / "chunk"
    chunk_dir.mkdir()
    chunks_file = chunk_dir / "chunks.ndjson"

    chunks_data = [
        {
            "chunk_id": "doc1:chunk1",
            "text_md": "Content for document 1 chunk 1",
            "token_count": 10,
            "traceability": {
                "title": "Document 1",
                "url": "https://example.com/doc1",
                "source_system": "confluence",
                "space_key": "TEST",
            },
        },
        {
            "chunk_id": "doc1:chunk2",
            "text_md": "Content for document 1 chunk 2",
            "token_count": 8,
            "traceability": {
                "title": "Document 1",
                "url": "https://example.com/doc1",
                "source_system": "confluence",
                "space_key": "TEST",
            },
        },
        {
            "chunk_id": "doc2:chunk1",
            "text_md": "Content for document 2 chunk 1",
            "token_count": 12,
            "traceability": {
                "title": "Document 2",
                "url": "https://example.com/doc2",
                "source_system": "confluence",
                "space_key": "TEST",
            },
        },
        {
            "chunk_id": "doc3:chunk1",
            "text_md": "Content for document 3 chunk 1",
            "token_count": 15,
            "traceability": {
                "title": "Document 3",
                "url": "https://example.com/doc3",
                "source_system": "confluence",
                "space_key": "TEST",
            },
        },
    ]

    with open(chunks_file, "w") as f:
        for chunk in chunks_data:
            f.write(json.dumps(chunk) + "\n")

    # Create preflight directory with doc_skiplist.json
    preflight_dir = run_dir / "preflight"
    preflight_dir.mkdir()

    skiplist_data = {
        "skip": skipped_docs,
        "reason": "quality_below_min",
        "min_quality": 0.60,
        "total_docs": 3,
        "skipped_count": len(skipped_docs),
    }

    skiplist_file = preflight_dir / "doc_skiplist.json"
    with open(skiplist_file, "w") as f:
        json.dump(skiplist_data, f, indent=2)

    return chunks_file, skiplist_file


def test_loader_honors_skiplist_skips_correct_docs(
    mock_session_factory, mock_embedder
):
    """Test that loader skips exactly the documents listed in skiplist."""
    mock_factory, mock_session = mock_session_factory

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        run_id = "test_run_skiplist"

        # Create run with doc2 in skiplist
        skipped_docs = ["doc2"]
        chunks_file, skiplist_file = create_test_run_with_skiplist(
            temp_path, run_id, skipped_docs
        )

        # Patch paths and dependencies
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
            patch("trailblazer.core.progress.get_progress") as mock_progress,
            patch("trailblazer.obs.events.EventEmitter") as mock_event_emitter,
        ):
            # Setup mocks
            mock_progress.return_value.enabled = False
            mock_event_emitter_instance = MagicMock()
            mock_event_emitter.return_value = mock_event_emitter_instance
            mock_event_emitter.return_value.__enter__ = MagicMock(
                return_value=mock_event_emitter_instance
            )
            mock_event_emitter.return_value.__exit__ = MagicMock(
                return_value=None
            )

            # Run loader
            result = load_chunks_to_db(
                run_id=run_id,
                provider_name="dummy",
                dimension=1536,
                batch_size=10,
            )

            # Verify skiplist was loaded and applied
            assert result["chunks_skipped"] == 1, (
                f"Expected 1 chunk skipped (doc2), got {result['chunks_skipped']}"
            )
            assert result["chunks_embedded"] == 3, (
                f"Expected 3 chunks embedded (doc1:2 + doc3:1), got {result['chunks_embedded']}"
            )

            # Verify embedder was called with correct texts (should not include doc2)
            # Check what was embedded (current API uses embed() for single texts)
            embed_calls = mock_embedder.embed.call_args_list
            embedded_texts = []
            for call in embed_calls:
                embedded_texts.append(call[0][0])  # First arg is single text

            # Should have 3 texts (2 from doc1, 1 from doc3, none from doc2)
            assert len(embedded_texts) == 3, (
                f"Expected 3 texts embedded, got {len(embedded_texts)}"
            )

            # Verify no doc2 content was embedded
            for text in embedded_texts:
                assert "document 2" not in text.lower(), (
                    f"doc2 content should be skipped: {text}"
                )

            # Verify doc1 and doc3 content was embedded
            doc1_found = any(
                "document 1" in text.lower() for text in embedded_texts
            )
            doc3_found = any(
                "document 3" in text.lower() for text in embedded_texts
            )
            assert doc1_found, "doc1 content should be embedded"
            assert doc3_found, "doc3 content should be embedded"


def test_loader_honors_skiplist_multiple_docs(
    mock_session_factory, mock_embedder
):
    """Test that loader correctly skips multiple documents from skiplist."""
    mock_factory, mock_session = mock_session_factory

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        run_id = "test_run_multi_skip"

        # Create run with doc1 and doc3 in skiplist
        skipped_docs = ["doc1", "doc3"]
        chunks_file, skiplist_file = create_test_run_with_skiplist(
            temp_path, run_id, skipped_docs
        )

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
            patch("trailblazer.core.progress.get_progress") as mock_progress,
            patch("trailblazer.obs.events.EventEmitter") as mock_event_emitter,
        ):
            mock_progress.return_value.enabled = False
            mock_event_emitter_instance = MagicMock()
            mock_event_emitter.return_value = mock_event_emitter_instance
            mock_event_emitter.return_value.__enter__ = MagicMock(
                return_value=mock_event_emitter_instance
            )
            mock_event_emitter.return_value.__exit__ = MagicMock(
                return_value=None
            )

            # Run loader
            result = load_chunks_to_db(
                run_id=run_id,
                provider_name="dummy",
                dimension=1536,
                batch_size=10,
            )

            # Should skip 3 chunks (2 from doc1, 1 from doc3) and embed 1 (from doc2)
            assert result["chunks_skipped"] == 3, (
                f"Expected 3 chunks skipped, got {result['chunks_skipped']}"
            )
            assert result["chunks_embedded"] == 1, (
                f"Expected 1 chunk embedded, got {result['chunks_embedded']}"
            )

            # Verify only doc2 content was embedded
            embed_calls = mock_embedder.embed.call_args_list
            embedded_texts = []
            for call in embed_calls:
                embedded_texts.append(call[0][0])

            assert len(embedded_texts) == 1, (
                f"Expected 1 text embedded, got {len(embedded_texts)}"
            )
            assert "document 2" in embedded_texts[0].lower(), (
                "Only doc2 should be embedded"
            )


def test_loader_no_skiplist_embeds_all(mock_session_factory, mock_embedder):
    """Test that loader embeds all chunks when no skiplist exists."""
    mock_factory, mock_session = mock_session_factory

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        run_id = "test_run_no_skiplist"

        # Create run without skiplist
        run_dir = temp_path / "var" / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        chunk_dir = run_dir / "chunk"
        chunk_dir.mkdir()
        chunks_file = chunk_dir / "chunks.ndjson"

        chunks_data = [
            {
                "chunk_id": "doc1:chunk1",
                "text_md": "Content for document 1",
                "token_count": 10,
                "traceability": {
                    "title": "Document 1",
                    "source_system": "confluence",
                },
            },
            {
                "chunk_id": "doc2:chunk1",
                "text_md": "Content for document 2",
                "token_count": 12,
                "traceability": {
                    "title": "Document 2",
                    "source_system": "confluence",
                },
            },
        ]

        with open(chunks_file, "w") as f:
            for chunk in chunks_data:
                f.write(json.dumps(chunk) + "\n")

        # No preflight directory created (no skiplist)

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
            patch("trailblazer.core.progress.get_progress") as mock_progress,
            patch("trailblazer.obs.events.EventEmitter") as mock_event_emitter,
        ):
            mock_progress.return_value.enabled = False
            mock_event_emitter_instance = MagicMock()
            mock_event_emitter.return_value = mock_event_emitter_instance
            mock_event_emitter.return_value.__enter__ = MagicMock(
                return_value=mock_event_emitter_instance
            )
            mock_event_emitter.return_value.__exit__ = MagicMock(
                return_value=None
            )

            # Run loader
            result = load_chunks_to_db(
                run_id=run_id,
                provider_name="dummy",
                dimension=1536,
                batch_size=10,
            )

            # Should embed all chunks
            assert result["chunks_skipped"] == 0, (
                f"Expected 0 chunks skipped, got {result['chunks_skipped']}"
            )
            assert result["chunks_embedded"] == 2, (
                f"Expected 2 chunks embedded, got {result['chunks_embedded']}"
            )


def test_loader_empty_skiplist_embeds_all(mock_session_factory, mock_embedder):
    """Test that loader embeds all chunks when skiplist is empty."""
    mock_factory, mock_session = mock_session_factory

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        run_id = "test_run_empty_skiplist"

        # Create run with empty skiplist
        skipped_docs = []  # Empty list
        chunks_file, skiplist_file = create_test_run_with_skiplist(
            temp_path, run_id, skipped_docs
        )

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
            patch("trailblazer.core.progress.get_progress") as mock_progress,
            patch("trailblazer.obs.events.EventEmitter") as mock_event_emitter,
        ):
            mock_progress.return_value.enabled = False
            mock_event_emitter_instance = MagicMock()
            mock_event_emitter.return_value = mock_event_emitter_instance
            mock_event_emitter.return_value.__enter__ = MagicMock(
                return_value=mock_event_emitter_instance
            )
            mock_event_emitter.return_value.__exit__ = MagicMock(
                return_value=None
            )

            # Run loader
            result = load_chunks_to_db(
                run_id=run_id,
                provider_name="dummy",
                dimension=1536,
                batch_size=10,
            )

            # Should embed all chunks
            assert result["chunks_skipped"] == 0, (
                f"Expected 0 chunks skipped, got {result['chunks_skipped']}"
            )
            assert result["chunks_embedded"] == 4, (
                f"Expected 4 chunks embedded, got {result['chunks_embedded']}"
            )


def test_loader_skiplist_load_failure_continues(
    mock_session_factory, mock_embedder
):
    """Test that loader continues if skiplist loading fails."""
    mock_factory, mock_session = mock_session_factory

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        run_id = "test_run_bad_skiplist"

        # Create run with malformed skiplist
        run_dir = temp_path / "var" / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        chunk_dir = run_dir / "chunk"
        chunk_dir.mkdir()
        chunks_file = chunk_dir / "chunks.ndjson"

        chunk_data = {
            "chunk_id": "doc1:chunk1",
            "text_md": "Content for document 1",
            "token_count": 10,
            "traceability": {
                "title": "Document 1",
                "source_system": "confluence",
            },
        }

        with open(chunks_file, "w") as f:
            f.write(json.dumps(chunk_data) + "\n")

        # Create malformed skiplist (invalid JSON)
        preflight_dir = run_dir / "preflight"
        preflight_dir.mkdir()
        skiplist_file = preflight_dir / "doc_skiplist.json"
        with open(skiplist_file, "w") as f:
            f.write("{ invalid json")

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
            patch("trailblazer.core.progress.get_progress") as mock_progress,
            patch("trailblazer.obs.events.EventEmitter") as mock_event_emitter,
        ):
            mock_progress.return_value.enabled = False
            mock_event_emitter_instance = MagicMock()
            mock_event_emitter.return_value = mock_event_emitter_instance
            mock_event_emitter.return_value.__enter__ = MagicMock(
                return_value=mock_event_emitter_instance
            )
            mock_event_emitter.return_value.__exit__ = MagicMock(
                return_value=None
            )

            # Should not raise exception despite bad skiplist
            result = load_chunks_to_db(
                run_id=run_id,
                provider_name="dummy",
                dimension=1536,
                batch_size=10,
            )

            # Should proceed to embed all chunks (skiplist loading failed)
            assert result["chunks_embedded"] == 1, (
                f"Expected 1 chunk embedded, got {result['chunks_embedded']}"
            )
