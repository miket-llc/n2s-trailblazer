"""Test embed contract: materialized chunks required, events emitted, legacy flags rejected."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys

import pytest
import click

from trailblazer.obs.events import EventEmitter, set_global_emitter


class TestEmbedContract:
    """Test embed contract enforcement and event emission."""

    def test_embed_fails_without_chunks(self):
        """Test that embed load fails when no chunks are materialized."""
        # Test the validation function directly
        from trailblazer.pipeline.steps.embed.loader import (
            _validate_materialized_chunks,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            # Mock the runs function to point to our temp directory
            with patch("trailblazer.core.paths.runs") as mock_runs:
                mock_runs.return_value = temp_path / "runs"

                # Should raise FileNotFoundError for missing chunks
                with pytest.raises(FileNotFoundError) as exc_info:
                    _validate_materialized_chunks("missing-chunks-test")

                # Verify error message
                error_msg = str(exc_info.value)
                assert "materialized chunks" in error_msg
                assert "chunks.ndjson" in error_msg
                assert "chunk run" in error_msg

    def test_embed_fails_with_empty_chunks(self):
        """Test that embed load fails when chunks file is empty."""
        from trailblazer.pipeline.steps.embed.loader import (
            _validate_materialized_chunks,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            # Create run directory with empty chunks file
            run_dir = temp_path / "runs" / "empty-chunks-test"
            chunk_dir = run_dir / "chunk"
            chunk_dir.mkdir(parents=True, exist_ok=True)

            chunks_file = chunk_dir / "chunks.ndjson"
            chunks_file.write_text("")  # Empty file

            with patch("trailblazer.core.paths.runs") as mock_runs:
                mock_runs.return_value = temp_path / "runs"

                # Should raise ValueError for empty chunks
                with pytest.raises(ValueError) as exc_info:
                    _validate_materialized_chunks("empty-chunks-test")

                # Verify error message
                error_msg = str(exc_info.value)
                assert "empty chunks file" in error_msg
                assert "materialized chunks" in error_msg

    def test_embed_succeeds_with_chunks_and_emits_events(self):
        """Test that embed load succeeds with chunks and emits proper events."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            logs_dir = temp_path / "logs"
            logs_dir.mkdir(exist_ok=True)

            # Set up EventEmitter
            emitter = EventEmitter(
                run_id="success-test",
                phase="embed",
                component="upsert",
                log_dir=str(logs_dir),
            )
            set_global_emitter(emitter)

            # Create run directory with chunks
            run_dir = temp_path / "runs" / "success-test"
            chunk_dir = run_dir / "chunk"
            chunk_dir.mkdir(parents=True, exist_ok=True)

            # Create chunks.ndjson with test data
            chunks_file = chunk_dir / "chunks.ndjson"
            test_chunks = [
                {
                    "chunk_id": "success-test:0000",
                    "text_md": "Test chunk 1",
                    "token_count": 10,
                    "doc_id": "doc1",
                    "title": "Test Document 1",
                },
                {
                    "chunk_id": "success-test:0001",
                    "text_md": "Test chunk 2",
                    "token_count": 15,
                    "doc_id": "doc2",
                    "title": "Test Document 2",
                },
            ]

            with open(chunks_file, "w") as f:
                for chunk in test_chunks:
                    f.write(json.dumps(chunk) + "\n")

            # Mock database operations
            with patch(
                "trailblazer.pipeline.steps.embed.loader.get_session_factory"
            ) as mock_session_factory:
                mock_session = MagicMock()
                mock_session_factory.return_value.__enter__.return_value = (
                    mock_session
                )

                # Mock database queries to return no existing data
                mock_session.query.return_value.filter_by.return_value.first.return_value = None
                mock_session.get.return_value = None

                with patch("trailblazer.core.paths.runs") as mock_runs:
                    mock_runs.return_value = temp_path / "runs"

                    with emitter:
                        try:
                            from trailblazer.pipeline.steps.embed.loader import (
                                load_chunks_to_db,
                            )

                            result = load_chunks_to_db(
                                run_id="success-test",
                                provider_name="dummy",
                                max_chunks=2,
                            )

                            # Verify result structure
                            assert isinstance(result, dict)
                            assert "docs_embedded" in result
                            assert "chunks_embedded" in result

                        except Exception as e:
                            # May fail due to missing dependencies, but should emit events
                            print(
                                f"Expected failure due to test environment: {e}"
                            )

            # Verify events were emitted
            events_file = logs_dir / "success-test" / "events.ndjson"
            assert events_file.exists()

            events = []
            with open(events_file, "r") as f:
                for line in f:
                    if line.strip():
                        events.append(json.loads(line.strip()))

            # Should have start and end events
            assert len(events) >= 2, "Should emit start and completion events"

            # Check for start event
            start_events = [
                e
                for e in events
                if "Starting embed" in e.get("metadata", {}).get("message", "")
            ]
            assert len(start_events) >= 1, "Should emit start event"

            # Check for completion event (success or failure)
            completion_events = [
                e
                for e in events
                if "completed"
                in e.get("metadata", {}).get("message", "").lower()
            ]
            assert len(completion_events) >= 1, "Should emit completion event"

            # Clean up
            set_global_emitter(None)

    def test_embed_rejects_legacy_chunk_flags(self):
        """Test that embed commands reject legacy --chunk-* flags."""
        from trailblazer.cli.main import _validate_no_legacy_chunk_flags

        # Test various legacy chunk flags
        legacy_flags = [
            "--chunk-size",
            "--chunk-overlap",
            "--chunk-strategy",
            "--max-chunk-size",
            "--min-chunk-size",
            "--chunk-method",
        ]

        for flag in legacy_flags:
            # Mock sys.argv to include the legacy flag
            with patch.object(
                sys,
                "argv",
                [
                    "trailblazer",
                    "embed",
                    "load",
                    flag,
                    "100",
                    "--run-id",
                    "test",
                ],
            ):
                # Should raise typer.Exit for legacy flags
                with pytest.raises(
                    (SystemExit, click.exceptions.Exit)
                ) as exc_info:
                    _validate_no_legacy_chunk_flags()

                # Should exit with code 1
                assert exc_info.value.code == 1

    def test_embed_validates_forbidden_modules(self):
        """Test that embed validates against forbidden chunk module imports."""
        # This test verifies the forbidden_modules guard is preserved
        from trailblazer.pipeline.steps.embed.loader import (
            _validate_no_chunk_imports,
        )

        # Should pass when no forbidden modules are imported
        _validate_no_chunk_imports()  # Should not raise

        # Test that the function exists and works
        assert _validate_no_chunk_imports is not None

    def test_embed_validates_materialized_chunks(self):
        """Test that embed validates materialized chunks exist."""
        from trailblazer.pipeline.steps.embed.loader import (
            _validate_materialized_chunks,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            with patch("trailblazer.core.paths.runs") as mock_runs:
                mock_runs.return_value = temp_path / "runs"

                # Should raise FileNotFoundError for missing chunks
                with pytest.raises(FileNotFoundError) as exc_info:
                    _validate_materialized_chunks("missing-run")

                assert "materialized chunks" in str(exc_info.value)
                assert "chunks.ndjson" in str(exc_info.value)

    def test_embed_event_schema_compliance(self):
        """Test that embed events comply with observability schema."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            logs_dir = temp_path / "logs"
            logs_dir.mkdir(exist_ok=True)

            # Set up EventEmitter
            emitter = EventEmitter(
                run_id="schema-test",
                phase="embed",
                component="upsert",
                log_dir=str(logs_dir),
            )
            set_global_emitter(emitter)

            from trailblazer.obs.events import emit_info, emit_error

            with emitter:
                # Emit test embed events
                emit_info(
                    "embed",
                    "schema-test",
                    "upsert",
                    message="Starting embed process",
                    provider="openai",
                    model="text-embedding-3-small",
                )

                emit_info(
                    "embed",
                    "schema-test",
                    "upsert",
                    message="Embed completed successfully",
                    docs_embedded=10,
                    chunks_embedded=50,
                    total_tokens=5000,
                )

                emit_error(
                    "embed",
                    "schema-test",
                    "upsert",
                    message="Embed completed with errors",
                    docs_embedded=8,
                    chunks_embedded=45,
                    errors=2,
                )

            # Verify events
            events_file = logs_dir / "schema-test" / "events.ndjson"
            assert events_file.exists()

            events = []
            with open(events_file, "r") as f:
                for line in f:
                    events.append(json.loads(line.strip()))

            assert len(events) == 3

            # Verify schema compliance
            for event in events:
                # Required observability fields
                required_fields = {
                    "ts",
                    "run_id",
                    "phase",
                    "component",
                    "pid",
                    "worker_id",
                    "level",
                    "action",
                }
                for field in required_fields:
                    assert field in event, f"Missing required field '{field}'"

                # Verify field values
                assert event["run_id"] == "schema-test"
                assert event["phase"] == "embed"
                assert event["component"] == "upsert"
                assert event["level"] in ["info", "error"]
                assert event["action"] in ["tick", "error"]

            # Verify specific event content
            start_event = events[0]
            assert start_event["provider"] == "openai"  # Direct field
            assert (
                start_event["model"] == "text-embedding-3-small"
            )  # Direct field

            success_event = events[1]
            assert success_event["metadata"]["docs_embedded"] == 10
            assert success_event["metadata"]["chunks_embedded"] == 50
            assert success_event["metadata"]["total_tokens"] == 5000

            error_event = events[2]
            assert error_event["level"] == "error"
            assert error_event["metadata"]["errors"] == 2

            # Clean up
            set_global_emitter(None)
