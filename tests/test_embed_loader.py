"""Tests for the embedding loader with idempotency and observability."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from trailblazer.pipeline.steps.embed.loader import (
    _compute_content_hash,
    _generate_assurance_report,
    _parse_timestamp,
    load_normalized_to_db,
)


def test_compute_content_hash_deterministic():
    """Test that content hash is deterministic."""
    record = {
        "title": "Test Document",
        "text_md": "# Title\n\nContent here.",
        "source": "confluence",
        "attachments": [
            {"filename": "image.png", "id": "att1", "media_type": "image/png"}
        ],
    }

    hash1 = _compute_content_hash(record)
    hash2 = _compute_content_hash(record)

    assert hash1 == hash2
    assert len(hash1) == 64  # SHA256 hex string


def test_compute_content_hash_different_content():
    """Test that different content produces different hashes."""
    record1 = {
        "title": "Test Document",
        "text_md": "Content 1",
        "source": "confluence",
        "attachments": [],
    }

    record2 = {
        "title": "Test Document",
        "text_md": "Content 2",  # Different content
        "source": "confluence",
        "attachments": [],
    }

    hash1 = _compute_content_hash(record1)
    hash2 = _compute_content_hash(record2)

    assert hash1 != hash2


def test_compute_content_hash_attachment_order():
    """Test that attachment order doesn't affect hash."""
    attachments1 = [
        {"filename": "a.png", "id": "att1", "media_type": "image/png"},
        {"filename": "b.pdf", "id": "att2", "media_type": "application/pdf"},
    ]

    attachments2 = [
        {"filename": "b.pdf", "id": "att2", "media_type": "application/pdf"},
        {"filename": "a.png", "id": "att1", "media_type": "image/png"},
    ]

    record1 = {
        "title": "Test",
        "text_md": "Content",
        "source": "confluence",
        "attachments": attachments1,
    }
    record2 = {
        "title": "Test",
        "text_md": "Content",
        "source": "confluence",
        "attachments": attachments2,
    }

    hash1 = _compute_content_hash(record1)
    hash2 = _compute_content_hash(record2)

    assert hash1 == hash2  # Order shouldn't matter


def test_parse_timestamp():
    """Test timestamp parsing."""
    # Valid ISO timestamp with Z
    ts1 = _parse_timestamp("2023-01-01T12:00:00Z")
    assert ts1 is not None
    assert ts1.year == 2023

    # Valid ISO timestamp with timezone
    ts2 = _parse_timestamp("2023-01-01T12:00:00+00:00")
    assert ts2 is not None

    # Invalid timestamp
    ts3 = _parse_timestamp("invalid-timestamp")
    assert ts3 is None

    # None/empty
    ts4 = _parse_timestamp(None)
    assert ts4 is None

    ts5 = _parse_timestamp("")
    assert ts5 is None


