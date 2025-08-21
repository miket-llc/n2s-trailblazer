"""Test CLI flag standardization: --dimension (not --dimensions)."""

import pytest
from typer.testing import CliRunner

from trailblazer.cli.main import app

# Mark all tests as unit tests (no database needed)
pytestmark = pytest.mark.unit


class TestFlagDimension:
    """Test that CLI uses --dimension flag consistently."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()

    def test_embed_load_has_dimension_flag(self):
        """Test that embed load exposes --dimension flag."""
        result = self.runner.invoke(app, ["embed", "load", "--help"])

        assert result.exit_code == 0
        assert "--dimension" in result.stdout
        assert "--dimensions" not in result.stdout

    def test_embed_corpus_has_dimension_flag(self):
        """Test that embed corpus exposes --dimension flag."""
        result = self.runner.invoke(app, ["embed", "corpus", "--help"])

        assert result.exit_code == 0
        assert "--dimension" in result.stdout
        assert "--dimensions" not in result.stdout

    def test_embed_plan_preflight_has_dimension_flag(self):
        """Test that embed plan-preflight exposes --dimension flag."""
        result = self.runner.invoke(app, ["embed", "plan-preflight", "--help"])

        assert result.exit_code == 0
        assert "--dimension" in result.stdout
        assert "--dimensions" not in result.stdout

    def test_embed_reembed_if_changed_has_dimension_flag(self):
        """Test that embed reembed-if-changed exposes --dimension flag."""
        result = self.runner.invoke(
            app, ["embed", "reembed-if-changed", "--help"]
        )

        assert result.exit_code == 0
        assert "--dimension" in result.stdout
        assert "--dimensions" not in result.stdout

    def test_embed_load_rejects_dimensions_flag(self):
        """Test that embed load rejects legacy --dimensions flag."""
        result = self.runner.invoke(
            app,
            [
                "embed",
                "load",
                "--run-id",
                "test-run",
                "--dimensions",  # Legacy flag should be rejected
                "1536",
                "--provider",
                "dummy",
            ],
        )

        # Should fail with "no such option" error
        assert result.exit_code != 0
        # Check stderr for error message since typer outputs there
        assert (
            "no such option" in result.output.lower()
            or "unrecognized" in result.output.lower()
        )

    def test_embed_corpus_rejects_dimensions_flag(self):
        """Test that embed corpus rejects legacy --dimensions flag."""
        result = self.runner.invoke(
            app,
            [
                "embed",
                "corpus",
                "--dimensions",  # Legacy flag should be rejected
                "1536",
                "--provider",
                "openai",
            ],
        )

        # Should fail with "no such option" error
        assert result.exit_code != 0
        # Check stderr for error message since typer outputs there
        assert (
            "no such option" in result.output.lower()
            or "unrecognized" in result.output.lower()
        )

    def test_dimension_flag_help_text(self):
        """Test that --dimension flag has proper help text."""
        result = self.runner.invoke(app, ["embed", "load", "--help"])

        assert result.exit_code == 0
        # Should have help text mentioning common dimensions
        help_text = result.stdout.lower()
        assert "dimension" in help_text
        assert any(dim in help_text for dim in ["512", "1024", "1536"])

    def test_embed_help_consistency(self):
        """Test that all embed subcommands consistently use dimension terminology."""
        embed_commands = [
            "load",
            "corpus",
            "reembed-if-changed",
            "plan-preflight",
        ]

        for cmd in embed_commands:
            result = self.runner.invoke(app, ["embed", cmd, "--help"])
            assert result.exit_code == 0

            # Should use "dimension" terminology, not "dimensions"
            help_text = result.stdout.lower()
            if "dimension" in help_text:
                # If dimension is mentioned, it should be singular form in help text
                dimension_contexts = []
                lines = help_text.split("\n")
                for line in lines:
                    if "dimension" in line:
                        dimension_contexts.append(line.strip())

                # Check that we don't have "dimensions" in flag names
                for context in dimension_contexts:
                    if "--" in context:  # This is a flag line
                        assert "--dimensions" not in context, (
                            f"Found --dimensions in {cmd}: {context}"
                        )
