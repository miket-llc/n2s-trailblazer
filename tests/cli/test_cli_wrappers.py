"""Tests for CLI wrapper commands (plan, ingest-all, normalize-all, status)."""

import pytest
from typer.testing import CliRunner

from trailblazer.cli.main import app

# Mark all tests as unit tests (no database needed)
pytestmark = pytest.mark.unit


@pytest.fixture
def runner():
    """CLI test runner."""
    return CliRunner()


class TestCommandsExist:
    """Test that wrapper commands exist and have proper help text."""

    def test_plan_help(self, runner):
        """Test plan command help text."""
        result = runner.invoke(app, ["plan", "--help"])
        assert result.exit_code == 0
        assert "Dry-run preview" in result.output
        assert "ingested" in result.output
        assert "confluence" in result.output.lower()
        assert "dita" in result.output.lower()

    def test_ingest_all_help(self, runner):
        """Test ingest-all command help text."""
        result = runner.invoke(app, ["ingest-all", "--help"])
        assert result.exit_code == 0
        assert "Ingest all" in result.output
        assert "ADF format" in result.output
        assert "from-scratch" in result.output
        assert "since" in result.output

    def test_normalize_all_help(self, runner):
        """Test normalize-all command help text."""
        result = runner.invoke(app, ["normalize-all", "--help"])
        assert result.exit_code == 0
        assert "Normalize all runs" in result.output
        assert "missing normalized output" in result.output
        assert "from-ingest" in result.output

    def test_status_help(self, runner):
        """Test status command help text."""
        result = runner.invoke(app, ["status", "--help"])
        assert result.exit_code == 0
        assert "Show quick status" in result.output
        assert "runs and totals" in result.output
        assert "workspace" in result.output


class TestMainCLIStructure:
    """Test that the wrapper commands are properly integrated into the main CLI."""

    def test_wrapper_commands_appear_in_main_help(self, runner):
        """Test that wrapper commands appear in main CLI help."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0

        # All wrapper commands should be listed
        assert "plan" in result.output
        assert "ingest-all" in result.output
        assert "normalize-all" in result.output
        assert "status" in result.output

        # Should show brief descriptions
        assert "Dry-run preview" in result.output
        assert "Ingest all" in result.output
        assert "Normalize all" in result.output
        assert "Show quick status" in result.output