def test_generate_assurance_report():
    """Test assurance report generation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Mock the runs function to return our temp directory
        with patch("trailblazer.core.paths.runs") as mock_runs:
            runs_dir = Path(tmpdir) / "runs"
            runs_dir.mkdir()
            mock_runs.return_value = runs_dir

            run_id = "test-run-123"
            metrics = {
                "run_id": run_id,
                "provider": "dummy",
                "dimension": 384,
                "docs_total": 100,
                "docs_skipped": 20,
                "docs_embedded": 80,
                "chunks_total": 500,
                "chunks_skipped": 50,
                "chunks_embedded": 450,
                "duration_seconds": 45.67,
                "errors": [{"line": 10, "error": "test error"}],
                "completed_at": "2023-01-01T12:00:00Z",
            }

            _generate_assurance_report(run_id, metrics)

            # Check JSON report
            json_path = runs_dir / run_id / "embed_assurance.json"
            assert json_path.exists()

            with open(json_path) as f:
                data = json.load(f)

            assert data["run_id"] == run_id
            assert data["provider"] == "dummy"
            assert data["docs_total"] == 100
            assert data["chunks_embedded"] == 450
            assert len(data["errors"]) == 1

            # Check Markdown report
            md_path = runs_dir / run_id / "embed_assurance.md"
            assert md_path.exists()

            with open(md_path) as f:
                md_content = f.read()

            assert "# Embedding Assurance Report" in md_content
            assert run_id in md_content
            assert "dummy" in md_content
            assert "100" in md_content  # docs_total
            assert "test error" in md_content


def test_load_normalized_to_db_basic():
    """Test basic loading functionality with PostgreSQL."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test normalized file
        test_data = [
            {
                "id": "doc1",
                "title": "Test Document 1",
                "text_md": "# Test\n\nThis is test content.",
                "source_system": "confluence",
                "space_key": "TEST",
                "url": "https://example.com/doc1",
                "created_at": "2023-01-01T12:00:00Z",
                "updated_at": "2023-01-01T12:00:00Z",
                "attachments": [],
                "links": [],
                "labels": [],
            }
        ]

        input_file = Path(tmpdir) / "normalized.ndjson"
        with open(input_file, "w") as f:
            for record in test_data:
                f.write(json.dumps(record) + "\n")

        # Mock database operations
        with patch(
            "trailblazer.pipeline.steps.embed.loader.get_session_factory"
        ) as mock_factory:
            mock_session = MagicMock()
            mock_factory.return_value.return_value.__enter__ = MagicMock(
                return_value=mock_session
            )
            mock_factory.return_value.return_value.__exit__ = MagicMock(
                return_value=None
            )

            # Mock embedder
            with patch(
                "trailblazer.pipeline.steps.embed.loader.get_embedding_provider"
            ) as mock_provider:
                mock_embedder = MagicMock()
                mock_embedder.provider_name = "dummy"
                mock_embedder.dimension = 384
                mock_embedder.embed_batch.return_value = [
                    [0.1] * 384
                ]  # Mock embedding
                mock_provider.return_value = mock_embedder

                # Mock document existence check
                mock_session.query.return_value.filter_by.return_value.first.return_value = None

                # Run the loader
                metrics = load_normalized_to_db(
                    input_file=str(input_file),
                    provider_name="dummy",
                    max_docs=1,
                )

                # Check metrics
                assert metrics["docs_total"] == 1
                assert metrics["provider"] == "dummy"
                assert metrics["dimension"] == 384
                assert "duration_seconds" in metrics


def test_load_normalized_to_db_idempotency():
    """Test that loading is idempotent (skips unchanged documents)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test normalized file
        test_data = [
            {
                "id": "doc1",
                "title": "Test Document 1",
                "text_md": "# Test\n\nThis is test content.",
                "source_system": "confluence",
                "attachments": [],
            }
        ]

        input_file = Path(tmpdir) / "normalized.ndjson"
        with open(input_file, "w") as f:
            for record in test_data:
                f.write(json.dumps(record) + "\n")

        # Mock database operations
        with patch(
            "trailblazer.pipeline.steps.embed.loader.get_session_factory"
        ) as mock_factory:
            mock_session = MagicMock()
            mock_factory.return_value.return_value.__enter__ = MagicMock(
                return_value=mock_session
            )
            mock_factory.return_value.return_value.__exit__ = MagicMock(
                return_value=None
            )

            # Mock embedder
            with patch(
                "trailblazer.pipeline.steps.embed.loader.get_embedding_provider"
            ) as mock_provider:
                mock_embedder = MagicMock()
                mock_embedder.provider_name = "dummy"
                mock_embedder.dimension = 384
                mock_provider.return_value = mock_embedder

                # Mock existing document (same content hash)
                mock_existing_doc = MagicMock()
                mock_session.query.return_value.filter_by.return_value.first.return_value = mock_existing_doc

                # Run the loader
                metrics = load_normalized_to_db(
                    input_file=str(input_file),
                    provider_name="dummy",
                    max_docs=1,
                )

                # Should skip the document
                assert metrics["docs_skipped"] == 1
                assert metrics["docs_embedded"] == 0


def test_load_normalized_to_db_missing_file():
    """Test error handling for missing input file."""
    with pytest.raises(FileNotFoundError, match="Normalized file not found"):
        load_normalized_to_db(input_file="/nonexistent/file.ndjson")


def test_load_normalized_to_db_no_input():
    """Test error handling when neither run_id nor input_file provided."""
    with pytest.raises(
        ValueError, match="Either run_id or input_file must be provided"
    ):
        load_normalized_to_db()


def test_load_normalized_to_db_invalid_json():
    """Test handling of invalid JSON lines."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test file with invalid JSON
        input_file = Path(tmpdir) / "invalid.ndjson"
        with open(input_file, "w") as f:
            f.write('{"valid": "json"}\n')
            f.write("invalid json line\n")
            f.write('{"another": "valid"}\n')

        # Mock database operations
        with patch(
            "trailblazer.pipeline.steps.embed.loader.get_session_factory"
        ) as mock_factory:
            mock_session = MagicMock()
            mock_factory.return_value.return_value.__enter__ = MagicMock(
                return_value=mock_session
            )
            mock_factory.return_value.return_value.__exit__ = MagicMock(
                return_value=None
            )

            # Mock embedder
            with patch(
                "trailblazer.pipeline.steps.embed.loader.get_embedding_provider"
            ) as mock_provider:
                mock_embedder = MagicMock()
                mock_embedder.provider_name = "dummy"
                mock_embedder.dimension = 384
                mock_provider.return_value = mock_embedder

                # Mock no existing documents
                mock_session.query.return_value.filter_by.return_value.first.return_value = None

                # Mock stdout capture for events
                with patch("builtins.print"):
                    metrics = load_normalized_to_db(
                        input_file=str(input_file),
                        provider_name="dummy",
                    )

                    # Should have errors for invalid JSON
                    assert len(metrics["errors"]) >= 1


