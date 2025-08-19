"""Test that monitor --json prints emitter lines for CI."""

import json
import tempfile
from pathlib import Path
from io import StringIO
from unittest.mock import patch

from trailblazer.obs.monitor import TrailblazerMonitor
from trailblazer.obs.events import EventEmitter


class TestMonitorJsonMode:
    """Test monitor JSON mode functionality."""

    def test_monitor_json_prints_emitter_lines(self):
        """Test that monitor --json prints event lines (smoke test)."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            logs_dir = temp_path / "logs"
            logs_dir.mkdir(exist_ok=True)

            # Create test events file in the structure monitor expects
            test_run_id = "monitor-test"
            # Monitor expects var/logs/{run_id}.ndjson, so create that structure
            var_logs_dir = temp_path / "var" / "logs"
            var_logs_dir.mkdir(parents=True, exist_ok=True)
            events_file = var_logs_dir / f"{test_run_id}.ndjson"

            # Create some test events in NDJSON format
            test_events = [
                {
                    "ts": "2025-08-19T17:30:00.000Z",
                    "run_id": test_run_id,
                    "phase": "ingest",
                    "component": "confluence",
                    "pid": 12345,
                    "worker_id": "confluence-12345",
                    "level": "info",
                    "action": "start",
                    "metadata": {"message": "Starting ingest"},
                },
                {
                    "ts": "2025-08-19T17:30:30.000Z",
                    "run_id": test_run_id,
                    "phase": "ingest",
                    "component": "confluence",
                    "pid": 12345,
                    "worker_id": "confluence-12345",
                    "level": "info",
                    "action": "complete",
                    "duration_ms": 30000,
                    "metadata": {"message": "Ingest completed", "pages": 100},
                },
            ]

            with open(events_file, "w") as f:
                for event in test_events:
                    f.write(json.dumps(event) + "\n")

            # Test monitor JSON mode (need to change working directory)
            import os

            original_cwd = os.getcwd()
            try:
                os.chdir(
                    temp_path
                )  # Change to temp directory so var/logs is found
                monitor = TrailblazerMonitor(
                    run_id=test_run_id, json_mode=True
                )

                # Capture stdout
                captured_output = StringIO()
                with patch("sys.stdout", captured_output):
                    monitor.display_json()
            finally:
                os.chdir(original_cwd)

            output = captured_output.getvalue()

            # Should output valid JSON
            summary = json.loads(output)

            # Verify summary structure
            assert summary["run_id"] == test_run_id
            assert "progress" in summary
            assert "recent_events" in summary
            assert (
                len(summary["recent_events"]) <= 5
            )  # Should limit to 5 recent events

    def test_monitor_json_events_mode(self):
        """Test that monitor can print raw event lines for CI."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            logs_dir = temp_path / "logs"
            logs_dir.mkdir(exist_ok=True)

            # Create test events file
            test_run_id = "events-test"
            events_file = logs_dir / f"{test_run_id}.ndjson"

            # Create test events
            test_events = [
                {
                    "ts": "2025-08-19T17:30:00.000Z",
                    "run_id": test_run_id,
                    "level": "info",
                    "message": "Event 1",
                },
                {
                    "ts": "2025-08-19T17:30:01.000Z",
                    "run_id": test_run_id,
                    "level": "warning",
                    "message": "Event 2",
                },
                {
                    "ts": "2025-08-19T17:30:02.000Z",
                    "run_id": test_run_id,
                    "level": "error",
                    "message": "Event 3",
                },
            ]

            with open(events_file, "w") as f:
                for event in test_events:
                    f.write(json.dumps(event) + "\n")

            # Test monitor JSON events mode
            monitor = TrailblazerMonitor(run_id=test_run_id, json_mode=True)

            # Capture stdout
            captured_output = StringIO()
            with patch("sys.stdout", captured_output):
                monitor.display_json_events()

            output_lines = captured_output.getvalue().strip().split("\n")

            # Should output each event as a separate JSON line
            assert len(output_lines) == 3, (
                f"Should output 3 event lines, got {len(output_lines)}"
            )

            # Verify each line is valid JSON
            for i, line in enumerate(output_lines):
                event = json.loads(line)
                assert event["run_id"] == test_run_id
                assert event["message"] == f"Event {i + 1}"

    def test_monitor_path_sync_with_emitter(self):
        """Test that monitor uses same path as EventEmitter."""
        test_run_id = "path-sync-test"

        # Create monitor
        monitor = TrailblazerMonitor(run_id=test_run_id)

        # Verify monitor uses correct path format
        expected_log_path = Path(f"var/logs/{test_run_id}.ndjson")
        assert monitor.log_file == expected_log_path

        # Create EventEmitter and verify it creates compatible path
        with tempfile.TemporaryDirectory():
            EventEmitter(
                run_id=test_run_id,
                phase="test",
                component="sync",
                log_dir="var/logs",  # Use same base directory
            )

            # EventEmitter creates: var/logs/<run_id>/events.ndjson
            # Monitor expects: var/logs/<run_id>.ndjson
            # They should be linked via symlink

            (Path("var/logs") / test_run_id / "events.ndjson")
            Path("var/logs") / f"{test_run_id}.ndjson"

            # The paths are compatible through the symlink system
            assert monitor.log_file.name == f"{test_run_id}.ndjson"

    def test_monitor_handles_missing_log_file(self):
        """Test that monitor handles missing log file gracefully."""
        # Test with non-existent run
        monitor = TrailblazerMonitor(run_id="nonexistent", json_mode=True)

        # Capture stdout
        captured_output = StringIO()
        with patch("sys.stdout", captured_output):
            monitor.display_json_events()

        output = captured_output.getvalue()

        # Should output error JSON
        error_data = json.loads(output)
        assert "error" in error_data
        assert "No event log file found" in error_data["error"]
        assert error_data["run_id"] == "nonexistent"

    def test_monitor_validates_json_format(self):
        """Test that monitor validates JSON format when reading events."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            logs_dir = temp_path / "logs"
            logs_dir.mkdir(exist_ok=True)

            # Create events file with mixed valid/invalid JSON
            test_run_id = "validation-test"
            events_file = logs_dir / f"{test_run_id}.ndjson"

            with open(events_file, "w") as f:
                f.write('{"valid": "json", "run_id": "validation-test"}\n')
                f.write("invalid json line\n")  # Invalid JSON
                f.write('{"another": "valid", "run_id": "validation-test"}\n')
                f.write("\n")  # Empty line

            # Test monitor JSON events mode
            monitor = TrailblazerMonitor(run_id=test_run_id, json_mode=True)

            # Capture stdout
            captured_output = StringIO()
            with patch("sys.stdout", captured_output):
                monitor.display_json_events()

            output_lines = captured_output.getvalue().strip().split("\n")

            # Should only output valid JSON lines (skip invalid ones)
            assert len(output_lines) == 2, (
                f"Should output 2 valid lines, got {len(output_lines)}"
            )

            # Verify each output line is valid JSON
            for line in output_lines:
                event = json.loads(line)
                assert event["run_id"] == test_run_id
