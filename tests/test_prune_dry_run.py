"""Test ops prune-runs CLI functionality."""

import json
import time
from pathlib import Path
from unittest.mock import patch
from typer.testing import CliRunner
from trailblazer.cli.main import app


def create_fake_run_dir(runs_dir: Path, run_id: str, age_days: int):
    """Helper to create fake run directory with specific age."""
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Create some fake files
    (run_dir / "ingest" / "confluence.ndjson").parent.mkdir(
        parents=True, exist_ok=True
    )
    (run_dir / "ingest" / "confluence.ndjson").write_text('{"id": "123"}\n')
    (run_dir / "normalize" / "normalized.ndjson").parent.mkdir(
        parents=True, exist_ok=True
    )
    (run_dir / "normalize" / "normalized.ndjson").write_text('{"id": "123"}\n')

    # Set modification time to simulate age
    age_seconds = age_days * 24 * 60 * 60
    target_time = time.time() - age_seconds

    for file_path in run_dir.rglob("*"):
        if file_path.is_file():
            Path(file_path).touch()
            import os

            os.utime(file_path, (target_time, target_time))

    # Set directory times too
    import os

    os.utime(run_dir, (target_time, target_time))

    return run_dir


def test_prune_dry_run_lists_candidates(tmp_path):
    """Test that prune-runs in dry-run mode lists expected candidates."""
    runner = CliRunner()

    # Create fake runs directory
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

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
    state_dir = tmp_path / "state" / "confluence"
    state_dir.mkdir(parents=True, exist_ok=True)

    protected_state = {
        "last_run_id": "run-2025-01-10_0900_old2",  # Protect this old run
        "last_highwater": "2025-01-10T09:00:00Z",
    }
    with open(state_dir / "DEV_state.json", "w") as f:
        json.dump(protected_state, f)

    # Change to temp directory so state/ is found
    import os

    original_cwd = os.getcwd()
    os.chdir(tmp_path)

    try:
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
            assert "Deletion candidates: 2" in result.stdout  # old1 and old3

            # Should list the candidates
            assert "run-2025-01-15_1000_old1" in result.stdout
            assert "run-2025-01-05_0800_old3" in result.stdout

            # Should mention it's a dry run
            assert "This is a dry run" in result.stdout

            # Should NOT mention the protected run as candidate
            assert (
                "run-2025-01-10_0900_old2"
                not in result.stdout.split("Candidates for deletion:")[1]
                if "Candidates for deletion:" in result.stdout
                else True
            )

            # Verify report file was created
            report_files = list(
                Path(tmp_path / "logs").glob("prune_report_*.json")
            )
            assert len(report_files) == 1

            with open(report_files[0]) as f:
                report = json.load(f)

            assert report["dry_run"] is True
            assert report["keep"] == 2
            assert report["min_age_days"] == 30
            assert report["total_runs"] == 5
            assert report["deleted_count"] == 0  # Dry run
            assert len(report["candidates"]) == 2
            assert len(report["protected_runs"]) == 3

            # All original directories should still exist
            assert all(
                (runs_dir / run_id).exists()
                for run_id in [
                    "run-2025-01-20_1400_new1",
                    "run-2025-01-19_1200_new2",
                    "run-2025-01-15_1000_old1",
                    "run-2025-01-10_0900_old2",
                    "run-2025-01-05_0800_old3",
                ]
            )

    finally:
        os.chdir(original_cwd)


