"""Tests for observability and assurance features."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch
import pytest

from trailblazer.core.event_log import EventLogger, init_event_logger
from trailblazer.core.assurance import generate_assurance_report
from trailblazer.core.progress import ProgressRenderer

# Mark all tests as unit tests (no database needed)
pytestmark = pytest.mark.unit


class TestEventLogger:
    """Test structured event logging."""

    def test_event_logger_init(self):
        """Test event logger initialization."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "test.ndjson"

            with EventLogger(log_path, "test-run") as logger:
                assert logger.run_id == "test-run"
                assert logger.log_path == log_path
                assert log_path.exists()

    def test_event_logging(self):
        """Test various event types are logged correctly."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "test.ndjson"

            with EventLogger(log_path, "test-run") as logger:
                # Log various events
                logger.space_begin(
                    source="confluence",
                    space_key="TEST",
                    space_id="123",
                    estimated_pages=10,
                )

                logger.page_fetch(
                    source="confluence",
                    space_key="TEST",
                    page_id="456",
                    title="Test Page",
                    url="https://example.com",
                    version=1,
                )

                logger.page_write(
                    source="confluence",
                    space_key="TEST",
                    page_id="456",
                    title="Test Page",
                    content_sha256="abc123",
                    body_repr="adf",
                    attachment_count=2,
                    bytes_written=1024,
                )

                logger.error(
                    message="Test error", error_type="api_error", retry_count=2
                )

            # Read and verify events
            events = []
            with open(log_path, "r") as f:
                for line in f:
                    events.append(json.loads(line.strip()))

            assert len(events) == 4

            # Check space.begin event
            space_begin = events[0]
            assert space_begin["event_type"] == "space.begin"
            assert space_begin["run_id"] == "test-run"
            assert space_begin["source"] == "confluence"
            assert space_begin["space_key"] == "TEST"
            assert space_begin["estimated_pages"] == 10
            assert "timestamp" in space_begin

            # Check page.fetch event
            page_fetch = events[1]
            assert page_fetch["event_type"] == "page.fetch"
            assert page_fetch["page_id"] == "456"
            assert page_fetch["title"] == "Test Page"

            # Check page.write event
            page_write = events[2]
            assert page_write["event_type"] == "page.write"
            assert page_write["content_sha256"] == "abc123"
            assert page_write["attachment_count"] == 2
            assert page_write["bytes_written"] == 1024

            # Check error event
            error_event = events[3]
            assert error_event["event_type"] == "error"
            assert error_event["message"] == "Test error"
            assert error_event["error_type"] == "api_error"
            assert error_event["retry_count"] == 2

    def test_heartbeat_event(self):
        """Test heartbeat event logging."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "test.ndjson"

            with EventLogger(log_path, "test-run") as logger:
                logger.heartbeat(
                    phase="ingesting",
                    processed=100,
                    rate=2.5,
                    elapsed=40.0,
                    eta=20.0,
                    last_api_status="200 OK",
                    retries=1,
                )

            with open(log_path, "r") as f:
                event = json.loads(f.read().strip())

            assert event["event_type"] == "heartbeat"
            assert event["phase"] == "ingesting"
            assert event["processed"] == 100
            assert event["rate"] == 2.5
            assert event["elapsed"] == 40.0
            assert event["eta"] == 20.0
            assert event["last_api_status"] == "200 OK"
            assert event["retries"] == 1


