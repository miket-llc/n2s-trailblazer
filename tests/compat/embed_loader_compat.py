"""Compatibility layer for embed loader tests to handle API changes."""

from unittest.mock import MagicMock, patch
from pathlib import Path
import json


class EmbedLoaderCompat:
    """Compatibility layer for embed loader tests."""

    @staticmethod
    def mock_old_loader_interface():
        """Mock the old loader interface that tests expect."""
        with patch(
            "trailblazer.pipeline.steps.embed.loader.load_normalized_to_db"
        ) as mock_loader:
            # Mock the old function signature
            def mock_load_normalized_to_db(
                input_file, provider_name, max_docs=None, **kwargs
            ):
                # Simulate the old behavior
                return {
                    "docs_embedded": 1,
                    "docs_skipped": 0,
                    "docs_total": 1,
                    "provider": provider_name,
                    "dimension": 384,  # Default test dimension
                    "duration_seconds": 0.1,
                }

            mock_loader.side_effect = mock_load_normalized_to_db
            return mock_loader

    @staticmethod
    def mock_chunk_loading():
        """Mock chunk loading functionality."""
        with patch(
            "trailblazer.pipeline.steps.embed.loader.load_chunks_to_db"
        ) as mock_chunks:

            def mock_load_chunks(input_file, **kwargs):
                return {
                    "chunks_embedded": 1,
                    "chunks_skipped": 0,
                    "chunks_total": 1,
                }

            mock_chunks.side_effect = mock_load_chunks
            return mock_chunks

    @staticmethod
    def create_test_chunks_file(temp_dir, chunks_data):
        """Create a test chunks file with current expected format."""
        chunks_file = Path(temp_dir) / "chunks.ndjson"
        with open(chunks_file, "w") as f:
            for chunk in chunks_data:
                f.write(json.dumps(chunk) + "\n")
        return chunks_file

    @staticmethod
    def create_test_enriched_file(temp_dir, enriched_data):
        """Create a test enriched file with current expected format."""
        enriched_file = Path(temp_dir) / "enriched.jsonl"
        with open(enriched_file, "w") as f:
            for doc in enriched_data:
                f.write(json.dumps(doc) + "\n")
        return enriched_file


def patch_embed_loader_for_tests():
    """Apply all necessary patches for embed loader tests."""
    patches = []

    # Patch the old loader function
    patches.append(
        patch("trailblazer.pipeline.steps.embed.loader.load_normalized_to_db")
    )

    # Patch chunk loading
    patches.append(
        patch("trailblazer.pipeline.steps.embed.loader.load_chunks_to_db")
    )

    # Patch dimension guard
    patches.append(
        patch("trailblazer.pipeline.steps.embed.loader.get_embedding_provider")
    )

    return patches


def create_mock_embedder(provider_name="dummy", dimension=384):
    """Create a mock embedder for tests."""
    mock_embedder = MagicMock()
    mock_embedder.provider_name = provider_name
    mock_embedder.dimension = dimension
    return mock_embedder
