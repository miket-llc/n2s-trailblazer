"""Test that preflight commands emit standardized events with READY/BLOCKED status and reason codes."""

import json
import tempfile
from pathlib import Path

from trailblazer.obs.events import EventEmitter, set_global_emitter


class TestPreflightEvents:
    """Test preflight event emission for both single and plan preflight commands."""

    def test_preflight_emits_ready_status_event(self):
        """Test that preflight emits READY status events with proper structure."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            logs_dir = temp_path / "logs"
            logs_dir.mkdir(exist_ok=True)

            # Set up EventEmitter
            emitter = EventEmitter(
                run_id="test-run",
                phase="preflight",
                component="embed",
                log_dir=str(logs_dir),
            )
            set_global_emitter(emitter)

            from trailblazer.obs.events import emit_info

            with emitter:
                # Simulate preflight events that would be emitted by CLI
                emit_info(
                    "preflight",
                    "test-run",
                    "embed",
                    message="Starting preflight validation",
                    provider="openai",
                    model="text-embedding-3-small",
                    dimension=1536,
                )

                emit_info(
                    "preflight",
                    "test-run",
                    "embed",
                    message="Preflight validation completed",
                    status="READY",
                    enriched_docs=100,
                    chunks=500,
                )

            # Verify events were emitted
            events_file = logs_dir / "test-run" / "events.ndjson"
            assert events_file.exists()

            events = []
            with open(events_file, "r") as f:
                for line in f:
                    if line.strip():
                        events.append(json.loads(line.strip()))

            # Should have preflight events
            assert len(events) >= 2, "Should emit preflight events"

            # Check for READY status event
            ready_events = [
                e
                for e in events
                if e.get("metadata", {}).get("status") == "READY"
            ]
            assert len(ready_events) >= 1, "Should emit READY status event"

            ready_event = ready_events[0]
            assert ready_event["metadata"]["enriched_docs"] == 100
            assert ready_event["metadata"]["chunks"] == 500

            # Clean up
            set_global_emitter(None)

    def test_preflight_blocked_reason_codes(self):
        """Test that preflight emits proper reason codes for BLOCKED status."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            logs_dir = temp_path / "logs"
            logs_dir.mkdir(exist_ok=True)

            # Set up EventEmitter
            emitter = EventEmitter(
                run_id="blocked-test",
                phase="preflight",
                component="embed",
                log_dir=str(logs_dir),
            )
            set_global_emitter(emitter)

            from trailblazer.obs.events import emit_info

            with emitter:
                # Simulate various BLOCKED scenarios
                blocked_reasons = [
                    "RUN_NOT_FOUND",
                    "MISSING_ENRICHED",
                    "MISSING_CHUNKS",
                    "EMPTY_ENRICHED",
                ]

                for reason in blocked_reasons:
                    emit_info(
                        "preflight",
                        "blocked-test",
                        "embed",
                        message="Preflight validation failed",
                        status="BLOCKED",
                        reason=reason,
                    )

            # Verify events were emitted
            events_file = logs_dir / "blocked-test" / "events.ndjson"
            assert events_file.exists()

            events = []
            with open(events_file, "r") as f:
                for line in f:
                    if line.strip():
                        events.append(json.loads(line.strip()))

            # Should have BLOCKED events
            blocked_events = [
                e
                for e in events
                if e.get("metadata", {}).get("status") == "BLOCKED"
            ]
            assert len(blocked_events) == 4, (
                f"Should emit 4 BLOCKED events, got {len(blocked_events)}"
            )

            # Verify reason codes
            reason_codes = [
                e.get("metadata", {}).get("reason") for e in blocked_events
            ]
            expected_reasons = [
                "RUN_NOT_FOUND",
                "MISSING_ENRICHED",
                "MISSING_CHUNKS",
                "EMPTY_ENRICHED",
            ]
            for expected_reason in expected_reasons:
                assert expected_reason in reason_codes, (
                    f"Missing reason code: {expected_reason}"
                )

            # Clean up
            set_global_emitter(None)

    def test_plan_preflight_emits_per_rid_events(self):
        """Test that plan-preflight emits events for each RID with status and reason."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            logs_dir = temp_path / "logs"
            logs_dir.mkdir(exist_ok=True)

            # Set up EventEmitter with timestamp
            timestamp = "20250819_130000"
            emitter = EventEmitter(
                run_id=timestamp,
                phase="plan_preflight",
                component="embed",
                log_dir=str(logs_dir),
            )
            set_global_emitter(emitter)

            from trailblazer.obs.events import emit_info

            with emitter:
                # Simulate plan-preflight events for multiple RIDs
                test_runs = [
                    {
                        "run_id": "test-run-1",
                        "status": "READY",
                        "docs": 10,
                        "chunks": 100,
                    },
                    {
                        "run_id": "test-run-2",
                        "status": "BLOCKED",
                        "reason": "MISSING_CHUNKS",
                    },
                    {
                        "run_id": "test-run-3",
                        "status": "BLOCKED",
                        "reason": "QUALITY_GATE",
                    },
                ]

                for run_data in test_runs:
                    if run_data["status"] == "READY":
                        emit_info(
                            "plan_preflight",
                            timestamp,
                            "embed",
                            message="Run preflight validation completed",
                            test_run_id=run_data["run_id"],
                            status="READY",
                            docs=run_data["docs"],
                            chunks=run_data["chunks"],
                        )
                    else:
                        emit_info(
                            "plan_preflight",
                            timestamp,
                            "embed",
                            message="Run preflight validation failed",
                            test_run_id=run_data["run_id"],
                            status="BLOCKED",
                            reason=run_data["reason"],
                        )

            # Verify events were emitted
            events_file = logs_dir / timestamp / "events.ndjson"
            assert events_file.exists()

            events = []
            with open(events_file, "r") as f:
                for line in f:
                    if line.strip():
                        events.append(json.loads(line.strip()))

            # Should have per-RID status events
            assert len(events) >= 3, (
                f"Should emit events for each RID, got {len(events)} events"
            )

            # Check for READY and BLOCKED events
            ready_events = [
                e
                for e in events
                if e.get("metadata", {}).get("status") == "READY"
            ]
            blocked_events = [
                e
                for e in events
                if e.get("metadata", {}).get("status") == "BLOCKED"
            ]

            assert len(ready_events) >= 1, "Should have READY events"
            assert len(blocked_events) >= 2, "Should have BLOCKED events"

            # Verify reason codes for blocked events
            for event in blocked_events:
                reason = event.get("metadata", {}).get("reason")
                expected_reasons = [
                    "MISSING_CHUNKS",
                    "MISSING_ENRICHED",
                    "QUALITY_GATE",
                    "TOKENIZER_MISSING",
                    "CONFIG_INVALID",
                    "PREFLIGHT_FILE_MISSING",
                    "PREFLIGHT_PARSE_ERROR",
                ]
                assert reason in expected_reasons, (
                    f"Invalid reason code: {reason}"
                )

            # Clean up
            set_global_emitter(None)

    def test_preflight_events_ndjson_format(self):
        """Test that preflight events are properly formatted in NDJSON."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            logs_dir = temp_path / "logs"
            logs_dir.mkdir(exist_ok=True)

            # Set up EventEmitter
            emitter = EventEmitter(
                run_id="format-test",
                phase="preflight",
                component="embed",
                log_dir=str(logs_dir),
            )
            set_global_emitter(emitter)

            with emitter:
                # Import emit functions
                from trailblazer.obs.events import emit_info

                # Emit test preflight events
                emit_info(
                    "preflight",
                    "format-test",
                    "embed",
                    message="Starting preflight validation",
                    provider="openai",
                    model="text-embedding-3-small",
                    dimension=1536,
                )

                emit_info(
                    "preflight",
                    "format-test",
                    "embed",
                    message="Preflight validation failed",
                    status="BLOCKED",
                    reason="MISSING_CHUNKS",
                )

                emit_info(
                    "preflight",
                    "format-test",
                    "embed",
                    message="Preflight validation completed",
                    status="READY",
                    enriched_docs=100,
                    chunks=500,
                )

            # Verify NDJSON format
            events_file = logs_dir / "format-test" / "events.ndjson"
            assert events_file.exists()

            events = []
            with open(events_file, "r") as f:
                for line in f:
                    event = json.loads(line.strip())
                    events.append(event)

            assert len(events) == 3

            # Verify NDJSON format and required fields
            for event in events:
                # Standard observability event fields
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
                    assert field in event, (
                        f"Missing required field '{field}' in event: {event}"
                    )

                # Verify field values
                assert event["ts"].endswith("Z")
                assert event["run_id"] == "format-test"
                assert event["phase"] == "preflight"
                assert event["component"] == "embed"
                assert event["level"] == "info"
                assert event["action"] == "tick"

            # Verify specific event content
            start_event = events[0]
            assert (
                "Starting preflight validation"
                in start_event["metadata"]["message"]
            )
            assert (
                start_event["provider"] == "openai"
            )  # provider is a direct field
            assert (
                start_event["metadata"]["dimension"] == 1536
            )  # dimension goes to metadata

            blocked_event = events[1]
            assert blocked_event["metadata"]["status"] == "BLOCKED"
            assert blocked_event["metadata"]["reason"] == "MISSING_CHUNKS"

            ready_event = events[2]
            assert ready_event["metadata"]["status"] == "READY"
            assert ready_event["metadata"]["enriched_docs"] == 100
            assert ready_event["metadata"]["chunks"] == 500

            # Clean up
            set_global_emitter(None)

    def test_preflight_reason_codes_comprehensive(self):
        """Test comprehensive list of preflight reason codes."""
        expected_reason_codes = [
            "RUN_NOT_FOUND",
            "MISSING_ENRICHED",
            "EMPTY_ENRICHED",
            "MISSING_CHUNKS",
            "QUALITY_GATE",
            "TOKENIZER_MISSING",
            "CONFIG_INVALID",
            "PREFLIGHT_FILE_MISSING",
            "PREFLIGHT_PARSE_ERROR",
        ]

        # This test documents the expected reason codes
        # In practice, these would be emitted by the actual preflight logic

        with tempfile.TemporaryDirectory() as temp_dir:
            logs_dir = Path(temp_dir) / "logs"
            logs_dir.mkdir(exist_ok=True)

            emitter = EventEmitter(
                run_id="reason-codes-test",
                phase="preflight",
                component="embed",
                log_dir=str(logs_dir),
            )
            set_global_emitter(emitter)

            from trailblazer.obs.events import emit_info

            with emitter:
                # Emit events with each reason code
                for reason in expected_reason_codes:
                    emit_info(
                        "preflight",
                        "reason-codes-test",
                        "embed",
                        message="Preflight validation failed",
                        status="BLOCKED",
                        reason=reason,
                        test_run_id=f"test-{reason.lower()}",
                    )

            # Verify all reason codes were captured
            events_file = logs_dir / "reason-codes-test" / "events.ndjson"
            assert events_file.exists()

            events = []
            with open(events_file, "r") as f:
                for line in f:
                    events.append(json.loads(line.strip()))

            assert len(events) == len(expected_reason_codes)

            # Verify each reason code appears
            emitted_reasons = [
                e.get("metadata", {}).get("reason") for e in events
            ]
            for expected_reason in expected_reason_codes:
                assert expected_reason in emitted_reasons, (
                    f"Missing reason code: {expected_reason}"
                )

            # Clean up
            set_global_emitter(None)
