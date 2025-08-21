"""Test that embed loader validates dimension=1536 before upsert."""

import tempfile
import os
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
import json

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


def create_test_run(temp_dir: Path, run_id: str):
    """Create a minimal test run with chunks."""
    run_dir = temp_dir / "var" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    chunk_dir = run_dir / "chunk"
    chunk_dir.mkdir()
    chunks_file = chunk_dir / "chunks.ndjson"

    chunk_data = {
        "chunk_id": "doc1:chunk1",
        "text_md": "Test content",
        "token_count": 5,
        "traceability": {"title": "Test Doc", "source_system": "test"},
    }

    with open(chunks_file, "w") as f:
        f.write(json.dumps(chunk_data) + "\n")

    return chunks_file


def test_dimension_guard_rejects_wrong_dimension(mock_session_factory):
    """Test that loader rejects embedder with wrong dimension."""
    mock_factory, mock_session = mock_session_factory

    # Mock embedder with wrong dimension
    mock_embedder = MagicMock()
    mock_embedder.provider_name = "openai"  # Use valid provider name
    mock_embedder.dim = 768  # Wrong dimension (should be 1536)
    mock_embedder.dimension = (
        768  # Also set dimension property for loader compatibility
    )
    mock_embedder.model = "test-model"

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        run_id = "test_wrong_dimension"

        create_test_run(temp_path, run_id)

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
                "trailblazer.pipeline.steps.embed.provider.OpenAIEmbedder",
                return_value=mock_embedder,
            ),
        ):
            # Should raise ValueError with clear message
            with pytest.raises(ValueError) as exc_info:
                load_chunks_to_db(
                    run_id=run_id,
                    provider_name="openai",
                    dimension=768,  # Wrong dimension
                )

            error_message = str(exc_info.value)
            assert "Dimension mismatch" in error_message
            assert "expected 1536, got 768" in error_message
            assert "Use --dimension 1536 (singular)" in error_message
            assert "openai" in error_message
            assert "test-model" in error_message


def test_dimension_guard_accepts_correct_dimension(mock_session_factory):
    """Test that loader accepts embedder with correct dimension."""
    mock_factory, mock_session = mock_session_factory

    # Mock embedder with correct dimension
    mock_embedder = MagicMock()
    mock_embedder.provider_name = "openai"
    mock_embedder.dim = 1536  # Correct dimension
    mock_embedder.dimension = (
        1536  # Also set dimension property for loader compatibility
    )
    mock_embedder.model = "text-embedding-3-small"
    mock_embedder.embed.return_value = [
        0.1
    ] * 1536  # Current API uses embed() for single texts

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        run_id = "test_correct_dimension"

        create_test_run(temp_path, run_id)

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
                "trailblazer.pipeline.steps.embed.provider.OpenAIEmbedder",
                return_value=mock_embedder,
            ),
            patch("trailblazer.core.progress.get_progress") as mock_progress,
            patch("trailblazer.obs.events.EventEmitter") as mock_event_emitter,
            patch.dict(os.environ, {"OPENAI_API_KEY": "test-key-123"}),
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

            # Should not raise exception
            result = load_chunks_to_db(
                run_id=run_id, provider_name="openai", dimension=1536
            )

            # Should successfully process
            assert "chunks_embedded" in result


def test_dimension_guard_fallback_to_test_embedding(mock_session_factory):
    """Test dimension detection via test embedding when dim attribute missing."""
    mock_factory, mock_session = mock_session_factory

    # Mock embedder without dim attribute
    mock_embedder = MagicMock()
    mock_embedder.provider_name = "openai"  # Use valid provider name
    # No dim or dimension attribute
    del mock_embedder.dim
    del mock_embedder.dimension

    # But test embedding returns correct dimension
    mock_embedder.embed.return_value = [
        0.1
    ] * 1536  # Current API uses embed() for single texts

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        run_id = "test_fallback_detection"

        create_test_run(temp_path, run_id)

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
                "trailblazer.pipeline.steps.embed.provider.OpenAIEmbedder",
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

            # Should not raise exception (dimension detected via test embedding)
            result = load_chunks_to_db(run_id=run_id, provider_name="openai")

            # Should successfully process
            assert "chunks_embedded" in result

            # Verify test embedding was called for dimension detection
            embed_calls = mock_embedder.embed.call_args_list
            # Should have at least one call (for dimension detection)
            assert len(embed_calls) >= 1


