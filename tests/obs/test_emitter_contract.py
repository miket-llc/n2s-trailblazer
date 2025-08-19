"""Test that EventEmitter contract ensures events land in var/logs/<RID>/events.ndjson."""

import json
import os
import tempfile
from pathlib import Path
from trailblazer.obs.events import (
    EventEmitter,
    EventAction,
    emit_info,
    emit_warn,
    emit_error,
    stage_run,
    set_global_emitter,
)


class TestEmitterContract:
    """Test EventEmitter contract for standardized event output."""

    def test_events_land_in_correct_path(self):
        """Test that events are written to var/logs/<RID>/events.ndjson."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir)
            run_id = "test-run-12345"

            # Create emitter
            emitter = EventEmitter(
                run_id=run_id,
                phase="test",
                component="emitter",
                log_dir=str(log_dir),
            )

            # Expected paths
            expected_events_path = log_dir / run_id / "events.ndjson"
            expected_stderr_path = log_dir / run_id / "stderr.log"

            with emitter:
                emitter.ingest_start(space_key="TEST")
                emitter.ingest_complete(total_processed=42, duration_ms=1000)

            # Verify directory structure
            assert expected_events_path.exists()
            assert expected_stderr_path.exists()

            # Verify symlinks
            run_symlink = log_dir / f"{run_id}.ndjson"
            latest_ndjson = log_dir / "latest.ndjson"
            latest_stderr = log_dir / "latest.stderr.log"

            assert run_symlink.is_symlink()
            assert latest_ndjson.is_symlink()
            assert latest_stderr.is_symlink()

    def test_event_schema_contract(self):
        """Test that events contain required fields with correct types."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir)
            run_id = "test-run-schema"

            emitter = EventEmitter(
                run_id=run_id,
                phase="ingest",
                component="confluence",
                log_dir=str(log_dir),
            )

            events_path = log_dir / run_id / "events.ndjson"

            with emitter:
                emitter.ingest_start(space_key="DEV", sourcefile="test.json")
                emitter.warning("Test warning message")
                emitter.error("Test error message", error_type="TestError")
                emitter.ingest_complete(total_processed=10, duration_ms=500)

            # Read and verify events
            events = []
            with open(events_path, "r") as f:
                for line in f:
                    events.append(json.loads(line.strip()))

            assert len(events) == 4

            # Verify required fields in all events
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

            for event in events:
                # Check required fields exist
                for field in required_fields:
                    assert field in event, (
                        f"Missing required field '{field}' in event: {event}"
                    )

                # Check field types and values
                assert event["ts"].endswith("Z"), "Timestamp should end with Z"
                assert event["run_id"] == run_id
                assert event["phase"] == "ingest"
                assert event["component"] == "confluence"
                assert isinstance(event["pid"], int)
                assert event["worker_id"] == f"confluence-{os.getpid()}"
                assert event["level"] in ["info", "warning", "error"]
                assert event["action"] in [
                    "start",
                    "complete",
                    "warning",
                    "error",
                ]

            # Verify specific event content
            start_event = events[0]
            assert start_event["action"] == "start"
            assert start_event["space_key"] == "DEV"
            assert start_event["sourcefile"] == "test.json"

            warning_event = events[1]
            assert warning_event["level"] == "warning"
            assert warning_event["action"] == "warning"
            assert "Test warning message" in str(warning_event["metadata"])

            error_event = events[2]
            assert error_event["level"] == "error"
            assert error_event["action"] == "error"
            assert "Test error message" in str(error_event["metadata"])

            complete_event = events[3]
            assert complete_event["action"] == "complete"
            assert complete_event["duration_ms"] == 500
            assert complete_event["metadata"]["total_processed"] == 10

    def test_thin_adapter_functions(self):
        """Test that thin adapter functions emit correct events."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir)
            run_id = "test-adapter-functions"

            # Test without global emitter (creates temporary)
            emit_info("test", run_id, "operation", message="info test")
            emit_warn("test", run_id, "operation", message="warn test")
            emit_error("test", run_id, "operation", message="error test")

            # Test with global emitter
            emitter = EventEmitter(
                run_id=run_id,
                phase="test",
                component="adapter",
                log_dir=str(log_dir),
            )

            set_global_emitter(emitter)
            events_path = log_dir / run_id / "events.ndjson"

            with emitter:
                emit_info("test", run_id, "operation", message="global info")
                emit_warn("test", run_id, "operation", message="global warn")
                emit_error("test", run_id, "operation", message="global error")

            # Verify events were written
            assert events_path.exists()

            events = []
            with open(events_path, "r") as f:
                for line in f:
                    events.append(json.loads(line.strip()))

            assert len(events) == 3

            # Verify event levels
            assert events[0]["level"] == "info"
            assert events[1]["level"] == "warning"
            assert events[2]["level"] == "error"

            # Clean up global emitter
            set_global_emitter(None)

    def test_stage_run_context_manager(self):
        """Test that stage_run context manager emits START/END with duration."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir)
            run_id = "test-stage-run"

            emitter = EventEmitter(
                run_id=run_id,
                phase="test",
                component="stage",
                log_dir=str(log_dir),
            )

            set_global_emitter(emitter)
            events_path = log_dir / run_id / "events.ndjson"

            with emitter:
                with stage_run(
                    "ingest", run_id, "confluence", space_key="DEV"
                ) as ctx:
                    # Simulate some work
                    ctx.update(pages_processed=5)

            # Verify events
            events = []
            with open(events_path, "r") as f:
                for line in f:
                    events.append(json.loads(line.strip()))

            assert len(events) == 2

            start_event = events[0]
            end_event = events[1]

            # Verify START event
            assert start_event["action"] == "start"
            assert start_event["space_key"] == "DEV"
            assert "duration_ms" not in start_event

            # Verify END event
            assert end_event["action"] == "complete"
            assert "duration_ms" in end_event
            assert isinstance(end_event["duration_ms"], int)
            assert end_event["duration_ms"] >= 0
            assert end_event["metadata"]["status"] == "complete"
            assert end_event["metadata"]["pages_processed"] == 5

            # Clean up
            set_global_emitter(None)

    def test_event_fields_mapping(self):
        """Test that events contain expected field mappings."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir)
            run_id = "test-field-mapping"

            emitter = EventEmitter(
                run_id=run_id,
                phase="embed",
                component="openai",
                log_dir=str(log_dir),
            )

            events_path = log_dir / run_id / "events.ndjson"

            with emitter:
                # Test various field types
                emitter.embed_start(
                    provider="openai",
                    model="text-embedding-3-small",
                    embedding_dims=1536,
                    space_key="TEST",
                    chunk_id="chunk-123",
                )

            # Verify event contains expected fields
            with open(events_path, "r") as f:
                event = json.loads(f.readline().strip())

            # Direct fields
            assert event["provider"] == "openai"
            assert event["model"] == "text-embedding-3-small"
            assert event["embedding_dims"] == 1536
            assert event["space_key"] == "TEST"
            assert event["chunk_id"] == "chunk-123"

            # Standard fields
            assert event["ts"]
            assert event["run_id"] == run_id
            assert event["phase"] == "embed"
            assert event["component"] == "openai"
            assert event["pid"] == os.getpid()
            assert event["worker_id"] == f"openai-{os.getpid()}"
            assert event["level"] == "info"
            assert event["action"] == "start"

    def test_metadata_field_handling(self):
        """Test that metadata fields are properly handled."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir)
            run_id = "test-metadata"

            emitter = EventEmitter(
                run_id=run_id,
                phase="test",
                component="metadata",
                log_dir=str(log_dir),
            )

            events_path = log_dir / run_id / "events.ndjson"

            with emitter:
                # Test with explicit metadata and extra fields
                emitter._emit(
                    EventAction.TICK,
                    space_key="TEST",  # Direct field
                    metadata={"explicit": "meta"},  # Explicit metadata
                    extra_field="extra",  # Should go to metadata
                    custom_count=42,  # Should go to metadata
                )

            with open(events_path, "r") as f:
                event = json.loads(f.readline().strip())

            # Direct field should be at top level
            assert event["space_key"] == "TEST"

            # Metadata should contain both explicit and extra fields
            assert event["metadata"]["explicit"] == "meta"
            assert event["metadata"]["extra_field"] == "extra"
            assert event["metadata"]["custom_count"] == 42