def test_load_normalized_to_db_missing_doc_id():
    """Test handling of records missing document ID."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test file with missing doc_id
        input_file = Path(tmpdir) / "missing_id.ndjson"
        with open(input_file, "w") as f:
            f.write('{"title": "No ID", "text_md": "content"}\n')

        # Mock database operations
        with patch(
            "trailblazer.pipeline.steps.embed.loader.get_session_factory"
        ) as mock_factory:
            mock_session = MagicMock()
            mock_factory.return_value.return_value.__enter__ = MagicMock(
                return_value=mock_session
            )
            mock_factory.return_value.return_value.__exit__ = MagicMock(
                return_value=None
            )

            # Mock embedder
            with patch(
                "trailblazer.pipeline.steps.embed.loader.get_embedding_provider"
            ) as mock_provider:
                mock_embedder = MagicMock()
                mock_embedder.provider_name = "dummy"
                mock_embedder.dimension = 384
                mock_provider.return_value = mock_embedder

                # Mock stdout capture for events
                with patch("builtins.print"):
                    metrics = load_normalized_to_db(
                        input_file=str(input_file),
                        provider_name="dummy",
                    )

                    # Should have error for missing doc_id
                    assert len(metrics["errors"]) >= 1
                    assert any(
                        "missing_doc_id" in str(error)
                        for error in metrics["errors"]
                    )


def test_load_normalized_to_db_chunking_error():
    """Test handling of chunking errors."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test file
        test_data = [{"id": "doc1", "title": "Test", "text_md": "content"}]

        input_file = Path(tmpdir) / "test.ndjson"
        with open(input_file, "w") as f:
            for record in test_data:
                f.write(json.dumps(record) + "\n")

        # Mock database operations
        with patch(
            "trailblazer.pipeline.steps.embed.loader.get_session_factory"
        ) as mock_factory:
            mock_session = MagicMock()
            mock_factory.return_value.return_value.__enter__ = MagicMock(
                return_value=mock_session
            )
            mock_factory.return_value.return_value.__exit__ = MagicMock(
                return_value=None
            )

            # Mock embedder
            with patch(
                "trailblazer.pipeline.steps.embed.loader.get_embedding_provider"
            ) as mock_provider:
                mock_embedder = MagicMock()
                mock_embedder.provider_name = "dummy"
                mock_embedder.dimension = 384
                mock_provider.return_value = mock_embedder

                # Mock no existing documents
                mock_session.query.return_value.filter_by.return_value.first.return_value = None

                # Mock chunking to raise an error
                with patch(
                    "trailblazer.pipeline.steps.embed.loader.chunk_normalized_record"
                ) as mock_chunk:
                    mock_chunk.side_effect = Exception("Chunking failed")

                    metrics = load_normalized_to_db(
                        input_file=str(input_file),
                        provider_name="dummy",
                    )

                    # Should have error for chunking failure
                    assert len(metrics["errors"]) >= 1
                    chunking_errors = [
                        e
                        for e in metrics["errors"]
                        if e.get("phase") == "chunking"
                    ]
                    assert len(chunking_errors) >= 1


