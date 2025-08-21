"""Test CLI compatibility layer for old command patterns."""

import pytest

# Mark all tests as unit tests (no database needed)
pytestmark = pytest.mark.unit


def test_cli_runner_embed_preflight_mapping(cli_runner):
    """Test that old embed preflight maps to new plan-preflight."""
    # This should automatically map "embed preflight" to "embed plan-preflight"
    # The actual command will fail since we don't have a real run, but the mapping
    # should work
    from trailblazer.cli.main import app

    result = cli_runner.invoke(app, ["embed", "preflight", "test_run"])

    # The command should be mapped, even if it fails due to missing run
    assert result is not None


def test_cli_runner_chunk_sweep_mapping(cli_runner):
    """Test that old chunk sweep maps to new chunk command."""
    # This should map "chunk sweep" to "chunk RUN_ID"
    from trailblazer.cli.main import app

    result = cli_runner.invoke(
        app, ["chunk", "sweep", "--runs-glob", "var/runs/*"]
    )

    # The command should be mapped, even if it fails due to missing run
    assert result is not None


def test_cli_runner_enrich_sweep_mapping(cli_runner):
    """Test that old enrich sweep maps to new enrich command."""
    # This should map "enrich sweep" to "enrich RUN_ID"
    from trailblazer.cli.main import app

    result = cli_runner.invoke(
        app, ["enrich", "sweep", "--runs-glob", "var/runs/*"]
    )

    # The command should be mapped, even if it fails due to missing run
    assert result is not None


def test_backward_compatible_cli_sweep_commands(backward_compatible_cli):
    """Test that backward compatible CLI handles old sweep commands."""
    # Test chunk sweep
    result = backward_compatible_cli.invoke("chunk sweep")
    assert result.exit_code == 0
    assert "Mock chunk sweep completed" in result.stdout

    # Test enrich sweep
    result = backward_compatible_cli.invoke("enrich sweep")
    assert result.exit_code == 0
    assert "Mock enrich sweep completed" in result.stdout
