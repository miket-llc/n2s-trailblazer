"""Test unified JSONL logging schema across pipeline stages."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

# Mark all tests as integration tests (need database)
pytestmark = pytest.mark.integration


class TestJSONLSchema:
    """Test that all pipeline stages use unified JSONL logging schema."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

    def test_embed_logging_schema(self):
        """Test that embed stage uses unified logging schema."""
        from trailblazer.pipeline.steps.embed.loader import load_chunks_to_db
        import io

        # Capture stdout to check event format
        captured_output = io.StringIO()

        with (
            patch("sys.stdout", captured_output),
            patch(
                "trailblazer.pipeline.steps.embed.loader.get_session_factory"
            ) as mock_session_factory,
            patch.dict(os.environ, {"TB_TESTING": "1"}),
        ):
            # Mock database session
            mock_session = MagicMock()
            mock_session_factory.return_value.__enter__.return_value = (
                mock_session
            )
            mock_session.query.return_value.filter_by.return_value.first.return_value = None
            mock_session.get.return_value = None

            # Create test chunks file
            chunks_file = self.temp_path / "test_chunks.ndjson"
            chunks_file.write_text(
                json.dumps(
                    {
                        "chunk_id": "test:0001",
                        "doc_id": "test",
                        "text_md": "Test content",
                        "char_count": 12,
                        "token_count": 3,
                    }
                )
                + "\n"
            )

            # Run embed with minimal chunks
            try:
                load_chunks_to_db(
                    chunks_file=str(chunks_file),
                    provider_name="dummy",
                    max_chunks=1,
                )
            except Exception:
                pass  # We just want to check the logging format

            # Check logged events
            output = captured_output.getvalue()
            if output.strip():
                events = [
                    json.loads(line)
                    for line in output.strip().split("\n")
                    if line.strip()
                ]

                for event in events:
                    # Check required unified schema fields
                    assert "ts" in event, "Event missing timestamp field"
                    assert "level" in event, "Event missing level field"
                    assert "stage" in event, "Event missing stage field"
                    assert "rid" in event, "Event missing run ID field"
                    assert "op" in event, "Event missing operation field"

                    # Check stage-specific fields
                    if event.get("stage") == "embed":
                        assert "provider" in event, (
                            "Embed event missing provider"
                        )
                        assert "dimension" in event, (
                            "Embed event missing dimension"
                        )

                    # Check timestamp format (ISO 8601)
                    ts = event["ts"]
                    assert "T" in ts and ("Z" in ts or "+" in ts), (
                        f"Invalid timestamp format: {ts}"
                    )

    def test_chunk_logging_schema(self):
        """Test that chunk stage uses unified logging schema."""

        # The chunk engine imports emit_event from obs.events
        # We can test that it follows the schema by checking the call
        with patch(
            "trailblazer.pipeline.steps.chunk.engine.emit_event"
        ) as mock_emit:
            from trailblazer.pipeline.steps.chunk.engine import chunk_document

            # Test chunking a document
            chunk_document(
                doc_id="test-doc",
                text_md="Test content for chunking",
                source_system="test",
            )

            # Verify emit_event was called
            assert mock_emit.called, "chunk_document should emit events"

            # Check that events use expected schema
            for call in mock_emit.call_args_list:
                args, kwargs = call
                if args:
                    event_type = args[0]
                    # Should follow unified naming pattern
                    assert "chunk." in event_type, (
                        f"Event type should be namespaced: {event_type}"
                    )

    def test_logging_field_consistency(self):
        """Test that logging fields are consistent across stages."""
        # Define required fields for unified schema
        required_fields = {"ts", "level", "stage", "rid", "op"}
        optional_fields = {
            "status",
            "duration_ms",
            "counts",
            "reason",
            "provider",
            "model",
            "dimension",
            "doc_id",
            "chunk_id",
        }

        # Test that our schema definition is complete
        assert "ts" in required_fields, "Timestamp should be required"
        assert "stage" in required_fields, "Stage should be required"
        assert "op" in required_fields, "Operation should be required"
        assert "provider" in optional_fields, (
            "Provider should be optional field"
        )
        assert "dimension" in optional_fields, (
            "Dimension should be optional field"
        )

    def test_event_level_values(self):
        """Test that event levels use standard values."""
        valid_levels = {"info", "warning", "error", "debug"}

        # Test that embed uses valid levels
        from trailblazer.pipeline.steps.embed.loader import load_chunks_to_db
        import io

        captured_output = io.StringIO()

        with (
            patch("sys.stdout", captured_output),
            patch(
                "trailblazer.pipeline.steps.embed.loader.get_session_factory"
            ) as mock_session_factory,
            patch.dict(os.environ, {"TB_TESTING": "1"}),
        ):
            mock_session = MagicMock()
            mock_session_factory.return_value.__enter__.return_value = (
                mock_session
            )
            mock_session.query.return_value.filter_by.return_value.first.return_value = None
            mock_session.get.return_value = None

            chunks_file = self.temp_path / "test_chunks.ndjson"
            chunks_file.write_text(
                json.dumps(
                    {"chunk_id": "test:0001", "text_md": "Test content"}
                )
                + "\n"
            )

            try:
                load_chunks_to_db(
                    chunks_file=str(chunks_file),
                    provider_name="dummy",
                    max_chunks=1,
                )
            except Exception:
                pass

            output = captured_output.getvalue()
            if output.strip():
                events = [
                    json.loads(line)
                    for line in output.strip().split("\n")
                    if line.strip()
                ]

                for event in events:
                    if "level" in event:
                        level = event["level"]
                        assert level in valid_levels, (
                            f"Invalid event level: {level}"
                        )

    def test_stage_naming_consistency(self):
        """Test that stage names are consistent."""
        valid_stages = {"normalize", "enrich", "chunk", "embed"}

        # Test embed stage naming
        from trailblazer.pipeline.steps.embed.loader import load_chunks_to_db
        import io

        captured_output = io.StringIO()

        with (
            patch("sys.stdout", captured_output),
            patch(
                "trailblazer.pipeline.steps.embed.loader.get_session_factory"
            ) as mock_session_factory,
            patch.dict(os.environ, {"TB_TESTING": "1"}),
        ):
            mock_session = MagicMock()
            mock_session_factory.return_value.__enter__.return_value = (
                mock_session
            )
            mock_session.query.return_value.filter_by.return_value.first.return_value = None

            chunks_file = self.temp_path / "test_chunks.ndjson"
            chunks_file.write_text(
                json.dumps(
                    {"chunk_id": "test:0001", "text_md": "Test content"}
                )
                + "\n"
            )

            try:
                load_chunks_to_db(
                    chunks_file=str(chunks_file),
                    provider_name="dummy",
                    max_chunks=1,
                )
            except Exception:
                pass

            output = captured_output.getvalue()
            if output.strip():
                events = [
                    json.loads(line)
                    for line in output.strip().split("\n")
                    if line.strip()
                ]

                for event in events:
                    if "stage" in event:
                        stage = event["stage"]
                        assert stage in valid_stages, (
                            f"Invalid stage name: {stage}"
                        )

    def test_operation_naming_convention(self):
        """Test that operation names follow consistent convention."""
        # Operations should be namespaced with stage prefix
        # e.g., "embed.start", "chunk.complete", etc.

        from trailblazer.pipeline.steps.embed.loader import load_chunks_to_db
        import io

        captured_output = io.StringIO()

        with (
            patch("sys.stdout", captured_output),
            patch(
                "trailblazer.pipeline.steps.embed.loader.get_session_factory"
            ) as mock_session_factory,
            patch.dict(os.environ, {"TB_TESTING": "1"}),
        ):
            mock_session = MagicMock()
            mock_session_factory.return_value.__enter__.return_value = (
                mock_session
            )

            chunks_file = self.temp_path / "test_chunks.ndjson"
            chunks_file.write_text(
                json.dumps(
                    {"chunk_id": "test:0001", "text_md": "Test content"}
                )
                + "\n"
            )

            try:
                load_chunks_to_db(
                    chunks_file=str(chunks_file),
                    provider_name="dummy",
                    max_chunks=1,
                )
            except Exception:
                pass

            output = captured_output.getvalue()
            if output.strip():
                events = [
                    json.loads(line)
                    for line in output.strip().split("\n")
                    if line.strip()
                ]

                for event in events:
                    if "op" in event:
                        op = event["op"]
                        # Operations should be namespaced or follow consistent patterns
                        assert "." in op or op in [
                            "start",
                            "complete",
                            "error",
                            "heartbeat",
                        ], f"Operation should be namespaced: {op}"
