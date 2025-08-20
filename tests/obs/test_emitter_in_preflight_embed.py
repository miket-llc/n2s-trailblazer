"""Test that preflight and embed use EventEmitter consistently."""

import pytest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from trailblazer.pipeline.steps.embed.preflight import (
    run_preflight_check,
    run_plan_preflight,
)
from trailblazer.pipeline.steps.embed.loader import load_chunks_to_db


def create_test_run(temp_dir: Path, run_id: str):
    """Create a minimal test run with all required artifacts."""
    run_dir = temp_dir / "var" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Create enrich directory with enriched.jsonl
    enrich_dir = run_dir / "enrich"
    enrich_dir.mkdir()
    enriched_file = enrich_dir / "enriched.jsonl"

    doc_data = {
        "id": "test_doc",
        "title": "Test Document",
        "quality_score": 0.9,
        "text_md": "Test content",
        "source_system": "test",
    }

    with open(enriched_file, "w") as f:
        f.write(json.dumps(doc_data) + "\n")

    # Create chunk directory with chunks.ndjson
    chunk_dir = run_dir / "chunk"
    chunk_dir.mkdir()
    chunks_file = chunk_dir / "chunks.ndjson"

    chunk_data = {
        "chunk_id": "test_doc:chunk1",
        "text_md": "Test content chunk",
        "token_count": 5,
        "traceability": {"title": "Test Doc", "source_system": "test"},
    }

    with open(chunks_file, "w") as f:
        f.write(json.dumps(chunk_data) + "\n")

    return run_dir


def test_preflight_uses_event_emitter():
    """Test that run_preflight_check uses EventEmitter context manager."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        run_id = "test_preflight_events"

        create_test_run(temp_path, run_id)

        # Patch paths and EventEmitter
        with (
            patch(
                "trailblazer.core.paths.runs",
                return_value=temp_path / "var" / "runs",
            ),
            patch(
                "trailblazer.pipeline.steps.embed.preflight.EventEmitter"
            ) as mock_event_emitter,
        ):
            # Set up mock EventEmitter
            mock_emitter_instance = MagicMock()
            mock_event_emitter.return_value.__enter__ = MagicMock(
                return_value=mock_emitter_instance
            )
            mock_event_emitter.return_value.__exit__ = MagicMock(
                return_value=None
            )

            # Run preflight
            result = run_preflight_check(
                run_id=run_id,
                provider="dummy",
                model="test-model",
                dimension=1536,
            )

            # Verify EventEmitter was used as context manager
            mock_event_emitter.assert_called_once_with(
                run_id=run_id, phase="embed", component="preflight"
            )

            # Verify start event was emitted
            mock_emitter_instance.embed_start.assert_called_once_with(
                provider="dummy", model="test-model", embedding_dims=1536
            )

            # Verify completion event was emitted
            mock_emitter_instance.embed_complete.assert_called_once()

            # Verify result is valid
            assert result["status"] in ["READY", "BLOCKED"]
            assert "run_id" in result
            assert result["run_id"] == run_id


def test_plan_preflight_uses_event_emitter():
    """Test that run_plan_preflight uses EventEmitter context manager."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Create test runs
        run_ids = ["test_run_1", "test_run_2"]
        for run_id in run_ids:
            create_test_run(temp_path, run_id)

        # Create plan file
        plan_file = temp_path / "test_plan.txt"
        with open(plan_file, "w") as f:
            for run_id in run_ids:
                f.write(f"var/runs/{run_id}\n")

        # Patch paths and EventEmitter
        with (
            patch(
                "trailblazer.core.paths.runs",
                return_value=temp_path / "var" / "runs",
            ),
            patch(
                "trailblazer.pipeline.steps.embed.preflight.EventEmitter"
            ) as mock_event_emitter,
        ):
            # Set up mock EventEmitter for both preflight calls and plan-preflight
            mock_emitter_instance = MagicMock()
            mock_event_emitter.return_value.__enter__ = MagicMock(
                return_value=mock_emitter_instance
            )
            mock_event_emitter.return_value.__exit__ = MagicMock(
                return_value=None
            )

            # Run plan preflight
            result = run_plan_preflight(
                plan_file=str(plan_file),
                out_dir=str(temp_path / "var" / "plan_preflight"),
                provider="dummy",
                model="test-model",
                dimension=1536,
            )

            # Verify EventEmitter was used for plan-preflight
            # Should be called once for plan-preflight + once for each run preflight
            assert mock_event_emitter.call_count >= 1

            # Check that plan-preflight EventEmitter was called
            plan_preflight_call = None
            for call in mock_event_emitter.call_args_list:
                if call[1]["run_id"] == "plan_preflight":
                    plan_preflight_call = call
                    break

            assert plan_preflight_call is not None, (
                "EventEmitter should be called for plan-preflight"
            )
            assert plan_preflight_call[1]["phase"] == "embed"
            assert plan_preflight_call[1]["component"] == "plan_preflight"

            # Verify result is valid
            assert "ready_runs" in result
            assert "blocked_runs" in result
            assert "total_runs_planned" in result


