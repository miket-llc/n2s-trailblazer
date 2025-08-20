"""Test clean-preflight command functionality."""

import json
import shutil
from pathlib import Path
from unittest.mock import patch
import pytest
import tempfile
import os

from trailblazer.cli.main import embed_clean_preflight_cmd


@pytest.fixture
def temp_workspace(tmp_path):
    """Create a temporary workspace with plan_preflight directories."""
    # Change to temp directory
    original_cwd = os.getcwd()
    os.chdir(tmp_path)

    # Create var directory structure
    var_dir = tmp_path / "var"
    var_dir.mkdir()

    yield tmp_path

    # Restore original directory
    os.chdir(original_cwd)


def create_plan_bundle(
    base_dir: Path,
    bundle_name: str,
    is_bad: bool = False,
    bad_reason: str = "quality_gate",
):
    """Create a plan preflight bundle for testing."""
    bundle_dir = base_dir / "var" / bundle_name
    bundle_dir.mkdir(parents=True, exist_ok=True)

    # Create plan_preflight.json
    plan_data = {
        "timestamp": "20250127T120000Z",
        "provider": "openai",
        "model": "text-embedding-3-small",
        "dimension": 1536,
        "ready_runs": 10 if not is_bad else 5,
        "blocked_runs": 2 if not is_bad else 7,
        "total_embeddable_docs": 1000,
        "runs_detail": [],
    }

    if is_bad and bad_reason == "quality_gate":
        # Add runs with QUALITY_GATE reason
        plan_data["runs_detail"] = [
            {"rid": "run1", "status": "READY", "reason": ""},
            {"rid": "run2", "status": "BLOCKED", "reason": "QUALITY_GATE"},
            {
                "rid": "run3",
                "status": "BLOCKED",
                "reason": "MISSING_ENRICH, QUALITY_GATE",
            },
        ]
    elif is_bad and bad_reason == "count_mismatch":
        # Create count mismatch scenario
        plan_data["runs_detail"] = [
            {"rid": "run1", "status": "READY", "reason": ""},
            {"rid": "run2", "status": "BLOCKED", "reason": "MISSING_ENRICH"},
        ]
    else:
        # Good bundle
        plan_data["runs_detail"] = [
            {"rid": "run1", "status": "READY", "reason": ""},
            {"rid": "run2", "status": "READY", "reason": ""},
            {"rid": "run3", "status": "BLOCKED", "reason": "MISSING_ENRICH"},
        ]

    with open(bundle_dir / "plan_preflight.json", "w") as f:
        json.dump(plan_data, f, indent=2)

    # Create ready.txt and blocked.txt
    ready_count = plan_data["ready_runs"]
    blocked_count = plan_data["blocked_runs"]

    if is_bad and bad_reason == "count_mismatch":
        # Intentionally create wrong counts
        ready_count = 15  # Much higher than JSON says
        blocked_count = 1

    with open(bundle_dir / "ready.txt", "w") as f:
        for i in range(ready_count):
            f.write(f"var/runs/ready_run_{i}\n")

    with open(bundle_dir / "blocked.txt", "w") as f:
        for i in range(blocked_count):
            f.write(f"var/runs/blocked_run_{i} # MISSING_ENRICH\n")

    # Create other bundle files
    (bundle_dir / "plan_preflight.csv").write_text(
        "rid,status,reason\nrun1,READY,\n"
    )
    (bundle_dir / "plan_preflight.md").write_text("# Plan Report\n")
    (bundle_dir / "log.out").write_text("Plan completed\n")

    return bundle_dir


def test_clean_preflight_no_bundles(temp_workspace):
    """Test clean-preflight when no bundles exist."""
    with patch("typer.echo") as mock_echo:
        embed_clean_preflight_cmd(dry_run=False)

        # Should report no bundles found
        mock_echo.assert_any_call(
            "ℹ️  No plan_preflight directories found", err=True
        )


def test_clean_preflight_good_bundles_only(temp_workspace):
    """Test clean-preflight with only good bundles."""
    # Create good bundles
    create_plan_bundle(
        temp_workspace, "plan_preflight_20250127T120000Z", is_bad=False
    )
    create_plan_bundle(
        temp_workspace, "plan_preflight_20250127T130000Z", is_bad=False
    )

    with patch("typer.echo") as mock_echo:
        embed_clean_preflight_cmd(dry_run=False)

        # Should report no bad bundles
        mock_echo.assert_any_call(
            "✅ No bad preflight artifacts found", err=True
        )


def test_clean_preflight_bad_bundle_quality_gate(temp_workspace):
    """Test clean-preflight with bad bundle containing QUALITY_GATE."""
    # Create one good and one bad bundle
    good_bundle = create_plan_bundle(
        temp_workspace, "plan_preflight_good", is_bad=False
    )
    bad_bundle = create_plan_bundle(
        temp_workspace,
        "plan_preflight_bad",
        is_bad=True,
        bad_reason="quality_gate",
    )

    with patch("typer.echo") as mock_echo:
        embed_clean_preflight_cmd(dry_run=False)

        # Should report 1 good, 1 bad bundle
        mock_echo.assert_any_call("   Good bundles: 1", err=True)
        mock_echo.assert_any_call("   Bad bundles: 1", err=True)
        mock_echo.assert_any_call(
            "   - plan_preflight_bad: contains_quality_gate", err=True
        )

    # Bad bundle should be archived, good bundle should remain
    assert not bad_bundle.exists()
    assert good_bundle.exists()

    # Archive should exist
    archive_dirs = list(
        (temp_workspace / "var" / "archive" / "bad_plan_preflight").glob("*")
    )
    assert len(archive_dirs) == 1
    archived_bundle = archive_dirs[0] / "plan_preflight_bad"
    assert archived_bundle.exists()
    assert (archived_bundle / "plan_preflight.json").exists()


