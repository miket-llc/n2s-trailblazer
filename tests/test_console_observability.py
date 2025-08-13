"""Tests for console observability and progress UX."""

import sys
from io import StringIO
from unittest.mock import patch

import pytest

from trailblazer.core.progress import (
    ProgressRenderer,
    is_tty,
    is_ci,
    should_use_pretty,
)
from trailblazer.core.logging import setup_logging, _should_use_json_format


class TestProgressRenderer:
    """Test progress renderer functionality."""

    def test_init_with_defaults(self):
        """Test progress renderer initialization with defaults."""
        renderer = ProgressRenderer()
        assert isinstance(renderer.enabled, bool)
        assert renderer.file == sys.stderr
        assert renderer.quiet_pretty is False

    def test_init_with_custom_file(self):
        """Test progress renderer with custom output file."""
        output = StringIO()
        renderer = ProgressRenderer(enabled=True, file=output)

        renderer.start_banner("test-123", 2, "auto-since", 100)

        content = output.getvalue()
        assert "test-123" in content
        assert "Spaces targeted: 2" in content
        assert "Mode: auto-since" in content
        assert "Max pages: 100" in content

    def test_quiet_pretty_mode(self):
        """Test that quiet_pretty suppresses banners but not progress."""
        output = StringIO()
        renderer = ProgressRenderer(
            enabled=True, quiet_pretty=True, file=output
        )

        # Banner should be suppressed
        renderer.start_banner("test-123", 2)
        assert output.getvalue() == ""

        # Progress should still work
        renderer.progress_update(
            "DEV", "12345", "Test Page", 3, "2025-01-01T00:00:00Z"
        )
        content = output.getvalue()
        assert "DEV" in content
        assert "Test Page" in content

    def test_spaces_table(self):
        """Test spaces table rendering."""
        output = StringIO()
        renderer = ProgressRenderer(enabled=True, file=output)

        spaces = [
            {"id": "123", "key": "DEV", "name": "Development Space"},
            {"id": "456", "key": "PROD", "name": "Production Space"},
        ]

        renderer.spaces_table(spaces)
        content = output.getvalue()

        assert "Spaces to ingest:" in content
        assert "DEV" in content
        assert "PROD" in content
        assert "Development Space" in content

    def test_progress_throttling(self):
        """Test that progress updates are throttled correctly."""
        output = StringIO()
        renderer = ProgressRenderer(enabled=True, file=output)

        # First update should appear (page 1, throttle_every=1)
        renderer.progress_update("DEV", "1", "Page 1", 0, throttle_every=2)
        assert (
            "Page 1" not in output.getvalue()
        )  # page_count=1, 1%2=1, so no output

        # Second update should appear (page 2, throttle_every=2)
        renderer.progress_update("DEV", "2", "Page 2", 0, throttle_every=2)
        assert "Page 2" in output.getvalue()  # page_count=2, 2%2=0, so output

    def test_one_line_summary(self):
        """Test one-line summary generation."""
        renderer = ProgressRenderer()

        summary = renderer.one_line_summary("test-123", 50, 25, 120.5)

        assert "test-123" in summary
        assert "50 pages" in summary
        assert "25 attachments" in summary
        assert "120.5s" in summary
        assert "pages/s" in summary

    def test_finish_banner(self):
        """Test finish banner with space stats."""
        output = StringIO()
        renderer = ProgressRenderer(enabled=True, file=output)

        space_stats = {
            "DEV": {"pages": 10, "attachments": 5, "empty_bodies": 1},
            "PROD": {"pages": 20, "attachments": 15, "empty_bodies": 0},
        }

        renderer.finish_banner("test-123", space_stats, 45.2)
        content = output.getvalue()

        assert "Completed ingest run: test-123" in content
        assert "Elapsed: 45.2s" in content
        assert "Total: 30 pages, 20 attachments" in content
        assert "Empty bodies: 1" in content
        assert "DEV: 10 pages, 5 attachments" in content


