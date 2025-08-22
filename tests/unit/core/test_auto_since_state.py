# Test constants for magic numbers
EXPECTED_COUNT_2 = 2
EXPECTED_COUNT_3 = 3
EXPECTED_COUNT_4 = 4

"""Tests for auto-since functionality."""

import json
import os
from unittest.mock import patch

import pytest

from trailblazer.pipeline.steps.ingest.confluence import ingest_confluence

# Mark all tests as unit tests (no database needed)
pytestmark = pytest.mark.unit


def test_auto_since_reads_and_updates_state(tmp_path):
    """Test that auto-since reads existing state and updates with new highwater."""
    # Setup state directory and file
    state_dir = tmp_path / "var" / "state" / "confluence"
    state_dir.mkdir(parents=True, exist_ok=True)

    state_file = state_dir / "DEV_state.json"
    initial_state = {
        "last_highwater": "2025-01-01T12:00:00Z",
        "last_run_id": "previous-run-abc123",
        "updated_at": "2025-01-01T13:00:00Z",
    }
    with open(state_file, "w") as f:
        json.dump(initial_state, f)

    # Patch the paths to use our temp directory
    with (
        patch("trailblazer.core.paths.ROOT", tmp_path),
        patch("trailblazer.pipeline.steps.ingest.confluence.ConfluenceClient") as mock_client_class,
    ):
        mock_client = mock_client_class.return_value
        mock_client.site_base = "https://example.com"

        # Mock confluence API
        def mock_search_cql(cql, start=0, limit=50):
            # Should be called with the timestamp from state file
            assert "2025-01-01T12:00:00Z" in cql
            return {"results": [{"id": "123"}, {"id": "456"}]}

        mock_client.search_cql.side_effect = mock_search_cql

        # Mock page retrieval
        def mock_get_page_by_id(page_id, body_format="storage"):
            if page_id == "123":
                return {
                    "id": "123",
                    "title": "Updated Page 1",
                    "spaceId": "1001",
                    "version": {
                        "number": 10,
                        "createdAt": "2025-01-15T14:30:00Z",
                    },  # Newer
                    "createdAt": "2025-01-01T10:00:00Z",
                    "body": {"storage": {"value": "<p>Updated content</p>"}},
                    "_links": {"webui": "/page1"},
                }
            elif page_id == "456":
                return {
                    "id": "456",
                    "title": "Updated Page 2",
                    "spaceId": "1001",
                    "version": {
                        "number": 8,
                        "createdAt": "2025-01-20T09:15:00Z",
                    },  # Even newer
                    "createdAt": "2025-01-02T15:30:00Z",
                    "body": {"storage": {"value": "<p>More updates</p>"}},
                    "_links": {"webui": "/page2"},
                }
            return {}

        mock_client.get_page_by_id.side_effect = mock_get_page_by_id
        mock_client.get_attachments_for_page.return_value = iter([])  # No attachments

        # Mock spaces resolution
        mock_client.get_spaces.return_value = iter([{"id": "1001", "key": "DEV"}])

        # Run ingest with auto-since
        outdir = str(tmp_path / "ingest")
        metrics = ingest_confluence(
            outdir=outdir,
            space_keys=["DEV"],
            space_ids=None,
            since=None,  # No explicit since
            auto_since=True,  # Enable auto-since
            body_format="storage",
            max_pages=None,
            progress=False,
            progress_every=1,
            run_id="test-auto-since-run",
        )

        # Verify processing happened
        assert metrics["pages"] == 2

        # Check that state file was updated with new highwater mark
        with open(state_file) as f:
            updated_state = json.load(f)

        # Should have the latest timestamp (2025-01-20T09:15:00Z)
        assert updated_state["last_highwater"] == "2025-01-20T09:15:00Z"
        assert updated_state["last_run_id"] == "test-auto-since-run"
        assert "updated_at" in updated_state


def test_auto_since_warns_on_missing_state(tmp_path):
    """Test that auto-since warns when state file doesn't exist."""
    # Change to temp directory (no state files exist)
    original_cwd = os.getcwd()
    os.chdir(tmp_path)

    try:
        with (
            patch("trailblazer.pipeline.steps.ingest.confluence.ConfluenceClient") as mock_client_class,
            patch("trailblazer.pipeline.steps.ingest.confluence.log") as mock_log,
        ):
            mock_client = mock_client_class.return_value
            mock_client.site_base = "https://example.com"
            mock_client.get_spaces.return_value = iter([{"id": "1001", "key": "DEV"}])
            mock_client.get_pages.return_value = iter([])  # No pages

            # Run with auto-since but no state file
            outdir = str(tmp_path / "ingest")
            ingest_confluence(
                outdir=outdir,
                space_keys=["DEV"],
                space_ids=None,
                since=None,
                auto_since=True,
                body_format="storage",
                max_pages=None,
                progress=False,
                progress_every=1,
                run_id="test-missing-state",
            )

            # Should have logged warning
            mock_log.warning.assert_called()
            warning_call = mock_log.warning.call_args
            assert "auto_since.missing_state" in warning_call[0][0]
            assert warning_call[1]["space"] == "DEV"

    finally:
        os.chdir(original_cwd)


def test_auto_since_no_op_without_spaces(tmp_path):
    """Test that auto-since is no-op when no spaces specified."""

    with patch("trailblazer.pipeline.steps.ingest.confluence.ConfluenceClient") as mock_client_class:
        mock_client = mock_client_class.return_value
        mock_client.site_base = "https://example.com"
        mock_client.get_pages.return_value = iter([])

        outdir = str(tmp_path / "ingest")
        metrics = ingest_confluence(
            outdir=outdir,
            space_keys=None,  # No spaces
            space_ids=None,
            since=None,
            auto_since=True,  # Should be ignored
            body_format="storage",
            max_pages=None,
            progress=False,
            progress_every=1,
            run_id="test-no-spaces",
        )

        # Should complete without error, no state operations
        assert metrics["pages"] == 0
        assert metrics["spaces"] == 0
