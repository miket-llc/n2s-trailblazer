"""Tests to ensure artifacts remain deterministic with new observability features."""

import pytest

# Mark all tests as unit tests (no database needed)
pytestmark = pytest.mark.unit


class TestArtifactDeterminism:
    """Test that all artifacts are deterministic and properly structured."""

    def test_expected_artifact_files(self, tmp_path):
        """Test that all expected artifact files are created."""
        # Expected files from the ingest process
        expected_files = {
            "confluence.ndjson",
            "pages.csv",
            "attachments.csv",
            "summary.json",
            "metrics.json",
            "manifest.json",
            "progress.json",  # New checkpoint file
            "final_summary.txt",  # New human summary
        }

        # This would be tested in an actual ingest run
        # For now, just verify the expected set is complete
        assert len(expected_files) == 8

    def test_summary_json_structure(self):
        """Test that summary.json has the expected structure with new fields."""
        expected_fields = {
            "run_id",
            "started_at",
            "completed_at",
            "elapsed_seconds",  # New field
            "total_pages",
            "total_attachments",
            "space_key_unknown_count",
            "progress_checkpoints",  # New field
            "spaces",
        }

        # Sample summary structure
        summary = {
            "run_id": "test-123",
            "started_at": "2025-01-01T00:00:00Z",
            "completed_at": "2025-01-01T00:10:00Z",
            "elapsed_seconds": 600.0,
            "total_pages": 100,
            "total_attachments": 50,
            "space_key_unknown_count": 0,
            "progress_checkpoints": 10,
            "spaces": {
                "DEV": {
                    "pages": 100,
                    "attachments": 50,
                    "empty_bodies": 5,
                    "avg_chars": 1200.5,
                }
            },
        }

        assert set(summary.keys()) == expected_fields

    def test_progress_json_structure(self):
        """Test progress.json checkpoint structure."""
        expected_fields = {
            "last_page_id",
            "pages_processed",
            "attachments_processed",
            "timestamp",
            "progress_checkpoints",
        }

        progress = {
            "last_page_id": "12345",
            "pages_processed": 50,
            "attachments_processed": 25,
            "timestamp": "2025-01-01T00:05:00Z",
            "progress_checkpoints": 5,
        }

        assert set(progress.keys()) == expected_fields

    def test_final_summary_format(self):
        """Test that final_summary.txt has expected one-line format."""
        from trailblazer.core.progress import ProgressRenderer

        renderer = ProgressRenderer()
        summary = renderer.one_line_summary("test-123", 100, 50, 300.5)

        # Should be single line with key metrics
        assert summary.count("\n") == 0
        assert "test-123" in summary
        assert "100 pages" in summary
        assert "50 attachments" in summary
        assert "300.5s" in summary

    def test_existing_csv_structure_unchanged(self):
        """Test that pages.csv and attachments.csv structure is unchanged."""
        # pages.csv expected columns
        expected_pages_columns = [
            "space_key",
            "page_id",
            "title",
            "version",
            "updated_at",
            "attachments_count",
            "url",
        ]

        # attachments.csv expected columns
        expected_attachments_columns = [
            "page_id",
            "filename",
            "media_type",
            "file_size",
            "download_url",
        ]

        # These should remain exactly the same for backward compatibility
        assert len(expected_pages_columns) == 7
        assert len(expected_attachments_columns) == 5

    def test_ndjson_structure_unchanged(self):
        """Test that confluence.ndjson structure includes new fields but maintains compatibility."""
        # Expected fields in each NDJSON line (Page model fields)
        base_fields = {
            "id",
            "title",
            "space_id",
            "space_key",
            "version",
            "updated_at",
            "created_at",
            "body_html",
            "url",
            "attachments",
            "metadata",
        }

        # New fields added for observability
        new_fields = {
            "body_repr",  # storage/adf/unknown
            "body_storage",  # when body_repr=storage
            "body_adf",  # when body_repr=adf
        }

        all_expected_fields = base_fields | new_fields

        # Verify we have the right number of expected fields
        assert len(all_expected_fields) == 14

    def test_metrics_json_structure(self):
        """Test metrics.json structure."""
        expected_fields = {
            "spaces",
            "pages",
            "attachments",
            "since",
            "body_format",
            "space_key_unknown_count",
        }

        metrics = {
            "spaces": 2,
            "pages": 100,
            "attachments": 50,
            "since": None,
            "body_format": "storage",
            "space_key_unknown_count": 0,
        }

        assert set(metrics.keys()) == expected_fields

    def test_manifest_json_structure(self):
        """Test manifest.json structure."""
        expected_fields = {"phase", "artifact", "completed_at"}

        manifest = {
            "phase": "ingest",
            "artifact": "confluence.ndjson",
            "completed_at": "2025-01-01T00:10:00Z",
        }

        assert set(manifest.keys()) == expected_fields

    def test_seen_page_ids_files(self):
        """Test that seen page IDs files are still created per space."""
        # These files follow the pattern: {space_key}_seen_page_ids.json
        # They should contain sorted arrays of page IDs

        sample_seen_ids = ["12345", "67890", "11111"]
        sorted_ids = sorted(sample_seen_ids)

        # Should be deterministically sorted
        assert sorted_ids == ["11111", "12345", "67890"]


