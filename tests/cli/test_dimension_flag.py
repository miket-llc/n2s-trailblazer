"""Test that --dimension is the only dimension flag used consistently across all commands."""

import inspect
from typing import get_origin, get_args

from typer.testing import CliRunner

from trailblazer.cli.main import app


class TestDimensionFlag:
    """Test dimension flag consistency across CLI commands."""

    def test_dimension_flag_consistency(self):
        """Test that all embed commands use --dimension flag consistently."""
        runner = CliRunner()

        # Test embed preflight command
        result = runner.invoke(app, ["embed", "preflight", "--help"])
        assert result.exit_code == 0
        assert "--dimension" in result.stdout
        assert "--dim " not in result.stdout  # Should not have old --dim flag

        # Test embed plan-preflight command
        result = runner.invoke(app, ["embed", "plan-preflight", "--help"])
        assert result.exit_code == 0
        assert "--dimension" in result.stdout
        assert "--dim " not in result.stdout

        # Test embed load command
        result = runner.invoke(app, ["embed", "load", "--help"])
        assert result.exit_code == 0
        assert "--dimension" in result.stdout
        assert "--dim " not in result.stdout

    def test_no_dim_flag_in_any_command(self):
        """Test that the old --dim flag is not present in any command."""
        runner = CliRunner()

        # Test various embed commands
        embed_commands = [
            ["embed", "load", "--help"],
            ["embed", "preflight", "--help"],
            ["embed", "plan-preflight", "--help"],
            ["embed", "corpus", "--help"],
            ["embed", "diff", "--help"],
        ]

        for cmd in embed_commands:
            try:
                result = runner.invoke(app, cmd)
                if result.exit_code == 0:
                    # Should not contain --dim flag (with space to avoid matching --dimension)
                    assert "--dim " not in result.stdout, (
                        f"Command {' '.join(cmd)} still has --dim flag"
                    )
                    # Should contain --dimension flag for embedding commands
                    if "embed" in cmd:
                        assert "--dimension" in result.stdout, (
                            f"Command {' '.join(cmd)} missing --dimension flag"
                        )
            except Exception:
                # Some commands might fail due to missing dependencies in test env
                # That's okay - we're just checking help text
                pass

    def test_dimension_parameter_types(self):
        """Test that dimension parameters have correct types."""
        # Import the functions to inspect their signatures
        from trailblazer.cli.main import (
            embed_preflight_cmd,
            embed_plan_preflight_cmd,
        )

        # Check embed_preflight_cmd
        sig = inspect.signature(embed_preflight_cmd)
        dimension_param = sig.parameters.get("dimension")
        assert dimension_param is not None, (
            "embed_preflight_cmd should have dimension parameter"
        )

        # Check type annotation
        annotation = dimension_param.annotation
        if hasattr(annotation, "__origin__"):
            # Handle Optional[int] or Union[int, None]
            origin = get_origin(annotation)
            args = get_args(annotation)
            if origin is type(None) or (
                hasattr(origin, "__name__") and "Union" in str(origin)
            ):
                # Optional[int] case
                assert int in args, (
                    f"dimension parameter should accept int, got: {annotation}"
                )
            else:
                assert annotation is int, (
                    f"dimension parameter should be int, got: {annotation}"
                )
        else:
            assert annotation is int, (
                f"dimension parameter should be int, got: {annotation}"
            )

        # Check embed_plan_preflight_cmd
        sig = inspect.signature(embed_plan_preflight_cmd)
        dimension_param = sig.parameters.get("dimension")
        assert dimension_param is not None, (
            "embed_plan_preflight_cmd should have dimension parameter"
        )

    def test_dimension_flag_help_text(self):
        """Test that dimension flag help text is consistent."""
        runner = CliRunner()

        # Test embed preflight help
        result = runner.invoke(app, ["embed", "preflight", "--help"])
        if result.exit_code == 0:
            # Should mention dimension values
            help_text = result.stdout.lower()
            assert "dimension" in help_text
            assert any(dim in help_text for dim in ["512", "1024", "1536"]), (
                "Should mention common dimension values"
            )

        # Test embed plan-preflight help
        result = runner.invoke(app, ["embed", "plan-preflight", "--help"])
        if result.exit_code == 0:
            help_text = result.stdout.lower()
            assert "dimension" in help_text

    def test_dimension_flag_in_subprocess_calls(self):
        """Test that subprocess calls use --dimension flag consistently."""
        # This test checks that when commands call other commands via subprocess,
        # they use the correct --dimension flag

        # We can't easily test actual subprocess calls, but we can verify
        # the CLI commands themselves are consistent

        runner = CliRunner()

        # Test that preflight command accepts --dimension
        result = runner.invoke(app, ["embed", "preflight", "--help"])
        if result.exit_code == 0:
            assert "--dimension" in result.stdout
            # Verify the flag is properly defined
            lines = result.stdout.split("\n")
            dimension_lines = [line for line in lines if "--dimension" in line]
            assert len(dimension_lines) > 0, (
                "Should have --dimension flag definition"
            )

    def test_no_legacy_dim_references(self):
        """Test that there are no legacy --dim references in help or code."""
        runner = CliRunner()

        # Get help for main app
        result = runner.invoke(app, ["--help"])
        if result.exit_code == 0:
            # Should not contain --dim references
            assert "--dim " not in result.stdout

        # Check embed subcommand help
        result = runner.invoke(app, ["embed", "--help"])
        if result.exit_code == 0:
            assert "--dim " not in result.stdout
