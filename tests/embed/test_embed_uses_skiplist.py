"""Test that embed loader honors doc_skiplist.json."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from trailblazer.pipeline.steps.embed.loader import load_chunks_to_db


@pytest.fixture
def mock_run_with_skiplist():
    """Create a mock run with doc_skiplist.json."""
    with tempfile.TemporaryDirectory() as temp_dir:
        run_dir = Path(temp_dir) / "test_run"
        run_dir.mkdir()

        # Create chunk directory
        chunk_dir = run_dir / "chunk"
        chunk_dir.mkdir()

        # Create chunks.ndjson with 5 docs
        chunks_file = chunk_dir / "chunks.ndjson"
        with open(chunks_file, "w") as f:
            for i in range(5):
                chunk = {
                    "chunk_id": f"doc_{i}:0000",
                    "doc_id": f"doc_{i}",
                    "text_md": f"Content for doc {i}",
                    "token_count": 100,
                    "title": f"Doc {i}",
                    "url": f"http://example.com/doc_{i}",
                    "source_system": "confluence",
                }
                f.write(json.dumps(chunk) + "\n")

        # Create preflight directory with skiplist
        preflight_dir = run_dir / "preflight"
        preflight_dir.mkdir()

        # Skip docs 1 and 3 (2 out of 5 = 40%)
        skiplist = {
            "skip": ["doc_1", "doc_3"],
            "reason": "quality_below_min",
            "min_quality": 0.60,
            "total_docs": 5,
            "skipped_count": 2,
        }

        skiplist_file = preflight_dir / "doc_skiplist.json"
        with open(skiplist_file, "w") as f:
            json.dump(skiplist, f, indent=2)

        yield run_dir.name


@patch("trailblazer.pipeline.steps.embed.loader.get_session_factory")
@patch("trailblazer.pipeline.steps.embed.loader.get_embedding_provider")
def test_embed_honors_skiplist(
    mock_provider, mock_session_factory, mock_run_with_skiplist
):
    """Test that embed loader skips documents in doc_skiplist.json."""
    # Mock the embedding provider
    mock_embedder = MagicMock()
    mock_embedder.provider_name = "dummy"
    mock_embedder.dimension = 384
    mock_embedder.embed_batch.return_value = [
        [0.1] * 384
    ] * 3  # 3 embeddings for non-skipped docs
    mock_provider.return_value = mock_embedder

    # Mock database session
    mock_session = MagicMock()
    mock_session_factory.return_value = mock_session

    with patch("trailblazer.pipeline.steps.embed.loader.runs") as mock_runs:
        mock_runs.return_value = Path(mock_run_with_skiplist).parent

        # Mock the database upsert functions
        with patch(
            "trailblazer.pipeline.steps.embed.loader.upsert_document"
        ) as mock_upsert_doc:
            with patch(
                "trailblazer.pipeline.steps.embed.loader.upsert_chunk"
            ) as mock_upsert_chunk:
                with patch(
                    "trailblazer.pipeline.steps.embed.loader.upsert_chunk_embedding"
                ) as mock_upsert_embed:
                    result = load_chunks_to_db(
                        run_id=mock_run_with_skiplist, provider_name="dummy"
                    )

                    # Should have processed 3 docs (skipped 2)
                    assert result["docs_embedded"] == 3
                    assert result["docs_skipped"] == 2
                    assert result["chunks_embedded"] == 3
                    assert result["chunks_skipped"] == 2

                    # Verify the right docs were processed
                    embedded_doc_ids = set()
                    for call in mock_upsert_doc.call_args_list:
                        # Extract doc_id from the call
                        doc_data = call[1]  # kwargs
                        embedded_doc_ids.add(doc_data.get("id", ""))

                    # Should have embedded docs 0, 2, 4 (skipped 1, 3)
                    expected_embedded = {"doc_0", "doc_2", "doc_4"}
                    assert embedded_doc_ids == expected_embedded
