"""Test confluence spaces CLI command."""

import json
from unittest.mock import Mock, patch
import pytest
from typer.testing import CliRunner
from trailblazer.cli.main import app


@pytest.fixture
def fake_spaces_data():
    """Mock spaces data for testing."""
    return [
        {
            "id": "12345",
            "key": "DEV",
            "name": "Development Space",
            "type": "global",
            "status": "current",
            "homepageId": "67890",
        },
        {
            "id": "54321",
            "key": "PROD",
            "name": "Production Space",
            "type": "global",
            "status": "current",
            "homepageId": "98765",
        },
    ]


def test_spaces_cli_writes_artifact_and_prints_table(
    tmp_path, fake_spaces_data
):
    """Test that spaces CLI writes JSON artifact and prints table."""
    runner = CliRunner()

    with (
        patch("trailblazer.core.artifacts.new_run_id") as mock_run_id,
        patch("trailblazer.core.artifacts.phase_dir") as mock_phase_dir,
        patch(
            "trailblazer.adapters.confluence_api.ConfluenceClient"
        ) as mock_client_class,
    ):
        # Setup mocks
        mock_run_id.return_value = "test-run-123"
        mock_phase_dir.return_value = tmp_path / "ingest"
        (tmp_path / "ingest").mkdir(parents=True, exist_ok=True)

        mock_client = Mock()
        mock_client.get_spaces.return_value = iter(fake_spaces_data)
        mock_client_class.return_value = mock_client

        # Run command
        result = runner.invoke(app, ["confluence", "spaces"])

        # Check success
        assert result.exit_code == 0

        # Check artifact was written
        spaces_file = tmp_path / "ingest" / "spaces.json"
        assert spaces_file.exists()

        with open(spaces_file) as f:
            saved_spaces = json.load(f)

        # Should be sorted by key, id
        assert len(saved_spaces) == 2
        assert saved_spaces[0]["key"] == "DEV"
        assert saved_spaces[1]["key"] == "PROD"

        # Check expected fields
        for space in saved_spaces:
            assert "id" in space
            assert "key" in space
            assert "name" in space
            assert "type" in space
            assert "status" in space
            assert "homepage_id" in space

        # Check console output contains table headers
        assert "ID" in result.stdout
        assert "KEY" in result.stdout
        assert "NAME" in result.stdout
        assert "TYPE" in result.stdout
        assert "STATUS" in result.stdout

        # Check space data appears in output
        assert "DEV" in result.stdout
        assert "PROD" in result.stdout
        assert "Development Space" in result.stdout
        assert "Production Space" in result.stdout


def test_spaces_cli_handles_empty_response(tmp_path):
    """Test spaces CLI handles no spaces returned."""
    runner = CliRunner()

    with (
        patch("trailblazer.core.artifacts.new_run_id") as mock_run_id,
        patch("trailblazer.core.artifacts.phase_dir") as mock_phase_dir,
        patch(
            "trailblazer.adapters.confluence_api.ConfluenceClient"
        ) as mock_client_class,
    ):
        # Setup mocks
        mock_run_id.return_value = "test-run-empty"
        mock_phase_dir.return_value = tmp_path / "ingest"
        (tmp_path / "ingest").mkdir(parents=True, exist_ok=True)

        mock_client = Mock()
        mock_client.get_spaces.return_value = iter([])  # Empty
        mock_client_class.return_value = mock_client

        # Run command
        result = runner.invoke(app, ["confluence", "spaces"])

        # Check success
        assert result.exit_code == 0

        # Check artifact was written (empty array)
        spaces_file = tmp_path / "ingest" / "spaces.json"
        assert spaces_file.exists()

        with open(spaces_file) as f:
            saved_spaces = json.load(f)

        assert saved_spaces == []
        assert "No spaces found." in result.stdout
