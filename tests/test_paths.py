"""Tests for workspace path management."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch


from trailblazer.core import paths


def test_paths_default_values():
    """Test default path values."""
    # Test that paths resolve correctly with defaults
    assert paths.data().name == "data"
    assert paths.workdir().name == "var"
    assert paths.runs().name == "runs"
    assert paths.state().name == "state"
    assert paths.logs().name == "logs"
    assert paths.cache().name == "cache"
    assert paths.tmp().name == "tmp"

    # Test that var subdirectories are under workdir
    assert paths.runs().parent == paths.workdir()
    assert paths.state().parent == paths.workdir()
    assert paths.logs().parent == paths.workdir()
    assert paths.cache().parent == paths.workdir()
    assert paths.tmp().parent == paths.workdir()


def test_paths_env_overrides():
    """Test that environment variables override defaults."""
    with patch.dict(
        os.environ,
        {
            "TRAILBLAZER_DATA_DIR": "custom_data",
            "TRAILBLAZER_WORKDIR": "custom_var",
        },
    ):
        # Need to reload the settings after env change
        from trailblazer.core.config import Settings

        custom_settings = Settings()

        with patch("trailblazer.core.paths.SETTINGS", custom_settings):
            assert paths.data().name == "custom_data"
            assert paths.workdir().name == "custom_var"
            assert paths.runs().parent.name == "custom_var"


def test_ensure_all_creates_directories():
    """Test that ensure_all creates all workspace directories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Mock the ROOT to point to our temp directory
        with patch("trailblazer.core.paths.ROOT", tmpdir_path):
            paths.ensure_all()

            # Check that all directories were created
            assert (tmpdir_path / "data").exists()
            assert (tmpdir_path / "var").exists()
            assert (tmpdir_path / "var" / "runs").exists()
            assert (tmpdir_path / "var" / "state").exists()
            assert (tmpdir_path / "var" / "logs").exists()
            assert (tmpdir_path / "var" / "cache").exists()
            assert (tmpdir_path / "var" / "tmp").exists()


def test_paths_are_absolute():
    """Test that all paths are absolute."""
    assert paths.data().is_absolute()
    assert paths.workdir().is_absolute()
    assert paths.runs().is_absolute()
    assert paths.state().is_absolute()
    assert paths.logs().is_absolute()
    assert paths.cache().is_absolute()
    assert paths.tmp().is_absolute()


def test_paths_integration_with_artifacts():
    """Test that artifacts module uses new paths correctly."""
    from trailblazer.core.artifacts import runs_dir, phase_dir

    # Test that artifacts module uses the new paths
    assert runs_dir() == paths.runs()

    # Test phase_dir creates under var/runs
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        with patch("trailblazer.core.paths.ROOT", tmpdir_path):
            test_run_id = "test_run_123"
            test_phase = "ingest"

            phase_path = phase_dir(test_run_id, test_phase)
            expected_path = (
                tmpdir_path / "var" / "runs" / test_run_id / test_phase
            )

            assert phase_path == expected_path
            assert phase_path.exists()


def test_normalize_path_integration():
    """Test that normalize module uses new paths correctly."""
    from trailblazer.pipeline.steps.normalize.html_to_md import (
        _default_ingest_path,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        with patch("trailblazer.core.paths.ROOT", tmpdir_path):
            test_run_id = "test_run_456"

            # Create test structure
            runs_dir = tmpdir_path / "var" / "runs" / test_run_id / "ingest"
            runs_dir.mkdir(parents=True)
            confluence_file = runs_dir / "confluence.ndjson"
            confluence_file.touch()

            # Test that it finds the file in the new location
            result_path = _default_ingest_path(test_run_id)
            assert result_path == confluence_file
            assert result_path.exists()


# Test removed: _default_normalized_path function no longer exists in embed loader
# This was testing deprecated functionality that has been refactored
def test_embed_loader_path_integration():
    """Test removed - function _default_normalized_path no longer exists."""
    pass
