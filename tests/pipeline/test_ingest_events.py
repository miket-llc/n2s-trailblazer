"""Test that ingest steps emit proper events and maintain data integrity."""

import json
import tempfile
from pathlib import Path

from trailblazer.obs.events import EventEmitter, set_global_emitter


class TestIngestEvents:
    """Test ingest event emission for both Confluence and DITA."""

    def test_dita_ingest_events_basic(self):
        """Basic test for DITA ingest event emission."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create a minimal DITA file structure
            dita_root = temp_path / "dita_source"
            dita_root.mkdir(exist_ok=True)

            # Create a simple DITA topic file
            topic_file = dita_root / "test_topic.dita"
            topic_content = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE topic PUBLIC "-//OASIS//DTD DITA Topic//EN" "topic.dtd">
<topic id="test_topic">
    <title>Test Topic</title>
    <body>
        <p>This is a test DITA topic.</p>
    </body>
</topic>"""
            topic_file.write_text(topic_content)

            # Set up output directory
            run_dir = temp_path / "test-run"
            ingest_dir = run_dir / "ingest"
            ingest_dir.mkdir(parents=True, exist_ok=True)
            logs_dir = temp_path / "logs"
            logs_dir.mkdir(exist_ok=True)

            # Set up event logging
            emitter = EventEmitter(
                run_id="test-run",
                phase="ingest",
                component="dita",
                log_dir=str(logs_dir),
            )
            set_global_emitter(emitter)

            with emitter:
                # Import and run DITA ingest
                from trailblazer.pipeline.steps.ingest.dita import ingest_dita

                result = ingest_dita(
                    outdir=str(ingest_dir),
                    root=str(dita_root),
                    run_id="test-run",
                )

            # Verify basic result structure
            assert isinstance(result, dict)
            assert "topics" in result
            assert "maps" in result
            assert result["topics"] == 1  # One topic file
            assert result["maps"] == 0  # No map files

            # Verify events were emitted
            events_file = logs_dir / "test-run" / "events.ndjson"
            assert events_file.exists()

            events = []
            with open(events_file, "r") as f:
                for line in f:
                    if line.strip():
                        events.append(json.loads(line.strip()))

            # Should have start and completion events
            assert len(events) >= 2

            # Check for start event
            start_events = [
                e
                for e in events
                if "Starting DITA ingest"
                in e.get("metadata", {}).get("message", "")
            ]
            assert len(start_events) >= 1
            start_event = start_events[0]
            assert start_event["level"] == "info"
            assert start_event["run_id"] == "test-run"

            # Check for completion event
            completion_events = [
                e
                for e in events
                if "DITA ingest completed"
                in e.get("metadata", {}).get("message", "")
            ]
            assert len(completion_events) >= 1
            completion_event = completion_events[0]
            assert completion_event["level"] == "info"
            assert completion_event["run_id"] == "test-run"
            assert completion_event["metadata"]["topics"] == 1
            assert completion_event["metadata"]["files_processed"] == 1

            # Clean up
            set_global_emitter(None)

    def test_emit_functions_work_independently(self):
        """Test that emit_* functions work independently."""
        with tempfile.TemporaryDirectory() as temp_dir:
            logs_dir = Path(temp_dir) / "logs"
            logs_dir.mkdir(exist_ok=True)

            # Set up emitter
            emitter = EventEmitter(
                run_id="test-emit",
                phase="ingest",
                component="test",
                log_dir=str(logs_dir),
            )
            set_global_emitter(emitter)

            from trailblazer.obs.events import emit_info, emit_warn, emit_error

            with emitter:
                # Test emit functions
                emit_info(
                    "ingest", "test-emit", "test", message="Test info message"
                )
                emit_warn(
                    "ingest",
                    "test-emit",
                    "test",
                    message="Test warning message",
                )
                emit_error(
                    "ingest", "test-emit", "test", message="Test error message"
                )

            # Verify events
            events_file = logs_dir / "test-emit" / "events.ndjson"
            assert events_file.exists()

            events = []
            with open(events_file, "r") as f:
                for line in f:
                    events.append(json.loads(line.strip()))

            assert len(events) == 3
            assert events[0]["level"] == "info"
            assert events[1]["level"] == "warning"
            assert events[2]["level"] == "error"

            # Clean up
            set_global_emitter(None)