def test_load_normalized_to_db_batch_processing():
    """Test batch processing of embeddings."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test file with multiple documents
        test_data = [
            {"id": f"doc{i}", "title": f"Doc {i}", "text_md": f"Content {i}"}
            for i in range(5)
        ]

        input_file = Path(tmpdir) / "test.ndjson"
        with open(input_file, "w") as f:
            for record in test_data:
                f.write(json.dumps(record) + "\n")

        # Mock database operations
        with patch(
            "trailblazer.pipeline.steps.embed.loader.get_session_factory"
        ) as mock_factory:
            mock_session = MagicMock()
            mock_factory.return_value.return_value.__enter__ = MagicMock(
                return_value=mock_session
            )
            mock_factory.return_value.return_value.__exit__ = MagicMock(
                return_value=None
            )

            # Mock embedder
            with patch(
                "trailblazer.pipeline.steps.embed.loader.get_embedding_provider"
            ) as mock_provider:
                mock_embedder = MagicMock()
                mock_embedder.provider_name = "dummy"
                mock_embedder.dimension = 384
                mock_embedder.embed_batch.return_value = [
                    [0.1] * 384
                ] * 10  # Mock batch embeddings
                mock_provider.return_value = mock_embedder

                # Mock no existing documents
                mock_session.query.return_value.filter_by.return_value.first.return_value = None
                mock_session.get.return_value = None  # No existing chunks

                metrics = load_normalized_to_db(
                    input_file=str(input_file),
                    provider_name="dummy",
                    batch_size=2,  # Small batch size to test batching
                )

                # Should process all documents
                assert metrics["docs_total"] == 5
                assert metrics["docs_embedded"] == 5

                # Should have called embed_batch multiple times due to small batch size
                assert mock_embedder.embed_batch.call_count >= 1


def test_load_normalized_to_db_postgresql_integration():
    """Test actual PostgreSQL database integration (not mocked)."""
    from trailblazer.db.engine import get_session

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test normalized file
        test_data = [
            {
                "id": "integration_doc_1",
                "title": "Integration Test Document",
                "text_md": "# Integration Test\n\nThis tests actual PostgreSQL integration.",
                "source_system": "confluence",
                "space_key": "INTEG",
                "url": "https://example.com/integration",
                "created_at": "2023-01-01T12:00:00Z",
                "updated_at": "2023-01-01T12:00:00Z",
                "attachments": [],
                "links": [],
                "labels": [],
            }
        ]

        input_file = Path(tmpdir) / "integration_test.ndjson"
        with open(input_file, "w") as f:
            for record in test_data:
                f.write(json.dumps(record) + "\n")

        # Run the loader with actual PostgreSQL database
        metrics = load_normalized_to_db(
            input_file=str(input_file),
            provider_name="dummy",
            max_docs=1,
        )

        # Verify metrics
        assert metrics["docs_total"] == 1
        assert metrics["docs_embedded"] == 1
        assert metrics["chunks_total"] > 0
        assert "duration_seconds" in metrics

        # Verify data was actually written to PostgreSQL
        with get_session() as session:
            from trailblazer.db.engine import Document, Chunk, ChunkEmbedding

            # Check document was created
            doc = session.query(Document).filter_by(doc_id="integration_doc_1").first()
            assert doc is not None
            assert doc.title == "Integration Test Document"
            assert doc.source_system == "confluence"

            # Check chunks were created
            chunks = session.query(Chunk).filter_by(doc_id="integration_doc_1").all()
            assert len(chunks) > 0

            # Check embeddings were created
            embeddings = session.query(ChunkEmbedding).join(Chunk).filter(
                Chunk.doc_id == "integration_doc_1"
            ).all()
            assert len(embeddings) > 0

            # Verify pgvector embeddings
            for emb in embeddings:
                assert emb.provider == "dummy"
                assert emb.dim > 0
                assert emb.embedding is not None
                # Verify it's a proper vector (not JSON string)
                import numpy as np
                assert isinstance(emb.embedding, (list, np.ndarray))
                assert len(emb.embedding) == emb.dim