class TestAssuranceReport:
    """Test assurance report generation."""

    def test_assurance_report_generation(self):
        """Test generating assurance reports from fake data."""
        with tempfile.TemporaryDirectory() as temp_dir:
            outdir = Path(temp_dir)

            # Create fake confluence.ndjson
            fake_data = [
                {
                    "id": "page1",
                    "title": "Test Page 1",
                    "space_key": "TEST",
                    "url": "https://example.com/page1",
                    "body_repr": "adf",
                    "body_adf": {"type": "doc", "content": []},
                    "attachment_count": 2,
                    "attachments": [
                        {"filename": "file1.pdf"},
                        {"filename": "file2.png"},
                    ],
                    "content_sha256": "hash1",
                    "version": 1,
                },
                {
                    "id": "page2",
                    "title": "Empty Page",
                    "space_key": "TEST",
                    "url": "https://example.com/page2",
                    "body_repr": "adf",
                    "body_adf": None,  # Empty body
                    "attachment_count": 0,
                    "attachments": [],
                    "content_sha256": "hash2",
                    "version": 2,
                },
                {
                    "id": "page3",
                    "title": "Large Page",
                    "space_key": "LARGE",
                    "url": "https://example.com/page3",
                    "body_repr": "storage",
                    "body_storage": "x" * 60000,  # Large page
                    "attachment_count": 1,
                    "attachments": [{"filename": "big.zip"}],
                    "content_sha256": "hash3",
                    "version": 3,
                },
            ]

            confluence_file = outdir / "confluence.ndjson"
            with open(confluence_file, "w") as f:
                for record in fake_data:
                    f.write(json.dumps(record) + "\n")

            # Create fake summary.json
            summary = {
                "total_pages": 3,
                "total_attachments": 3,
                "elapsed_seconds": 10.5,
                "warnings": ["test_warning"],
            }
            summary_file = outdir / "summary.json"
            with open(summary_file, "w") as f:
                json.dump(summary, f)

            # Create fake event log
            event_log_path = outdir / "events.ndjson"
            events = [
                {
                    "timestamp": "2025-01-01T12:00:00Z",
                    "event_type": "error",
                    "error_type": "api_timeout",
                    "space_key": "TEST",
                    "message": "API timeout",
                },
                {
                    "timestamp": "2025-01-01T12:01:00Z",
                    "event_type": "space.end",
                    "space_key": "TEST",
                    "elapsed_seconds": 5.0,
                    "pages_processed": 2,
                },
            ]
            with open(event_log_path, "w") as f:
                for event in events:
                    f.write(json.dumps(event) + "\n")

            # Generate assurance report
            json_path, md_path = generate_assurance_report(
                run_id="test-run-123",
                source="confluence",
                outdir=outdir,
                event_log_path=event_log_path,
            )

            # Verify JSON report
            assert json_path.exists()
            with open(json_path, "r") as f:
                report = json.load(f)

            assert report["run_id"] == "test-run-123"
            assert report["source"] == "confluence"
            assert report["totals"]["pages"] == 3
            assert report["totals"]["attachments"] == 3
            assert report["totals"]["spaces"] == 2  # TEST and LARGE

            # Check quality issues
            assert len(report["quality_issues"]["zero_body_pages"]) == 1
            assert (
                report["quality_issues"]["zero_body_pages"][0]["page_id"]
                == "page2"
            )

            assert len(report["performance"]["top_10_largest_pages"]) >= 1
            large_page = report["performance"]["top_10_largest_pages"][0]
            assert large_page["page_id"] == "page3"
            assert large_page["char_count"] == 60000

            # Check error analysis
            assert report["errors"]["summary"]["total_errors"] == 1
            assert "api_timeout" in report["errors"]["by_type"]

            # Check per-space stats
            assert "TEST" in report["spaces"]
            assert "LARGE" in report["spaces"]
            assert report["spaces"]["TEST"]["pages"] == 2
            assert report["spaces"]["LARGE"]["pages"] == 1

            # Verify Markdown report
            assert md_path.exists()
            with open(md_path, "r") as f:
                md_content = f.read()

            assert "# Assurance Report: Confluence Ingest" in md_content
            assert "test-run-123" in md_content
            assert "## 📊 Summary" in md_content
            assert "## 🔍 Quality Issues" in md_content
            assert "Zero-Body Pages (1)" in md_content
            assert "## 📈 Top 10 Largest Pages" in md_content
            assert "## ❌ Errors" in md_content
            assert "## 🏢 Per-Space Breakdown" in md_content
            assert "## 🔄 Reproduction Command" in md_content

            # Check reproduction command
            assert "trailblazer ingest confluence" in report["repro_command"]
            assert "--body-format atlas_doc_format" in report["repro_command"]


class TestProgressRenderer:
    """Test Rich progress renderer."""

    def test_progress_renderer_init(self):
        """Test progress renderer initialization."""
        renderer = ProgressRenderer(enabled=True, no_color=True)
        assert renderer.enabled is True
        assert renderer.no_color is True
        assert renderer.console is not None

    @patch("sys.stderr")
    def test_progress_banner(self, mock_stderr):
        """Test progress banner output."""
        renderer = ProgressRenderer(enabled=True, no_color=True)

        # Test start banner
        renderer.start_banner(
            run_id="test-123",
            spaces=5,
            since_mode="since 2025-01-01",
            max_pages=100,
            estimated_pages=500,
        )

        # Test finish banner
        space_stats = {
            "TEST1": {
                "pages": 10,
                "attachments": 5,
                "empty_bodies": 1,
                "avg_chars": 1500,
            },
            "TEST2": {
                "pages": 20,
                "attachments": 10,
                "empty_bodies": 0,
                "avg_chars": 2000,
            },
        }
        renderer.finish_banner(
            run_id="test-123", space_stats=space_stats, elapsed=30.5
        )

        # Basic verification that methods don't crash
        assert True

    def test_resumability_evidence(self):
        """Test resumability evidence display."""
        renderer = ProgressRenderer(enabled=True, no_color=True)

        renderer.resumability_evidence(
            since="2025-01-01T00:00:00Z",
            spaces=3,
            pages_known=150,
            estimated_to_fetch=50,
            skipped_unchanged=100,
        )

        # Basic verification that method doesn't crash
        assert True

    def test_heartbeat(self):
        """Test heartbeat display."""
        renderer = ProgressRenderer(enabled=True, no_color=True)

        renderer.heartbeat(
            phase="ingesting",
            processed=75,
            rate=2.5,
            elapsed=30.0,
            eta=12.0,
            last_api_status="200 OK",
            retries=2,
        )

        # Basic verification that method doesn't crash
        assert True

    def test_attachment_verification_error(self):
        """Test attachment verification error display."""
        renderer = ProgressRenderer(enabled=True, no_color=True)

        renderer.attachment_verification_error(
            page_id="123456", expected=5, actual=3
        )

        # Should increment error count
        assert renderer.error_count == 1


class TestGlobalLoggerManagement:
    """Test global event logger management."""

    def test_global_event_logger(self):
        """Test global event logger initialization and cleanup."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "global.ndjson"

            # Initialize global logger
            logger = init_event_logger(log_path, "global-test")
            assert logger.run_id == "global-test"

            # Get global logger
            from trailblazer.core.event_log import get_event_logger

            retrieved_logger = get_event_logger()
            assert retrieved_logger is logger

            # Log an event
            retrieved_logger.space_begin(source="test", space_key="GLOBAL")

            # Close global logger
            from trailblazer.core.event_log import close_event_logger

            close_event_logger()

            # Verify event was written
            assert log_path.exists()
            with open(log_path, "r") as f:
                event = json.loads(f.read().strip())
            assert event["space_key"] == "GLOBAL"
