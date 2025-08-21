"""Tests for the ops prune-runs command in dry-run mode."""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from trailblazer.cli.main import app


def create_fake_run_dir(runs_dir: Path, run_name: str, age_days: int):
    """Create a fake run directory with specified age."""
    run_dir = runs_dir / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    # Create some fake content
    (run_dir / "ingest").mkdir(exist_ok=True)
    (run_dir / "ingest" / "summary.json").write_text(
        json.dumps({"pages": 10, "attachments": 5})
    )

    # Set modification time to simulate age
    age_timestamp = (datetime.now() - timedelta(days=age_days)).timestamp()
    os.utime(run_dir, (age_timestamp, age_timestamp))


def test_prune_dry_run_lists_candidates(tmp_path):
    """Test that prune-runs in dry-run mode lists expected candidates."""
    runner = CliRunner()

    # Create fake runs directory
    runs_dir = tmp_path / "var" / "runs"
    runs_dir.mkdir(parents=True)

    # Create runs of different ages (newest first by name)
    create_fake_run_dir(
        runs_dir, "run-2025-01-20_1400_new1", age_days=5
    )  # New - should be kept
    create_fake_run_dir(
        runs_dir, "run-2025-01-19_1200_new2", age_days=10
    )  # New - should be kept
    create_fake_run_dir(
        runs_dir, "run-2025-01-15_1000_old1", age_days=45
    )  # Old - candidate
    create_fake_run_dir(
        runs_dir, "run-2025-01-10_0900_old2", age_days=50
    )  # Old - candidate
    create_fake_run_dir(
        runs_dir, "run-2025-01-05_0800_old3", age_days=60
    )  # Old - candidate

    # Create fake state file referencing one old run (should protect it)
    state_dir = tmp_path / "var" / "state" / "confluence"
    state_dir.mkdir(parents=True, exist_ok=True)

    protected_state = {
        "last_run_id": "run-2025-01-10_0900_old2",  # Protect this old run
        "last_highwater": "2025-01-10T09:00:00Z",
    }
    with open(state_dir / "DEV_state.json", "w") as f:
        json.dump(protected_state, f)

    # Patch paths to use temp directory
    with patch("trailblazer.core.paths.ROOT", tmp_path):
        with patch("trailblazer.core.artifacts.runs_dir") as mock_runs_dir:
            mock_runs_dir.return_value = runs_dir

            # Run prune command (dry-run by default)
            result = runner.invoke(
                app,
                [
                    "ops",
                    "prune-runs",
                    "--keep",
                    "2",  # Keep 2 newest
                    "--min-age-days",
                    "30",  # Only delete if older than 30 days
                ],
            )

            assert result.exit_code == 0

            # Check output
            assert "Total runs: 5" in result.stdout
            assert (
                "Protected runs: 3" in result.stdout
            )  # 2 newest + 1 referenced
            assert "Deletion candidates: 2" in result.stdout

            # Should show the specific candidates (not the protected one)
            assert "run-2025-01-15_1000_old1" in result.stdout
            assert "run-2025-01-05_0800_old3" in result.stdout

            # Protected run should NOT be in candidates list
            candidates_section = result.stdout.split(
                "Candidates for deletion:"
            )[1].split("💡")[0]
            assert "run-2025-01-10_0900_old2" not in candidates_section

            # Should mention dry-run mode
            assert "dry run" in result.stdout
            assert "no-dry-run" in result.stdout

            # Check that report file was created
            assert "Report written to:" in result.stdout


def test_prune_protected_by_multiple_state_files(tmp_path):
    """Test that runs referenced in multiple state files are protected."""
    runner = CliRunner()

    runs_dir = tmp_path / "var" / "runs"
    runs_dir.mkdir(parents=True)

    # Create runs
    create_fake_run_dir(runs_dir, "run-old-protected", age_days=60)
    create_fake_run_dir(runs_dir, "run-old-unprotected", age_days=55)

    # Create multiple state files referencing the first run
    state_dir = tmp_path / "var" / "state" / "confluence"
    state_dir.mkdir(parents=True, exist_ok=True)

    for space in ["DEV", "PROD"]:
        state_data = {
            "last_run_id": "run-old-protected",
            "last_highwater": "2025-01-01T00:00:00Z",
        }
        with open(state_dir / f"{space}_state.json", "w") as f:
            json.dump(state_data, f)

    with patch("trailblazer.core.paths.ROOT", tmp_path):
        with patch("trailblazer.core.artifacts.runs_dir") as mock_runs_dir:
            mock_runs_dir.return_value = runs_dir

            result = runner.invoke(
                app,
                [
                    "ops",
                    "prune-runs",
                    "--keep",
                    "0",  # Don't protect any by age
                    "--min-age-days",
                    "30",
                ],
            )

            assert result.exit_code == 0

            # Only 1 candidate (unprotected), even though both are old
            assert "Deletion candidates: 1" in result.stdout
            assert "run-old-unprotected" in result.stdout