def test_embed_loader_uses_event_emitter():
    """Test that embed loader uses EventEmitter context manager."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        run_id = "test_embed_events"

        create_test_run(temp_path, run_id)

        # Mock dependencies
        mock_session_factory = MagicMock()
        mock_session = MagicMock()
        mock_session_factory.return_value.__enter__ = MagicMock(
            return_value=mock_session
        )
        mock_session_factory.return_value.__exit__ = MagicMock(
            return_value=None
        )

        mock_embedder = MagicMock()
        mock_embedder.provider_name = "dummy"
        mock_embedder.dim = 1536
        mock_embedder.embed_texts.return_value = [[0.1] * 1536]

        # Patch dependencies including EventEmitter
        with (
            patch(
                "trailblazer.core.paths.runs",
                return_value=temp_path / "var" / "runs",
            ),
            patch(
                "trailblazer.pipeline.steps.embed.loader.get_session_factory",
                return_value=mock_session_factory,
            ),
            patch(
                "trailblazer.pipeline.steps.embed.loader.get_embedding_provider",
                return_value=mock_embedder,
            ),
            patch("trailblazer.core.progress.get_progress") as mock_progress,
            patch("trailblazer.obs.events.EventEmitter") as mock_event_emitter,
        ):
            # Set up mocks
            mock_progress.return_value.enabled = False
            mock_emitter_instance = MagicMock()
            mock_event_emitter.return_value.__enter__ = MagicMock(
                return_value=mock_emitter_instance
            )
            mock_event_emitter.return_value.__exit__ = MagicMock(
                return_value=None
            )

            # Run embed loader
            result = load_chunks_to_db(
                run_id=run_id,
                provider_name="dummy",
                dimension=1536,
                batch_size=10,
            )

            # Verify EventEmitter was used as context manager
            mock_event_emitter.assert_called_once_with(
                run_id=run_id, phase="embed", component="loader"
            )

            # Verify start event was emitted
            mock_emitter_instance.embed_start.assert_called_once()

            # Verify result is valid
            assert "chunks_embedded" in result
            assert "chunks_skipped" in result


def test_event_emitter_consistent_fields():
    """Test that EventEmitter uses consistent field names across preflight and embed."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        run_id = "test_consistent_fields"

        create_test_run(temp_path, run_id)

        # Track all emitted events
        emitted_events = []

        def mock_emit(event_type, **kwargs):
            emitted_events.append({"type": event_type, "kwargs": kwargs})

        # Patch paths and capture events
        with (
            patch(
                "trailblazer.core.paths.runs",
                return_value=temp_path / "var" / "runs",
            ),
            patch(
                "trailblazer.pipeline.steps.embed.preflight.EventEmitter"
            ) as mock_event_emitter,
        ):
            # Set up mock to capture events
            mock_emitter_instance = MagicMock()
            mock_event_emitter.return_value.__enter__ = MagicMock(
                return_value=mock_emitter_instance
            )
            mock_event_emitter.return_value.__exit__ = MagicMock(
                return_value=None
            )

            # Run preflight
            result = run_preflight_check(
                run_id=run_id,
                provider="openai",
                model="text-embedding-3-small",
                dimension=1536,
            )

            # Verify start event has consistent parameters
            start_call = mock_emitter_instance.embed_start.call_args
            assert start_call is not None

            start_kwargs = (
                start_call[1]
                if start_call[1]
                else start_call[0][0]
                if start_call[0]
                else {}
            )

            # Should have standard embedding parameters
            expected_fields = ["provider", "model", "embedding_dims"]
            for field in expected_fields:
                assert field in start_kwargs or any(
                    field in str(arg) for arg in start_call[0]
                ), f"Missing expected field '{field}' in embed_start call"

            # Verify completion event has consistent parameters
            complete_call = mock_emitter_instance.embed_complete.call_args
            assert complete_call is not None

            # Should have counts and timing information
            if complete_call[1]:
                complete_kwargs = complete_call[1]
                assert (
                    "total_embedded" in complete_kwargs
                    or "counts" in complete_kwargs
                )

            assert result["status"] in ["READY", "BLOCKED"]


@patch("trailblazer.pipeline.steps.embed.preflight.validate_tokenizer_config")
def test_event_emitter_error_handling(mock_tokenizer):
    """Test that EventEmitter properly handles errors in preflight."""
    # Mock tokenizer to fail
    mock_tokenizer.side_effect = Exception("Tokenizer validation failed")

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        run_id = "test_error_handling"

        create_test_run(temp_path, run_id)

        # Patch paths and EventEmitter
        with (
            patch(
                "trailblazer.core.paths.runs",
                return_value=temp_path / "var" / "runs",
            ),
            patch(
                "trailblazer.pipeline.steps.embed.preflight.EventEmitter"
            ) as mock_event_emitter,
        ):
            mock_emitter_instance = MagicMock()
            mock_event_emitter.return_value.__enter__ = MagicMock(
                return_value=mock_emitter_instance
            )
            mock_event_emitter.return_value.__exit__ = MagicMock(
                return_value=None
            )

            # Should handle error gracefully (tokenizer validation is caught)
            with pytest.raises(Exception):
                run_preflight_check(
                    run_id=run_id,
                    provider="openai",
                    model="text-embedding-3-small",
                    dimension=1536,
                )

            # EventEmitter should still be called even if there's an error
            mock_event_emitter.assert_called_once()
            mock_emitter_instance.embed_start.assert_called_once()
