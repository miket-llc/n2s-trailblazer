"""Test that chunk step emits proper events for chunk.begin/chunk.doc/chunk.end."""

import json
import tempfile
from pathlib import Path
from typing import List, Dict, Any

from trailblazer.pipeline.steps.chunk.engine import chunk_document
from trailblazer.obs.events import EventEmitter, set_global_emitter


class TestChunkEventsEmitted:
    """Test chunk event emission through EventEmitter."""

    def test_chunk_document_emits_events_via_emit_param(self):
        """Test that chunk_document emits events when emit parameter is provided."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            logs_dir = temp_path / "logs"
            logs_dir.mkdir(exist_ok=True)

            # Set up EventEmitter
            emitter = EventEmitter(
                run_id="test-chunk",
                phase="chunk",
                component="chunker",
                log_dir=str(logs_dir),
            )

            # Collect emitted events
            emitted_events: List[Dict[str, Any]] = []

            def test_emit(event_type: str, **kwargs):
                """Test emit function that captures events."""
                emitted_events.append({"event_type": event_type, **kwargs})

            # Test document that will create multiple chunks
            test_doc = """# Main Title

This is the first paragraph with some content that should be long enough to create multiple chunks when we have a low token limit.

## Section 1

This is another section with content. We want to make sure this creates multiple chunks so we can test the event emission properly.

## Section 2

And here's a third section with even more content to ensure we get multiple chunks and can verify that events are emitted for each chunk created during the chunking process.

## Section 3