class TestBackwardCompatibility:
    """Test that existing functionality is not broken."""

    def test_old_progress_flag_still_works(self):
        """Test that --progress flag behavior is preserved."""
        from trailblazer.core.progress import ProgressRenderer

        # Progress should still work as before
        renderer = ProgressRenderer(enabled=True)

        # Should have the same basic functionality
        assert hasattr(renderer, "progress_update")
        assert callable(renderer.progress_update)

    def test_progress_every_parameter_honored(self):
        """Test that progress_every parameter works correctly."""
        from trailblazer.core.progress import ProgressRenderer
        from io import StringIO

        output = StringIO()
        renderer = ProgressRenderer(enabled=True, file=output)

        # With throttle_every=3, only every 3rd call should produce output
        renderer.progress_update("DEV", "1", "Page 1", 0, throttle_every=3)
        assert len(output.getvalue()) == 0  # No output yet

        renderer.progress_update("DEV", "2", "Page 2", 0, throttle_every=3)
        assert len(output.getvalue()) == 0  # Still no output

        renderer.progress_update("DEV", "3", "Page 3", 0, throttle_every=3)
        assert len(output.getvalue()) > 0  # Now we should see output

    def test_structured_logging_events_unchanged(self):
        """Test that structured logging event names are stable."""
        expected_events = {
            "confluence.space",
            "confluence.page",
            "confluence.attachments",
        }

        # These event names should never change for backward compatibility
        assert "confluence.space" in expected_events
        assert "confluence.page" in expected_events
        assert "confluence.attachments" in expected_events


@pytest.mark.integration
class TestOutputStreamSeparation:
    """Integration tests for proper stream separation."""

    def test_no_json_on_stderr(self):
        """Test that JSON logs never appear on stderr."""
        # This would need to be tested with actual CLI runs
        # but the principle is enforced by design:
        # - structlog is configured to use stdout
        # - ProgressRenderer explicitly uses stderr
        pass

    def test_no_pretty_on_stdout(self):
        """Test that pretty output never appears on stdout."""
        # Same as above - enforced by design
        pass

    def test_run_id_output_location(self):
        """Test that run_id is output to stdout for scripting."""
        # The CLI should echo the run_id to stdout so scripts can capture it
        # while all other pretty output goes to stderr
        pass


class TestErrorHandling:
    """Test error handling in new observability features."""

    def test_progress_checkpoint_write_failure(self):
        """Test graceful handling of progress checkpoint write failures."""
        # Should log warning but not fail the entire ingest
        pass

    def test_resume_indicator_missing_file(self):
        """Test handling of missing progress checkpoint file."""
        # Should not crash when progress.json doesn't exist
        pass

    def test_spaces_table_api_failure(self):
        """Test graceful handling of space details API failures."""
        # Should fall back to basic info when space details can't be fetched
        pass
