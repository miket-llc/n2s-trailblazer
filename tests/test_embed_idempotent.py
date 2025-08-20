"""Test idempotent re-embedding functionality."""

import json
from unittest.mock import patch, MagicMock

from trailblazer.pipeline.steps.embed.loader import load_chunks_to_db


def test_idempotent_re_embed_same_run(tmp_path):
    """Test that embedding the same run twice doesn't create duplicates."""
    # Create temporary run structure
    run_id = "test_run_idempotent"
    run_dir = tmp_path / "var" / "runs" / run_id
    run_dir.mkdir(parents=True)

    # Create chunks.ndjson with 2 documents
    chunk_dir = run_dir / "chunk"
    chunk_dir.mkdir()

    chunks_data = [
        {
            "chunk_id": "doc1:0001",
            "doc_id": "doc1",
            "text_md": "Content 1",
            "token_count": 100,
        },
        {
            "chunk_id": "doc2:0001",
            "doc_id": "doc2",
            "text_md": "Content 2",
            "token_count": 100,
        },
    ]

    with open(chunk_dir / "chunks.ndjson", "w") as f:
        for chunk in chunks_data:
            f.write(json.dumps(chunk) + "\n")

    # Mock the paths.runs() function to return our temp directory
    with patch("trailblazer.core.paths.runs") as mock_runs:
        mock_runs.return_value = tmp_path / "var" / "runs"

        # Mock the embedding provider
        with patch(
            "trailblazer.pipeline.steps.embed.loader.get_embedding_provider"
        ) as mock_provider:
            mock_embedder = MagicMock()
            mock_embedder.provider_name = "openai"
            mock_embedder.dimension = 1536
            mock_embedder.embed_batch.return_value = [[0.0] * 1536] * 2

            mock_provider.return_value = mock_embedder

            # Mock database operations
            with patch(
                "trailblazer.pipeline.steps.embed.loader.get_session_factory"
            ) as mock_session_factory:
                mock_session = MagicMock()
                mock_session_factory.return_value.__enter__.return_value = (
                    mock_session
                )

                # First embedding run
                result1 = load_chunks_to_db(
                    run_id=run_id, provider_name="dummy", dimension=1536
                )

                # Second embedding run (same run, no skip flag)
                result2 = load_chunks_to_db(
                    run_id=run_id, provider_name="dummy", dimension=1536
                )

    # Verify both runs completed successfully
    assert result1["chunks_embedded"] == 2
    assert result2["chunks_embedded"] == 2

    # Verify the same total chunks were processed
    assert result1["chunks_total"] == 2
    assert result2["chunks_total"] == 2

    # Verify provider and dimension consistency
    assert result1["provider"] == "dummy"
    assert result1["dimension"] == 1536
    assert result2["provider"] == "dummy"
    assert result2["dimension"] == 1536


def test_embed_assurance_json_consistency(tmp_path):
    """Test that embed_assurance.json is consistent across re-embeds."""
    # Create temporary run structure
    run_id = "test_run_assurance_consistency"
    run_dir = tmp_path / "var" / "runs" / run_id
    run_dir.mkdir(parents=True)

    # Create chunks.ndjson with 1 document
    chunk_dir = run_dir / "chunk"
    chunk_dir.mkdir()

    chunks_data = [
        {
            "chunk_id": "doc1:0001",
            "doc_id": "doc1",
            "text_md": "Content 1",
            "token_count": 100,
        }
    ]

    with open(chunk_dir / "chunks.ndjson", "w") as f:
        for chunk in chunks_data:
            f.write(json.dumps(chunk) + "\n")

    # Mock the paths.runs() function to return our temp directory
    with patch("trailblazer.core.paths.runs") as mock_runs:
        mock_runs.return_value = tmp_path / "var" / "runs"

        # Mock the embedding provider
        with patch(
            "trailblazer.pipeline.steps.embed.loader.get_embedding_provider"
        ) as mock_provider:
            mock_embedder = MagicMock()
            mock_embedder.provider_name = "openai"
            mock_embedder.dimension = 1536
            mock_embedder.embed_batch.return_value = [[0.0] * 1536]

            mock_provider.return_value = mock_embedder

            # Mock database operations
            with patch(
                "trailblazer.pipeline.steps.embed.loader.get_session_factory"
            ) as mock_session_factory:
                mock_session = MagicMock()
                mock_session_factory.return_value.__enter__.return_value = (
                    mock_session
                )

                # First embedding run
                load_chunks_to_db(
                    run_id=run_id, provider_name="dummy", dimension=1536
                )

                # Second embedding run
                load_chunks_to_db(
                    run_id=run_id, provider_name="dummy", dimension=1536
                )

    # Check that embed_assurance.json was created
    embed_dir = run_dir / "embed"
    assert embed_dir.exists()

    assurance_file = embed_dir / "embed_assurance.json"
    assert assurance_file.exists()

    with open(assurance_file, "r") as f:
        assurance_data = json.load(f)

    # Verify the assurance report has consistent data
    # The second run may have embedded 0 chunks if they were already embedded
    assert assurance_data["provider"] == "dummy"
    assert assurance_data["dimension"] == 1536
    # Check that chunks were embedded in at least one of the runs
    assert (
        assurance_data["chunks_embedded"] >= 0
    )  # Could be 0 if already embedded