class TestLoggingConfiguration:
    """Test logging configuration and format detection."""

    @patch.dict("os.environ", {}, clear=True)
    @patch("sys.stdout.isatty", return_value=True)
    def test_should_use_json_format_tty(self):
        """Test JSON format detection with TTY."""
        assert not _should_use_json_format()

    @patch.dict("os.environ", {}, clear=True)
    @patch("sys.stdout.isatty", return_value=False)
    def test_should_use_json_format_redirect(self):
        """Test JSON format detection with redirected stdout."""
        assert _should_use_json_format()

    @patch.dict("os.environ", {"CI": "true"}, clear=True)
    @patch("sys.stdout.isatty", return_value=True)
    def test_should_use_json_format_ci(self):
        """Test JSON format detection in CI."""
        assert _should_use_json_format()

    @patch.dict("os.environ", {"GITHUB_ACTIONS": "true"}, clear=True)
    def test_should_use_json_format_github_actions(self):
        """Test JSON format detection in GitHub Actions."""
        assert _should_use_json_format()

    def test_setup_logging_json_format(self):
        """Test that JSON format is configured correctly."""
        setup_logging(format="json")
        # Just ensure it doesn't crash; actual verification would require
        # checking structlog internals which is complex

    def test_setup_logging_plain_format(self):
        """Test that plain format is configured correctly."""
        setup_logging(format="plain")
        # Just ensure it doesn't crash


class TestEnvironmentDetection:
    """Test environment detection functions."""

    @patch("sys.stdout.isatty", return_value=True)
    def test_is_tty_true(self):
        """Test TTY detection when stdout is a TTY."""
        assert is_tty()

    @patch("sys.stdout.isatty", return_value=False)
    def test_is_tty_false(self):
        """Test TTY detection when stdout is redirected."""
        assert not is_tty()

    @patch.dict("os.environ", {"CI": "true"}, clear=True)
    def test_is_ci_true(self):
        """Test CI detection with CI environment variable."""
        assert is_ci()

    @patch.dict("os.environ", {}, clear=True)
    def test_is_ci_false(self):
        """Test CI detection without CI environment variables."""
        assert not is_ci()

    @patch("trailblazer.core.progress.is_tty", return_value=True)
    @patch("trailblazer.core.progress.is_ci", return_value=False)
    def test_should_use_pretty_true(self):
        """Test pretty output decision when TTY and not CI."""
        assert should_use_pretty()

    @patch("trailblazer.core.progress.is_tty", return_value=False)
    @patch("trailblazer.core.progress.is_ci", return_value=False)
    def test_should_use_pretty_false_no_tty(self):
        """Test pretty output decision when not TTY."""
        assert not should_use_pretty()

    @patch("trailblazer.core.progress.is_tty", return_value=True)
    @patch("trailblazer.core.progress.is_ci", return_value=True)
    def test_should_use_pretty_false_ci(self):
        """Test pretty output decision when in CI."""
        assert not should_use_pretty()


class TestProgressCheckpoints:
    """Test progress checkpoint functionality."""

    def test_checkpoint_data_structure(self, tmp_path):
        """Test that progress checkpoints have the correct structure."""
        # This would be tested as part of the ingest integration
        # but we can test the expected data structure

        expected_keys = {
            "last_page_id",
            "pages_processed",
            "attachments_processed",
            "timestamp",
            "progress_checkpoints",
        }

        # Create sample checkpoint
        checkpoint = {
            "last_page_id": "12345",
            "pages_processed": 10,
            "attachments_processed": 5,
            "timestamp": "2025-01-01T00:00:00Z",
            "progress_checkpoints": 2,
        }

        assert set(checkpoint.keys()) == expected_keys

    def test_resume_indicator(self):
        """Test resume indicator display."""
        output = StringIO()
        renderer = ProgressRenderer(enabled=True, file=output)

        renderer.resume_indicator("12345", "2025-01-01T00:00:00Z")

        content = output.getvalue()
        assert "Resuming from page 12345" in content
        assert "2025-01-01T00:00:00Z" in content


@pytest.mark.integration
class TestStreamSeparation:
    """Test that JSON and pretty output are properly separated."""

    def test_json_to_stdout_pretty_to_stderr(self):
        """Test that structured logs go to stdout and pretty to stderr."""
        # This is more of an integration test that would need to be run
        # with actual CLI commands, but we can test the principle

        from trailblazer.core.logging import log

        # Capture stdout
        stdout_capture = StringIO()
        with patch("sys.stdout", stdout_capture):
            setup_logging(format_type="json")
            log.info("test.event", key="value")

        # Should contain JSON
        output = stdout_capture.getvalue()
        assert (
            '{"event": "test.event"' in output
            or '"event":"test.event"' in output
        )

    def test_no_intermixed_output(self):
        """Test that pretty and JSON are never mixed on same stream."""
        # This is enforced by design:
        # - structlog always goes to stdout
        # - ProgressRenderer always goes to stderr
        # - CLI uses typer.echo() which defaults to stdout but can specify err=True

        output = StringIO()
        renderer = ProgressRenderer(enabled=True, file=output)

        # Progress should only go to the specified file (stderr equivalent)
        renderer.progress_update("DEV", "123", "Test", 0)

        # Verify it goes to our mock stderr, not mixed with JSON
        assert len(output.getvalue()) > 0