def test_clean_preflight_bad_bundle_count_mismatch(temp_workspace):
    """Test clean-preflight with bad bundle having count mismatch."""
    bad_bundle = create_plan_bundle(
        temp_workspace,
        "plan_preflight_mismatch",
        is_bad=True,
        bad_reason="count_mismatch",
    )

    with patch("typer.echo") as mock_echo:
        embed_clean_preflight_cmd(dry_run=False)

        # Should detect count mismatch
        mock_echo.assert_any_call("   Bad bundles: 1", err=True)
        # The exact count mismatch message will vary, just check it contains "count_mismatch"
        found_mismatch = False
        for call in mock_echo.call_args_list:
            if len(call[0]) > 0 and "count_mismatch" in str(call[0][0]):
                found_mismatch = True
                break
        assert found_mismatch, "Should have detected count mismatch"

    # Bad bundle should be archived
    assert not bad_bundle.exists()


def test_clean_preflight_missing_plan_json(temp_workspace):
    """Test clean-preflight with bundle missing plan_preflight.json."""
    bundle_dir = temp_workspace / "var" / "plan_preflight_incomplete"
    bundle_dir.mkdir(parents=True)

    # Create only some files, missing plan_preflight.json
    (bundle_dir / "ready.txt").write_text("var/runs/run1\n")
    (bundle_dir / "blocked.txt").write_text("var/runs/run2 # MISSING_ENRICH\n")

    with patch("typer.echo") as mock_echo:
        embed_clean_preflight_cmd(dry_run=False)

        # Should detect missing plan JSON
        mock_echo.assert_any_call(
            "   - plan_preflight_incomplete: missing_plan_preflight_json",
            err=True,
        )

    # Bundle should be archived
    assert not bundle_dir.exists()


def test_clean_preflight_stray_files(temp_workspace):
    """Test clean-preflight with stray plan files at root level."""
    var_dir = temp_workspace / "var"

    # Create stray files
    (var_dir / "plan_legacy.txt").write_text("var/runs/run1\nvar/runs/run2\n")
    (var_dir / "ready_old.txt").write_text("var/runs/run3\n")
    (var_dir / "blocked_old.txt").write_text(
        "var/runs/run4 # MISSING_ENRICH\n"
    )

    with patch("typer.echo") as mock_echo:
        embed_clean_preflight_cmd(dry_run=False)

        # Should detect stray files
        mock_echo.assert_any_call("   Stray files: 3", err=True)
        mock_echo.assert_any_call("   - var/plan_legacy.txt", err=True)

    # Stray files should be archived
    assert not (var_dir / "plan_legacy.txt").exists()
    assert not (var_dir / "ready_old.txt").exists()
    assert not (var_dir / "blocked_old.txt").exists()


def test_clean_preflight_dry_run(temp_workspace):
    """Test clean-preflight dry run mode."""
    bad_bundle = create_plan_bundle(
        temp_workspace,
        "plan_preflight_bad",
        is_bad=True,
        bad_reason="quality_gate",
    )

    with patch("typer.echo") as mock_echo:
        embed_clean_preflight_cmd(dry_run=True)

        # Should report what would be done without doing it
        mock_echo.assert_any_call("   Bad bundles: 1", err=True)
        found_dry_run = False
        for call in mock_echo.call_args_list:
            if len(call[0]) > 0 and "DRY RUN" in str(call[0][0]):
                found_dry_run = True
                break
        assert found_dry_run, "Should have indicated dry run mode"

    # Bad bundle should still exist (not archived in dry run)
    assert bad_bundle.exists()


def test_clean_preflight_creates_report(temp_workspace):
    """Test that clean-preflight creates a cleanup report."""
    bad_bundle = create_plan_bundle(
        temp_workspace,
        "plan_preflight_bad",
        is_bad=True,
        bad_reason="quality_gate",
    )
    var_dir = temp_workspace / "var"
    (var_dir / "stray_plan.txt").write_text("var/runs/run1\n")

    embed_clean_preflight_cmd(dry_run=False)

    # Should create archive directory with report
    archive_dirs = list(
        (temp_workspace / "var" / "archive" / "bad_plan_preflight").glob("*")
    )
    assert len(archive_dirs) == 1

    report_file = archive_dirs[0] / "cleanup_report.json"
    assert report_file.exists()

    # Verify report contents
    with open(report_file) as f:
        report = json.load(f)

    assert report["bad_bundles_archived"] == 1
    assert report["stray_files_archived"] == 1
    assert len(report["bad_bundles"]) == 1
    assert len(report["stray_files"]) == 1
    assert "plan_preflight_bad" in report["bad_bundles"][0]["bundle"]
    assert "contains_quality_gate" in report["bad_bundles"][0]["reasons"]