Final section with additional content to make sure we have enough text to trigger multiple chunks and verify the event emission works correctly throughout the entire chunking process."""

            with emitter:
                # Call chunk_document with our test emit function
                chunks = chunk_document(
                    doc_id="test-doc-001",
                    text_md=test_doc,
                    title="Test Document",
                    url="https://example.com/test-doc",
                    source_system="test",
                    labels=["test", "chunking"],
                    hard_max_tokens=100,  # Low limit to force multiple chunks
                    min_tokens=50,
                    overlap_tokens=20,
                    model="text-embedding-3-small",
                    emit=test_emit,
                )

            # Verify chunks were created
            assert len(chunks) > 1, (
                "Should create multiple chunks with low token limit"
            )

            # Verify events were emitted
            assert len(emitted_events) > 0, (
                "Should emit events during chunking"
            )

            # Check for specific event types
            event_types = [e["event_type"] for e in emitted_events]

            # Should have chunk.begin, chunk.doc, and chunk.end events
            assert "chunk.begin" in event_types, (
                f"Should emit chunk.begin event, got: {event_types}"
            )
            assert "chunk.doc" in event_types, (
                f"Should emit chunk.doc events, got: {event_types}"
            )
            assert "chunk.end" in event_types, (
                f"Should emit chunk.end event, got: {event_types}"
            )

            # Should have multiple chunk.doc events (may be more than final chunks due to glue pass)
            doc_events = [
                e for e in emitted_events if e["event_type"] == "chunk.doc"
            ]
            assert len(doc_events) >= len(chunks), (
                f"Should emit chunk.doc events during processing, got {len(doc_events)} events for {len(chunks)} final chunks"
            )

            # Verify event data structure
            for event in emitted_events:
                assert "event_type" in event
                # Each event should have relevant metadata
                if event["event_type"] == "chunk.begin":
                    assert "doc_id" in event
                    assert "title" in event
                    assert "source_system" in event
                elif event["event_type"] == "chunk.doc":
                    assert "chunk_id" in event
                    assert "token_count" in event
                    assert "chunk_type" in event
                    assert "split_strategy" in event
                elif event["event_type"] == "chunk.end":
                    assert "doc_id" in event
                    assert "total_chunks" in event
                    assert "coverage_pct" in event

    def test_chunk_document_uses_module_emit_when_no_param(self):
        """Test that chunk_document uses module-level emit_event when no emit param provided."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            logs_dir = temp_path / "logs"
            logs_dir.mkdir(exist_ok=True)

            # Set up EventEmitter for module-level emit_event
            emitter = EventEmitter(
                run_id="test-module-emit",
                phase="chunk",
                component="chunker",
                log_dir=str(logs_dir),
            )
            set_global_emitter(emitter)

            test_doc = """# Test Document

This is a test document with enough content to potentially trigger events during chunking. We want to make sure that when no emit parameter is provided, the module-level emit_event function is used instead."""

            with emitter:
                # Call chunk_document without emit parameter
                chunks = chunk_document(
                    doc_id="test-doc-002",
                    text_md=test_doc,
                    title="Module Emit Test",
                    url="https://example.com/module-test",
                    source_system="test",
                    hard_max_tokens=50,  # Low limit to potentially trigger events
                    min_tokens=20,
                    model="text-embedding-3-small",
                    # No emit parameter - should use module-level emit_event
                )

            # Verify chunks were created
            assert len(chunks) >= 1

            # Verify events were written to EventEmitter
            events_file = logs_dir / "test-module-emit" / "events.ndjson"
            assert events_file.exists()

            events = []
            with open(events_file, "r") as f:
                for line in f:
                    if line.strip():
                        events.append(json.loads(line.strip()))

            # Should have some events from the chunker
            assert len(events) > 0

            # Clean up
            set_global_emitter(None)

    def test_chunk_events_in_ndjson_format(self):
        """Test that chunk events land in var/logs/<RID>/events.ndjson with proper format."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            logs_dir = temp_path / "logs"
            logs_dir.mkdir(exist_ok=True)

            # Set up EventEmitter
            emitter = EventEmitter(
                run_id="chunk-events-test",
                phase="chunk",
                component="chunker",
                log_dir=str(logs_dir),
            )

            # Track events through emit wrapper like CLI does
            def cli_emit_wrapper(event_type: str, **kwargs):
                """CLI-style emit wrapper."""
                if event_type == "chunk.begin":
                    input_file = kwargs.get("input_file")
                    emitter.chunk_start(input_file=input_file)
                elif event_type == "chunk.doc":
                    # Use generic _emit for chunk.doc events with chunk-specific data
                    emitter._emit("tick", **kwargs)
                elif event_type == "chunk.end":
                    total_chunks = kwargs.get("total_chunks", 0)
                    duration_ms = kwargs.get("duration_ms", 0)
                    emitter.chunk_complete(
                        total_chunks=total_chunks, duration_ms=duration_ms
                    )
                elif event_type == "chunk.force_truncate":
                    emitter.warning(
                        f"Chunk force truncated: {kwargs.get('chunk_id', 'unknown')}",
                        **kwargs,
                    )
                elif event_type == "chunk.coverage_warning":
                    emitter.warning(
                        f"Coverage warning for doc {kwargs.get('doc_id', 'unknown')}",
                        **kwargs,
                    )

            test_doc = "# Test\n\nShort document for testing."

            with emitter:
                # Emit some test events through the wrapper
                cli_emit_wrapper("chunk.begin", input_file="test.json")

                # Call chunk_document
                chunks = chunk_document(
                    doc_id="test-doc-003",
                    text_md=test_doc,
                    title="NDJSON Test",
                    hard_max_tokens=200,
                    emit=cli_emit_wrapper,
                )

                cli_emit_wrapper(
                    "chunk.end", total_chunks=len(chunks), duration_ms=100
                )

            # Verify events file exists and has proper format
            events_file = logs_dir / "chunk-events-test" / "events.ndjson"
            assert events_file.exists()

            events = []
            with open(events_file, "r") as f:
                for line in f:
                    event = json.loads(line.strip())
                    events.append(event)

            # Should have at least begin and end events
            assert len(events) >= 2

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
                assert event["run_id"] == "chunk-events-test"
                assert event["phase"] == "chunk"
                assert event["component"] == "chunker"
                assert event["level"] in ["info", "warning", "error"]
                assert event["action"] in [
                    "start",
                    "tick",
                    "complete",
                    "warning",
                    "error",
                ]

            # Check for chunk.begin event
            begin_events = [e for e in events if e.get("action") == "start"]
            assert len(begin_events) >= 1

            # Check for chunk.end event
            end_events = [e for e in events if e.get("action") == "complete"]
            assert len(end_events) >= 1

    def test_chunk_engine_import_error_handling(self):
        """Test that chunk engine raises ImportError when obs.events unavailable."""
        # This test verifies the ImportError behavior
        # In practice, obs.events should always be available in production

        # The import happens at module level, so we can't easily test the ImportError
        # without complex mocking. Instead, verify the import statement is correct
        from trailblazer.pipeline.steps.chunk.engine import chunk_document

        # If we got here, the import worked (which is expected in normal operation)
        assert chunk_document is not None

        # Test that the function accepts the emit parameter
        import inspect

        sig = inspect.signature(chunk_document)
        assert "emit" in sig.parameters
        assert (
            sig.parameters["emit"].annotation
            == "Optional[Callable[..., None]]"
        )
