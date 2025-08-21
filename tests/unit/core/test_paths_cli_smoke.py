"""Smoke tests for paths CLI functionality."""

import json
import subprocess
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch

# Mark all tests as unit tests (no database needed)
pytestmark = pytest.mark.unit


def test_paths_show_command():
    """Test that 'trailblazer paths show' works."""
    result = subprocess.run(
        ["python", "-m", "trailblazer.cli.main", "paths", "show"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    output = result.stdout

    # Check that expected output is present
    assert "📁 Workspace Paths" in output
    assert "Data (inputs):" in output
    assert "Workdir (managed):" in output
    assert "Runs:" in output
    assert "State:" in output
    assert "Logs:" in output
    assert "Cache:" in output
    assert "Tmp:" in output


def test_paths_show_json_command():
    """Test that 'trailblazer paths show --json' works."""
    result = subprocess.run(
        [
            "python",
            "-m",
            "trailblazer.cli.main",
            "paths",
            "show",
            "--json",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0

    # Parse the JSON output
    paths_data = json.loads(result.stdout)

    # Check that all expected keys are present
    expected_keys = [
        "data",
        "workdir",
        "runs",
        "state",
        "logs",
        "cache",
        "tmp",
    ]
    for key in expected_keys:
        assert key in paths_data
        assert isinstance(paths_data[key], str)
        assert Path(paths_data[key]).is_absolute()


def test_paths_ensure_command():
    """Test that 'trailblazer paths ensure' works."""
    result = subprocess.run(
        ["python", "-m", "trailblazer.cli.main", "paths", "ensure"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "✅ All workspace directories created" in result.stdout


def test_artifacts_integration_smoke():
    """Smoke test that artifacts module works with new paths."""
    from trailblazer.core.artifacts import new_run_id, runs_dir, phase_dir

    # Test basic functionality
    run_id = new_run_id()
    assert isinstance(run_id, str)
    assert len(run_id) > 10  # Should have timestamp + UUID

    # Test runs_dir returns a Path
    runs_path = runs_dir()
    assert isinstance(runs_path, Path)
    assert runs_path.name == "runs"

    # Test phase_dir creates path correctly
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        with patch("trailblazer.core.paths.ROOT", tmpdir_path):
            phase_path = phase_dir(run_id, "test_phase")
            assert phase_path.exists()
            assert phase_path.parent.name == run_id
            assert phase_path.name == "test_phase"
