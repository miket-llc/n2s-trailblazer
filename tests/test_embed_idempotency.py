"""Test that embedding is idempotent and dimension guard is enforced."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from trailblazer.pipeline.steps.embed.loader import load_chunks_to_db


class TestEmbedIdempotency:
    """Test that embedding is idempotent and dimension guard is enforced."""

    def test_idempotent_re_embed_no_skip(self, setup_test_db):
        """Test that re-embedding without --skip-unchanged doesn't double row counts."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create a test run directory structure
            run_id = "test_idempotent_run"
            run_dir = temp_path / "var" / "runs" / run_id
            run_dir.mkdir(parents=True)

            # Create chunks.ndjson with one document
            chunk_dir = run_dir / "chunk"
            chunk_dir.mkdir()

            chunks_data = [
                {
                    "chunk_id": "doc1:0001",
                    "doc_id": "doc1",
                    "text_md": "Test document content",
                    "token_count": 50,
                    "char_count": 200,
                    "ord": 1,
                    "chunk_type": "text",
                    "meta": {},
                    "traceability": {
                        "title": "Test Doc",
                        "source_system": "test",
                        "space_key": "TEST",
                    },
                }
            ]

            with open(chunk_dir / "chunks.ndjson", "w") as f:
                for chunk in chunks_data:
                    f.write(json.dumps(chunk) + "\n")

            # Mock the embedding provider
            with patch(
                "trailblazer.pipeline.steps.embed.loader.get_embedding_provider"
            ) as mock_get_provider:
                mock_provider = MagicMock()
                mock_provider.provider_name = "dummy"
                mock_provider.dimension = 1536
                mock_provider.embed_batch.return_value = [
                    [0.1] * 1536
                ]  # 1 embedding
                mock_get_provider.return_value = mock_provider

                # Mock the paths.runs() function to return our temp directory
                with patch("trailblazer.core.paths.runs") as mock_runs:
                    mock_runs.return_value = temp_path / "var" / "runs"

                    # Mock database session
                    with patch(
                        "trailblazer.pipeline.steps.embed.loader.get_session_factory"
                    ) as mock_session_factory:
                        mock_session = MagicMock()
                        mock_session_factory.return_value = mock_session

                        # Mock the database upsert functions
                        with patch(
                            "trailblazer.pipeline.steps.embed.loader.upsert_document"
                        ):
                            with patch(
                                "trailblazer.pipeline.steps.embed.loader.upsert_chunk"
                            ):
                                with patch(
                                    "trailblazer.pipeline.steps.embed.loader.upsert_chunk_embedding"
                                ):
                                    # First embedding
                                    result1 = load_chunks_to_db(
                                        run_id=run_id,
                                        provider_name="dummy",
                                        dimension=1536,
                                        batch_size=1,
                                    )

                                    # Second embedding (should be idempotent)
                                    result2 = load_chunks_to_db(
                                        run_id=run_id,
                                        provider_name="dummy",
                                        dimension=1536,
                                        batch_size=1,
                                    )

                                    # Both should embed the same chunks (idempotent)
                                    assert result1["chunks_embedded"] == 1, (
                                        "First run should embed 1 chunk"
                                    )
                                    assert result2["chunks_embedded"] == 1, (
                                        "Second run should embed 1 chunk (idempotent)"
                                    )

                                    # Both should process the same document
                                    assert result1["docs_total"] == 1, (
                                        "First run should process 1 document"
                                    )
                                    assert result2["docs_total"] == 1, (
                                        "Second run should process 1 document"
                                    )

    def test_idempotent_re_embed_with_skip(self, setup_test_db):
        """Test that re-embedding with --skip-unchanged skips unchanged runs."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create a test run directory structure
            run_id = "test_idempotent_skip_run"
            run_dir = temp_path / "var" / "runs" / run_id
            run_dir.mkdir(parents=True)

            # Create chunks.ndjson with one document
            chunk_dir = run_dir / "chunk"
            chunk_dir.mkdir()

            chunks_data = [
                {
                    "chunk_id": "doc1:0001",
                    "doc_id": "doc1",
                    "text_md": "Test document content",
                    "token_count": 50,
                    "char_count": 200,
                    "ord": 1,
                    "chunk_type": "text",
                    "meta": {},
                    "traceability": {
                        "title": "Test Doc",
                        "source_system": "test",
                        "space_key": "TEST",
                    },
                }
            ]

            with open(chunk_dir / "chunks.ndjson", "w") as f:
                for chunk in chunks_data:
                    f.write(json.dumps(chunk) + "\n")

            # Create enrich directory with fingerprints for changed_only test
            enrich_dir = run_dir / "enrich"
            enrich_dir.mkdir()

            # Create fingerprints.jsonl (current fingerprints)
            fingerprints_data = [
                {"doc_id": "doc1", "fingerprint": "test_fingerprint_123"}
            ]

            with open(enrich_dir / "fingerprints.jsonl", "w") as f:
                for fp in fingerprints_data:
                    f.write(json.dumps(fp) + "\n")

            # Create fingerprints.prev.jsonl (previous fingerprints - same as current to simulate no changes)
            with open(enrich_dir / "fingerprints.prev.jsonl", "w") as f:
                for fp in fingerprints_data:
                    f.write(json.dumps(fp) + "\n")

            # Mock the embedding provider
            with patch(
                "trailblazer.pipeline.steps.embed.loader.get_embedding_provider"
            ) as mock_get_provider:
                mock_provider = MagicMock()
                mock_provider.provider_name = "dummy"
                mock_provider.dimension = 1536
                mock_provider.embed_batch.return_value = [
                    [0.1] * 1536
                ]  # 1 embedding
                mock_get_provider.return_value = mock_provider

                # Mock the paths.runs() function to return our temp directory
                with patch("trailblazer.core.paths.runs") as mock_runs:
                    mock_runs.return_value = temp_path / "var" / "runs"

                    # Mock database session
                    with patch(
                        "trailblazer.pipeline.steps.embed.loader.get_session_factory"
                    ) as mock_session_factory:
                        mock_session = MagicMock()
                        mock_session_factory.return_value = mock_session

                        # Mock the database upsert functions
                        with patch(
                            "trailblazer.pipeline.steps.embed.loader.upsert_document"
                        ):
                            with patch(
                                "trailblazer.pipeline.steps.embed.loader.upsert_chunk"
                            ):
                                with patch(
                                    "trailblazer.pipeline.steps.embed.loader.upsert_chunk_embedding"
                                ):
                                    # First embedding
                                    result1 = load_chunks_to_db(
                                        run_id=run_id,
                                        provider_name="dummy",
                                        dimension=1536,
                                        batch_size=1,
                                    )

                                    # Second embedding with changed_only=True (simulating --skip-unchanged)
                                    result2 = load_chunks_to_db(
                                        run_id=run_id,
                                        provider_name="dummy",
                                        dimension=1536,
                                        batch_size=1,
                                        changed_only=True,
                                    )

                                    # First should embed normally
                                    assert result1["chunks_embedded"] == 1, (
                                        "First run should embed 1 chunk"
                                    )
                                    assert result1["docs_total"] == 1, (
                                        "First run should process 1 document"
                                    )

                                    # Second should skip (no changes) - this tests the changed_only logic
                                    # Note: The changed_only logic prevents embedding chunks but still processes documents
                                    assert result2["chunks_embedded"] == 0, (
                                        "Second run should skip unchanged chunks"
                                    )
                                    assert result2["docs_total"] == 1, (
                                        "Second run still processes documents but skips embedding"
                                    )
                                    assert result2["docs_unchanged"] == 1, (
                                        "Second run should mark document as unchanged"
                                    )

    def test_dimension_guard_enforced(self, setup_test_db):
        """Test that dimension guard enforces exactly 1536 everywhere."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create a test run directory structure
            run_id = "test_dimension_guard"
            run_dir = temp_path / "var" / "runs" / run_id
            run_dir.mkdir(parents=True)

            # Create chunks.ndjson with one document
            chunk_dir = run_dir / "chunk"
            chunk_dir.mkdir()

            chunks_data = [
                {
                    "chunk_id": "doc1:0001",
                    "doc_id": "doc1",
                    "text_md": "Test document content",
                    "token_count": 50,
                    "char_count": 200,
                    "ord": 1,
                    "chunk_type": "text",
                    "meta": {},
                    "traceability": {
                        "title": "Test Doc",
                        "source_system": "test",
                        "space_key": "TEST",
                    },
                }
            ]

            with open(chunk_dir / "chunks.ndjson", "w") as f:
                for chunk in chunks_data:
                    f.write(json.dumps(chunk) + "\n")

            # Mock the embedding provider with wrong dimension
            with patch(
                "trailblazer.pipeline.steps.embed.loader.get_embedding_provider"
            ) as mock_get_provider:
                mock_provider = MagicMock()
                mock_provider.provider_name = "dummy"
                mock_provider.dimension = 768  # Wrong dimension!
                mock_provider.embed_batch.return_value = [
                    [0.1] * 768
                ]  # Wrong dimension
                mock_get_provider.return_value = mock_provider

                # Mock the paths.runs() function to return our temp directory
                with patch("trailblazer.core.paths.runs") as mock_runs:
                    mock_runs.return_value = temp_path / "var" / "runs"

                    # Mock database session
                    with patch(
                        "trailblazer.pipeline.steps.embed.loader.get_session_factory"
                    ) as mock_session_factory:
                        mock_session = MagicMock()
                        mock_session_factory.return_value = mock_session

                        # Mock the database upsert functions
                        with patch(
                            "trailblazer.pipeline.steps.embed.loader.upsert_document"
                        ):
                            with patch(
                                "trailblazer.pipeline.steps.embed.loader.upsert_chunk"
                            ):
                                with patch(
                                    "trailblazer.pipeline.steps.embed.loader.upsert_chunk_embedding"
                                ):
                                    # This should raise an error due to dimension mismatch
                                    with pytest.raises(
                                        ValueError,
                                        match="Dimension mismatch: expected 1536, got 768",
                                    ):
                                        load_chunks_to_db(
                                            run_id=run_id,
                                            provider_name="dummy",
                                            dimension=768,  # Wrong dimension
                                            batch_size=1,
                                        )