def test_dimension_guard_fallback_wrong_dimension(mock_session_factory):
    """Test dimension detection via test embedding detects wrong dimension."""
    mock_factory, mock_session = mock_session_factory

    # Mock embedder without dim attribute but wrong test embedding dimension
    mock_embedder = MagicMock()
    mock_embedder.provider_name = "openai"  # Use valid provider name
    del mock_embedder.dim
    del mock_embedder.dimension

    # Test embedding returns wrong dimension
    mock_embedder.embed.return_value = [0.1] * 384  # Wrong dimension

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        run_id = "test_fallback_wrong"

        create_test_run(temp_path, run_id)

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
                "trailblazer.pipeline.steps.embed.provider.OpenAIEmbedder",
                return_value=mock_embedder,
            ),
        ):
            # Should raise ValueError after detecting wrong dimension
            with pytest.raises(ValueError) as exc_info:
                load_chunks_to_db(run_id=run_id, provider_name="openai")

            error_message = str(exc_info.value)
            assert "Dimension mismatch" in error_message
            assert "expected 1536, got 384" in error_message


def test_dimension_guard_test_embedding_fails_gracefully(mock_session_factory):
    """Test that dimension guard continues when test embedding fails."""
    mock_factory, mock_session = mock_session_factory

    # Mock embedder without dim attribute and failing test embedding
    mock_embedder = MagicMock()
    mock_embedder.provider_name = "openai"  # Use valid provider name
    del mock_embedder.dim
    del mock_embedder.dimension

    # Test embedding raises exception
    mock_embedder.embed.side_effect = Exception("Test embedding failed")

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        run_id = "test_fallback_fails"

        create_test_run(temp_path, run_id)

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
                "trailblazer.pipeline.steps.embed.provider.OpenAIEmbedder",
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

            # Should not raise exception (dimension detection failed, but continues)
            # This is acceptable since we can't determine the dimension
            result = load_chunks_to_db(run_id=run_id, provider_name="openai")

            # Should process (dimension validation was skipped due to detection failure)
            assert "chunks_embedded" in result


def test_dimension_guard_uses_dimension_attribute_over_dim(
    mock_session_factory,
):
    """Test that dimension guard prefers 'dimension' attribute over 'dim'."""
    mock_factory, mock_session = mock_session_factory

    # Mock embedder with both dim and dimension attributes (different values)
    mock_embedder = MagicMock()
    mock_embedder.provider_name = "openai"  # Use valid provider name
    mock_embedder.dim = 768  # Wrong
    mock_embedder.dimension = 1536  # Correct (should be preferred)
    mock_embedder.embed.return_value = [
        0.1
    ] * 1536  # Current API uses embed() for single texts

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        run_id = "test_dimension_priority"

        create_test_run(temp_path, run_id)

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
                "trailblazer.pipeline.steps.embed.provider.OpenAIEmbedder",
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

            # Should not raise exception (dimension=1536 is correct)
            result = load_chunks_to_db(run_id=run_id, provider_name="openai")

            # Should successfully process
            assert "chunks_embedded" in result


def test_dimension_guard_explicit_dimension_override():
    """Test dimension validation with explicit dimension parameter."""
    # Mock embedder that would be created with custom dimension
    mock_embedder = MagicMock()
    mock_embedder.provider_name = "openai"
    mock_embedder.dim = 512  # Wrong dimension
    mock_embedder.dimension = (
        512  # Also set dimension property for consistency
    )
    mock_embedder.model = "custom-model"

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        run_id = "test_explicit_dimension"

        create_test_run(temp_path, run_id)

        # Patch to create embedder with wrong dimension
        with (
            patch(
                "trailblazer.core.paths.runs",
                return_value=temp_path / "var" / "runs",
            ),
            patch(
                "trailblazer.pipeline.steps.embed.provider.OpenAIEmbedder",
                return_value=mock_embedder,
            ),
        ):
            # Should raise ValueError when creating embedder with wrong dimension
            with pytest.raises(ValueError) as exc_info:
                load_chunks_to_db(
                    run_id=run_id,
                    provider_name="openai",
                    model="custom-model",
                    dimension=512,  # Explicitly wrong dimension
                )

            error_message = str(exc_info.value)
            assert "expected 1536, got 512" in error_message
