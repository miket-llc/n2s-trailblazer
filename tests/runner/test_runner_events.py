"""Test that pipeline runner emits proper START/END events with totals."""

import json
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from trailblazer.obs.events import EventEmitter, set_global_emitter


class TestRunnerEvents:
    """Test pipeline runner event emission."""

    def test_runner_emits_start_end_events(self):
        """Test that pipeline run produces START/END events with totals."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            logs_dir = temp_path / "logs"
            logs_dir.mkdir(exist_ok=True)

            # Set up EventEmitter
            emitter = EventEmitter(
                run_id="runner-test",
                phase="runner",
                component="pipeline",
                log_dir=str(logs_dir),
            )
            set_global_emitter(emitter)

            # Mock the phase execution to avoid actual pipeline work
            with patch(
                "trailblazer.pipeline.runner._execute_phase"
            ) as mock_execute:
                mock_execute.return_value = None

                # Mock phase_dir to return our temp directory
                with patch(
                    "trailblazer.pipeline.runner.phase_dir"
                ) as mock_phase_dir:
                    mock_phase_dir.return_value = temp_path / "phase_output"

                    with emitter:
                        from trailblazer.pipeline.runner import run

                        # Run a simple pipeline
                        result_run_id = run(
                            phases=["normalize", "chunk"],
                            dry_run=False,
                            run_id="runner-test",
                        )

                        assert result_run_id == "runner-test"

            # Verify events were emitted
            events_file = logs_dir / "runner-test" / "events.ndjson"
            assert events_file.exists()

            events = []
            with open(events_file, "r") as f:
                for line in f:
                    if line.strip():
                        events.append(json.loads(line.strip()))

            # Should have START and END events
            assert len(events) >= 2, "Should emit START and END events"

            # Check for START event
            start_events = [e for e in events if e.get("action") == "start"]
            assert len(start_events) >= 1, "Should emit START event"

            start_event = start_events[0]
            assert start_event["phase"] == "runner"
            assert start_event["component"] == "pipeline"
            assert start_event["run_id"] == "runner-test"

            # Check for END event
            end_events = [e for e in events if e.get("action") == "complete"]
            assert len(end_events) >= 1, "Should emit END event"

            end_event = end_events[-1]
            assert end_event["phase"] == "runner"
            assert end_event["component"] == "pipeline"
            assert end_event["run_id"] == "runner-test"
            assert "duration_ms" in end_event
            assert end_event["metadata"]["phases_completed"] == [
                "normalize",
                "chunk",
            ]
            assert end_event["metadata"]["total_phases"] == 2

            # Clean up
            set_global_emitter(None)

    def test_runner_backlog_emits_events(self):
        """Test that run_from_backlog emits proper events."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            logs_dir = temp_path / "logs"
            logs_dir.mkdir(exist_ok=True)

            # Mock backlog functions
            mock_summary = {
                "total": 5,
                "sample_run_ids": ["run1", "run2", "run3"],
                "earliest": "2025-01-01",
                "latest": "2025-01-02",
            }

            with patch(
                "trailblazer.pipeline.runner.get_backlog_summary"
            ) as mock_get_summary:
                mock_get_summary.return_value = mock_summary

                with patch(
                    "trailblazer.pipeline.runner.claim_run_for_chunking"
                ) as mock_claim:
                    # Mock claiming runs - return None to end the loop
                    mock_claim.side_effect = [
                        {"run_id": "run1", "status": "ready"},
                        {"run_id": "run2", "status": "ready"},
                        None,  # End processing
                    ]

                    with patch(
                        "trailblazer.pipeline.runner._execute_phase"
                    ) as mock_execute:
                        mock_execute.return_value = None

                        with patch(
                            "trailblazer.pipeline.runner.phase_dir"
                        ) as mock_phase_dir:
                            mock_phase_dir.return_value = (
                                temp_path / "phase_output"
                            )

                            # Create a specific emitter for this test
                            backlog_run_id = (
                                f"backlog-chunk-{int(time.time())}"
                            )
                            emitter = EventEmitter(
                                run_id=backlog_run_id,
                                phase="runner",
                                component="backlog",
                                log_dir=str(logs_dir),
                            )
                            set_global_emitter(emitter)

                            with emitter:
                                from trailblazer.pipeline.runner import (
                                    run_from_backlog,
                                )

                                # Run backlog processing
                                result = run_from_backlog(
                                    phase="chunk", dry_run=False, limit=2
                                )

                                assert "Processed" in result

            # Verify events were emitted
            # Note: The actual run_id will be generated in the function
            # so we need to check for any events in the logs directory
            events_found = False
            for events_file in logs_dir.rglob("events.ndjson"):
                if events_file.exists():
                    events = []
                    with open(events_file, "r") as f:
                        for line in f:
                            if line.strip():
                                events.append(json.loads(line.strip()))

                    if events:
                        events_found = True
                        # Should have START and END events
                        start_events = [
                            e for e in events if e.get("action") == "start"
                        ]
                        end_events = [
                            e for e in events if e.get("action") == "complete"
                        ]

                        assert len(start_events) >= 1, (
                            "Should emit START event"
                        )
                        assert len(end_events) >= 1, "Should emit END event"

                        # Verify backlog-specific content
                        start_event = start_events[0]
                        assert start_event["phase"] == "runner"
                        assert start_event["component"] == "backlog"

                        end_event = end_events[0]
                        assert "processed_runs" in end_event["metadata"]
                        break

            assert events_found, "Should emit backlog processing events"

            # Clean up
            set_global_emitter(None)

    def test_runner_events_schema_compliance(self):
        """Test that runner events comply with observability schema."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            logs_dir = temp_path / "logs"
            logs_dir.mkdir(exist_ok=True)

            # Set up EventEmitter
            emitter = EventEmitter(
                run_id="schema-test",
                phase="runner",
                component="pipeline",
                log_dir=str(logs_dir),
            )
            set_global_emitter(emitter)

            from trailblazer.obs.events import emit_info

            with emitter:
                # Emit test runner events
                emit_info(
                    "runner",
                    "schema-test",
                    "pipeline",
                    message="Starting pipeline run",
                    phases=["normalize", "chunk"],
                    dry_run=False,
                )

                emit_info(
                    "runner",
                    "schema-test",
                    "pipeline",
                    message="Pipeline run completed",
                    phases_completed=["normalize", "chunk"],
                    total_phases=2,
                    dry_run=False,
                )

            # Verify events
            events_file = logs_dir / "schema-test" / "events.ndjson"
            assert events_file.exists()

            events = []
            with open(events_file, "r") as f:
                for line in f:
                    events.append(json.loads(line.strip()))

            assert len(events) == 2

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
                assert event["phase"] == "runner"
                assert event["component"] == "pipeline"
                assert event["level"] == "info"
                assert event["action"] == "tick"

            # Verify specific runner event content
            start_event = events[0]
            assert start_event["metadata"]["phases"] == ["normalize", "chunk"]
            assert start_event["metadata"]["dry_run"] is False

            end_event = events[1]
            assert end_event["metadata"]["phases_completed"] == [
                "normalize",
                "chunk",
            ]
            assert end_event["metadata"]["total_phases"] == 2

            # Clean up
            set_global_emitter(None)
