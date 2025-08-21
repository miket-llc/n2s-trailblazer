"""Test diff-deletions CLI functionality."""

import json
import pytest
from unittest.mock import patch
from typer.testing import CliRunner
from trailblazer.cli.main import app

# Mark all tests as unit tests (no database needed)
pytestmark = pytest.mark.unit


def test_diff_deletions_finds_correct_deletions(tmp_path):
    """Test that diff-deletions correctly identifies deleted page IDs."""
    runner = CliRunner()

    # Setup fake runs directory structure
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    # Baseline run with more pages
    baseline_run = "run-2025-01-01_1200_abc1"
    baseline_ingest_dir = runs_dir / baseline_run / "ingest"
    baseline_ingest_dir.mkdir(parents=True)

    baseline_seen_ids = ["123", "456", "789", "999"]  # 4 pages
    baseline_file = baseline_ingest_dir / "DEV_seen_page_ids.json"
    with open(baseline_file, "w") as f:
        json.dump(baseline_seen_ids, f)

    # Current run with fewer pages (some deleted)
    current_run = "run-2025-01-15_1400_def2"
    current_ingest_dir = runs_dir / current_run / "ingest"
    current_ingest_dir.mkdir(parents=True)

    current_seen_ids = ["123", "789"]  # 2 pages (456 and 999 deleted)
    current_file = current_ingest_dir / "DEV_seen_page_ids.json"
    with open(current_file, "w") as f:
        json.dump(current_seen_ids, f)

    # Mock runs_dir to return our temp directory
    with patch("trailblazer.core.artifacts.runs_dir") as mock_runs_dir:
        mock_runs_dir.return_value = runs_dir

        # Run diff-deletions command
        result = runner.invoke(
            app,
            [
                "ingest",
                "diff-deletions",
                "--space",
                "DEV",
                "--baseline-run",
                baseline_run,
                "--current-run",
                current_run,
            ],
        )

        # Check success
        assert result.exit_code == 0

        # Check output
        assert "Found 2 deleted pages" in result.stdout
        assert "space 'DEV'" in result.stdout

        # Check deleted_ids.json was written to current run
        deleted_file = current_ingest_dir / "deleted_ids.json"
        assert deleted_file.exists()

        with open(deleted_file) as f:
            deleted_ids = json.load(f)

        # Should be sorted list of IDs in baseline but not current
        assert deleted_ids == ["456", "999"]


def test_diff_deletions_no_deletions(tmp_path):
    """Test diff-deletions when no pages were deleted."""
    runner = CliRunner()

    # Setup runs with same page IDs
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    baseline_run = "run-2025-01-01_1200_abc1"
    baseline_ingest_dir = runs_dir / baseline_run / "ingest"
    baseline_ingest_dir.mkdir(parents=True)

    current_run = "run-2025-01-15_1400_def2"
    current_ingest_dir = runs_dir / current_run / "ingest"
    current_ingest_dir.mkdir(parents=True)

    same_ids = ["123", "456", "789"]

    # Both runs have same page IDs
    for run_dir, filename in [
        (baseline_ingest_dir, "DEV_seen_page_ids.json"),
        (current_ingest_dir, "DEV_seen_page_ids.json"),
    ]:
        with open(run_dir / filename, "w") as f:
            json.dump(same_ids, f)

    with patch("trailblazer.core.artifacts.runs_dir") as mock_runs_dir:
        mock_runs_dir.return_value = runs_dir

        result = runner.invoke(
            app,
            [
                "ingest",
                "diff-deletions",
                "--space",
                "DEV",
                "--baseline-run",
                baseline_run,
                "--current-run",
                current_run,
            ],
        )

        assert result.exit_code == 0
        assert "Found 0 deleted pages" in result.stdout

        # Empty deletions file should still be created
        deleted_file = current_ingest_dir / "deleted_ids.json"
        assert deleted_file.exists()

        with open(deleted_file) as f:
            deleted_ids = json.load(f)
        assert deleted_ids == []


def test_diff_deletions_missing_baseline_file(tmp_path):
    """Test error handling when baseline file doesn't exist."""
    runner = CliRunner()

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    # Only create current run (baseline missing)
    current_run = "run-2025-01-15_1400_def2"
    current_ingest_dir = runs_dir / current_run / "ingest"
    current_ingest_dir.mkdir(parents=True)

    current_file = current_ingest_dir / "DEV_seen_page_ids.json"
    with open(current_file, "w") as f:
        json.dump(["123"], f)

    with patch("trailblazer.core.artifacts.runs_dir") as mock_runs_dir:
        mock_runs_dir.return_value = runs_dir

        result = runner.invoke(
            app,
            [
                "ingest",
                "diff-deletions",
                "--space",
                "DEV",
                "--baseline-run",
                "nonexistent-run",
                "--current-run",
                current_run,
            ],
        )

        assert result.exit_code == 1
        assert (
            "Baseline file not found" in result.stdout
            or "Baseline file not found" in result.stderr
        )


def test_diff_deletions_missing_current_file(tmp_path):
    """Test error handling when current file doesn't exist."""
    runner = CliRunner()

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    # Only create baseline run (current missing)
    baseline_run = "run-2025-01-01_1200_abc1"
    baseline_ingest_dir = runs_dir / baseline_run / "ingest"
    baseline_ingest_dir.mkdir(parents=True)

    baseline_file = baseline_ingest_dir / "DEV_seen_page_ids.json"
    with open(baseline_file, "w") as f:
        json.dump(["123"], f)

    with patch("trailblazer.core.artifacts.runs_dir") as mock_runs_dir:
        mock_runs_dir.return_value = runs_dir

        result = runner.invoke(
            app,
            [
                "ingest",
                "diff-deletions",
                "--space",
                "DEV",
                "--baseline-run",
                baseline_run,
                "--current-run",
                "nonexistent-run",
            ],
        )

        assert result.exit_code == 1
        assert (
            "Current file not found" in result.stdout
            or "Current file not found" in result.stderr
        )


def test_diff_deletions_additions_only(tmp_path):
    """Test when current run has more pages than baseline (additions, no deletions)."""
    runner = CliRunner()

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    baseline_run = "run-2025-01-01_1200_abc1"
    baseline_ingest_dir = runs_dir / baseline_run / "ingest"
    baseline_ingest_dir.mkdir(parents=True)

    current_run = "run-2025-01-15_1400_def2"
    current_ingest_dir = runs_dir / current_run / "ingest"
    current_ingest_dir.mkdir(parents=True)

    # Baseline has fewer pages
    baseline_ids = ["123", "456"]
    baseline_file = baseline_ingest_dir / "DEV_seen_page_ids.json"
    with open(baseline_file, "w") as f:
        json.dump(baseline_ids, f)

    # Current has more pages (additions)
    current_ids = ["123", "456", "789", "999"]  # Added 789, 999
    current_file = current_ingest_dir / "DEV_seen_page_ids.json"
    with open(current_file, "w") as f:
        json.dump(current_ids, f)

    with patch("trailblazer.core.artifacts.runs_dir") as mock_runs_dir:
        mock_runs_dir.return_value = runs_dir

        result = runner.invoke(
            app,
            [
                "ingest",
                "diff-deletions",
                "--space",
                "DEV",
                "--baseline-run",
                baseline_run,
                "--current-run",
                current_run,
            ],
        )

        assert result.exit_code == 0
        assert "Found 0 deleted pages" in result.stdout

        # No deletions
        deleted_file = current_ingest_dir / "deleted_ids.json"
        assert deleted_file.exists()

        with open(deleted_file) as f:
            deleted_ids = json.load(f)
        assert deleted_ids == []