def test_prune_no_dry_run_actually_deletes(tmp_path):
    """Test that --no-dry-run actually deletes candidates."""
    runner = CliRunner()

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    # Create some old runs
    create_fake_run_dir(
        runs_dir, "run-2025-01-15_1000_keep1", age_days=5
    )  # New - keep
    create_fake_run_dir(
        runs_dir, "run-2025-01-10_0900_delete1", age_days=45
    )  # Old - delete
    create_fake_run_dir(
        runs_dir, "run-2025-01-05_0800_delete2", age_days=50
    )  # Old - delete

    import os

    original_cwd = os.getcwd()
    os.chdir(tmp_path)

    try:
        with patch("trailblazer.core.artifacts.runs_dir") as mock_runs_dir:
            mock_runs_dir.return_value = runs_dir

            # Run with actual deletion
            result = runner.invoke(
                app,
                [
                    "ops",
                    "prune-runs",
                    "--keep",
                    "1",
                    "--min-age-days",
                    "30",
                    "--no-dry-run",  # Actually delete
                ],
            )

            assert result.exit_code == 0

            # Check output
            assert "Deleting 2 run directories" in result.stdout
            assert "Deleted: run-2025-01-10_0900_delete1" in result.stdout
            assert "Deleted: run-2025-01-05_0800_delete2" in result.stdout

            # Verify deletions actually happened
            assert (runs_dir / "run-2025-01-15_1000_keep1").exists()
            assert not (runs_dir / "run-2025-01-10_0900_delete1").exists()
            assert not (runs_dir / "run-2025-01-05_0800_delete2").exists()

            # Check report shows actual deletions
            report_files = list(
                Path(tmp_path / "logs").glob("prune_report_*.json")
            )
            assert len(report_files) == 1

            with open(report_files[0]) as f:
                report = json.load(f)

            assert report["dry_run"] is False
            assert report["deleted_count"] == 2

    finally:
        os.chdir(original_cwd)


def test_prune_no_candidates(tmp_path):
    """Test prune when no runs qualify for deletion."""
    runner = CliRunner()

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    # Create only new runs
    create_fake_run_dir(runs_dir, "run-2025-01-20_1400_new1", age_days=5)
    create_fake_run_dir(runs_dir, "run-2025-01-19_1200_new2", age_days=10)

    import os

    original_cwd = os.getcwd()
    os.chdir(tmp_path)

    try:
        with patch("trailblazer.core.artifacts.runs_dir") as mock_runs_dir:
            mock_runs_dir.return_value = runs_dir

            result = runner.invoke(
                app,
                ["ops", "prune-runs", "--keep", "1", "--min-age-days", "30"],
            )

            assert result.exit_code == 0
            assert "Deletion candidates: 0" in result.stdout

            # Both runs should still exist
            assert (runs_dir / "run-2025-01-20_1400_new1").exists()
            assert (runs_dir / "run-2025-01-19_1200_new2").exists()

    finally:
        os.chdir(original_cwd)


def test_prune_no_runs_directory(tmp_path):
    """Test prune when no runs directory exists."""
    runner = CliRunner()

    # Don't create runs directory

    with patch("trailblazer.core.artifacts.runs_dir") as mock_runs_dir:
        mock_runs_dir.return_value = tmp_path / "nonexistent"

        result = runner.invoke(
            app, ["ops", "prune-runs", "--keep", "1", "--min-age-days", "30"]
        )

        assert result.exit_code == 0
        assert "No runs directory found" in result.stdout


def test_prune_protected_by_multiple_state_files(tmp_path):
    """Test that runs referenced in multiple state files are protected."""
    runner = CliRunner()

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    # Create runs
    create_fake_run_dir(runs_dir, "run-old-protected", age_days=60)
    create_fake_run_dir(runs_dir, "run-old-unprotected", age_days=55)

    # Create multiple state files referencing the first run
    state_dir = tmp_path / "state" / "confluence"
    state_dir.mkdir(parents=True, exist_ok=True)

    for space in ["DEV", "PROD"]:
        state_data = {
            "last_run_id": "run-old-protected",
            "last_highwater": "2025-01-01T00:00:00Z",
        }
        with open(state_dir / f"{space}_state.json", "w") as f:
            json.dump(state_data, f)

    import os

    original_cwd = os.getcwd()
    os.chdir(tmp_path)

    try:
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

    finally:
        os.chdir(original_cwd)
