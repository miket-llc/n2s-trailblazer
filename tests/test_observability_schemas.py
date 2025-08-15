"""Test observability event schemas and emission."""

import json
import tempfile
from pathlib import Path
from src.trailblazer.obs.events import (
    EventEmitter,
    ObservabilityEvent,
    EventLevel,
    EventAction,
)


def test_observability_event_schema():
    """Test that ObservabilityEvent schema is properly typed."""
    # Valid event
    event = ObservabilityEvent(
        ts="2024-01-01T00:00:00Z",
        run_id="test-run-123",
        phase="ingest",
        component="confluence",
        pid=12345,
        worker_id="confluence-12345",
        level=EventLevel.INFO,
        action=EventAction.START,
        space_key="TEST",
        metadata={"extra": "data"},
    )

    assert event.ts == "2024-01-01T00:00:00Z"
    assert event.run_id == "test-run-123"
    assert event.phase == "ingest"
    assert event.component == "confluence"
    assert event.level == EventLevel.INFO
    assert event.action == EventAction.START
    assert event.space_key == "TEST"
    assert event.metadata["extra"] == "data"


def test_event_emitter_creates_ndjson():
    """Test that EventEmitter creates valid NDJSON events."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Override the log directory
        import src.trailblazer.obs.events as events_module

        events_module.Path = (
            lambda x: Path(tmpdir) / x if "var/logs" in str(x) else Path(x)
        )

        try:
            with EventEmitter("test-run", "ingest", "confluence") as emitter:
                emitter.ingest_start(space_key="TEST", sourcefile="test.xml")
                emitter.ingest_tick(processed=50, space_key="TEST")
                emitter.ingest_complete(total_processed=100, duration_ms=5000)
                emitter.warning("Test warning message")
                emitter.error("Test error message", error_type="TestError")

            # Check log file was created
            log_file = Path(tmpdir) / "test-run.ndjson"
            assert log_file.exists()

            # Parse and validate NDJSON
            lines = log_file.read_text().strip().split("\n")
            assert len(lines) == 5

            events = [json.loads(line) for line in lines]

            # Validate first event (ingest.start)
            start_event = events[0]
            assert start_event["action"] == "start"
            assert start_event["phase"] == "ingest"
            assert start_event["component"] == "confluence"
            assert start_event["space_key"] == "TEST"
            assert start_event["sourcefile"] == "test.xml"
            assert "ts" in start_event
            assert start_event["run_id"] == "test-run"

            # Validate tick event
            tick_event = events[1]
            assert tick_event["action"] == "tick"
            assert tick_event["metadata"]["processed"] == 50

            # Validate completion event
            complete_event = events[2]
            assert complete_event["action"] == "complete"
            assert complete_event["duration_ms"] == 5000
            assert complete_event["metadata"]["total_processed"] == 100

            # Validate warning event
            warning_event = events[3]
            assert warning_event["action"] == "warning"
            assert warning_event["level"] == "warning"
            assert (
                warning_event["metadata"]["message"] == "Test warning message"
            )

            # Validate error event
            error_event = events[4]
            assert error_event["action"] == "error"
            assert error_event["level"] == "error"
            assert error_event["metadata"]["message"] == "Test error message"
            assert error_event["metadata"]["error_type"] == "TestError"

        finally:
            # Restore original Path
            events_module.Path = Path


def test_heartbeat_event_structure():
    """Test heartbeat event has required fields."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Override the log directory
        import src.trailblazer.obs.events as events_module

        events_module.Path = (
            lambda x: Path(tmpdir) / x if "var/logs" in str(x) else Path(x)
        )

        try:
            with EventEmitter("test-run", "embed", "openai") as emitter:
                emitter.heartbeat(
                    processed=150,
                    rate=2.5,
                    eta_seconds=300.0,
                    active_workers=3,
                    provider="openai",
                    model="text-embedding-3-small",
                )

            # Check heartbeat event
            log_file = Path(tmpdir) / "test-run.ndjson"
            event = json.loads(log_file.read_text().strip())

            assert event["action"] == "heartbeat"
            assert event["phase"] == "embed"
            assert event["component"] == "openai"
            assert event["metadata"]["processed"] == 150
            assert event["metadata"]["rate"] == 2.5
            assert event["metadata"]["eta_seconds"] == 300.0
            assert event["metadata"]["active_workers"] == 3
            assert event["metadata"]["provider"] == "openai"
            assert event["metadata"]["model"] == "text-embedding-3-small"

        finally:
            events_module.Path = Path


def test_stable_event_names():
    """Test that event names follow the required patterns."""
    expected_actions = [
        "start",
        "tick",
        "complete",
        "error",
        "warning",
        "heartbeat",
    ]

    for action in expected_actions:
        assert hasattr(EventAction, action.upper())
        assert getattr(EventAction, action.upper()).value == action

    # Test phase-specific event patterns
    with tempfile.TemporaryDirectory() as tmpdir:
        import src.trailblazer.obs.events as events_module

        events_module.Path = (
            lambda x: Path(tmpdir) / x if "var/logs" in str(x) else Path(x)
        )

        try:
            with EventEmitter("test", "test", "test") as emitter:
                # Test all phase-specific start events
                emitter.ingest_start()
                emitter.normalize_start()
                emitter.enrich_start()
                emitter.chunk_start()
                emitter.embed_start(
                    provider="test", model="test", embedding_dims=1536
                )
                emitter.retrieve_start(query="test")
                emitter.compose_start()
                emitter.playbook_start(playbook_type="test")

            log_file = Path(tmpdir) / "test.ndjson"
            lines = log_file.read_text().strip().split("\n")
            events = [json.loads(line) for line in lines]

            # All should be start events
            for event in events:
                assert event["action"] == "start"
                assert "ts" in event
                assert "run_id" in event
                assert "phase" in event
                assert "component" in event

        finally:
            events_module.Path = Path
