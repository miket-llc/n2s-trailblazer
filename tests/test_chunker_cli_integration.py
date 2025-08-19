"""Tests for chunker CLI integration."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from trailblazer.cli.main import app


class TestChunkerCLIIntegration:
    """Test chunker CLI commands and parameter handling."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

    def create_test_run(self, run_id: str):
        """Create a test run with enriched input."""
        run_dir = self.temp_path / "runs" / run_id
        enrich_dir = run_dir / "enrich"
        enrich_dir.mkdir(parents=True, exist_ok=True)

        enriched_file = enrich_dir / "enriched.jsonl"
        with open(enriched_file, "w") as f:
            f.write(
                json.dumps(
                    {
                        "id": "doc1",
                        "title": "Test Document",
                        "text_md": "This is test content for CLI chunking. "
                        * 30,
                        "attachments": [],
                        "chunk_hints": {"preferHeadings": True},
                        "section_map": [],
                    }
                )
                + "\n"
            )

        return run_dir

    @patch("src.trailblazer.core.artifacts.phase_dir")
    def test_chunk_cli_default_parameters(self, mock_phase_dir):
        """Test chunk CLI with default parameters."""
        run_id = "test_run_001"
        run_dir = self.create_test_run(run_id)

        # Mock phase_dir to return our test directory
        mock_phase_dir.side_effect = (
            lambda rid, phase: run_dir / phase if phase else run_dir
        )

        # Run chunk command with defaults
        result = self.runner.invoke(app, ["chunk", run_id])

        # Should succeed
        assert result.exit_code == 0

        # Verify output mentions default parameters
        assert "Max tokens: 800" in result.stderr
        assert "Min tokens: 120" in result.stderr
        assert "Overlap tokens: 60" in result.stderr

    @patch("src.trailblazer.core.artifacts.phase_dir")
    def test_chunk_cli_custom_parameters(self, mock_phase_dir):
        """Test chunk CLI with custom parameters."""
        run_id = "test_run_002"
        run_dir = self.create_test_run(run_id)

        mock_phase_dir.side_effect = (
            lambda rid, phase: run_dir / phase if phase else run_dir
        )

        # Run chunk command with custom parameters
        result = self.runner.invoke(
            app,
            [
                "chunk",
                run_id,
                "--max-tokens",
                "1000",
                "--min-tokens",
                "150",
                "--overlap-tokens",
                "80",
            ],
        )

        assert result.exit_code == 0

        # Verify custom parameters are shown
        assert "Max tokens: 1000" in result.stderr
        assert "Min tokens: 150" in result.stderr
        assert "Overlap tokens: 80" in result.stderr

    @patch("src.trailblazer.core.artifacts.phase_dir")
    def test_chunk_cli_parameter_validation(self, mock_phase_dir):
        """Test that CLI validates parameters correctly."""
        run_id = "test_run_003"
        run_dir = self.create_test_run(run_id)

        mock_phase_dir.side_effect = (
            lambda rid, phase: run_dir / phase if phase else run_dir
        )

        # Test with invalid (negative) parameters
        result = self.runner.invoke(
            app, ["chunk", run_id, "--max-tokens", "-100"]
        )

        # Should fail with validation error
        assert result.exit_code != 0

    @patch("src.trailblazer.core.artifacts.phase_dir")
    def test_chunk_cli_missing_run(self, mock_phase_dir):
        """Test chunk CLI with non-existent run."""
        run_id = "nonexistent_run"

        # Mock to return non-existent path
        mock_phase_dir.side_effect = (
            lambda rid, phase: Path("/nonexistent") / rid / phase
            if phase
            else Path("/nonexistent") / rid
        )

        result = self.runner.invoke(app, ["chunk", run_id])

        # Should fail
        assert result.exit_code == 1
        assert "not found" in result.stderr

    @patch("src.trailblazer.core.artifacts.phase_dir")
    def test_chunk_cli_missing_input_files(self, mock_phase_dir):
        """Test chunk CLI when input files are missing."""
        run_id = "test_run_004"
        run_dir = self.temp_path / "runs" / run_id
        run_dir.mkdir(
            parents=True, exist_ok=True
        )  # Create run dir but no input files

        mock_phase_dir.side_effect = (
            lambda rid, phase: run_dir / phase if phase else run_dir
        )

        result = self.runner.invoke(app, ["chunk", run_id])

        # Should fail with informative message
        assert result.exit_code == 1
        assert "No input files found" in result.stderr

    @patch("src.trailblazer.core.artifacts.phase_dir")
    def test_chunk_cli_progress_output(self, mock_phase_dir):
        """Test chunk CLI progress output."""
        run_id = "test_run_005"
        run_dir = self.create_test_run(run_id)

        mock_phase_dir.side_effect = (
            lambda rid, phase: run_dir / phase if phase else run_dir
        )

        # Test with progress enabled (default)
        result = self.runner.invoke(app, ["chunk", run_id])

        assert result.exit_code == 0
        assert "🔄 Chunking documents" in result.stderr
        assert "✅ Chunking complete" in result.stderr

    @patch("src.trailblazer.core.artifacts.phase_dir")
    def test_chunk_cli_no_progress(self, mock_phase_dir):
        """Test chunk CLI with progress disabled."""
        run_id = "test_run_006"
        run_dir = self.create_test_run(run_id)

        mock_phase_dir.side_effect = (
            lambda rid, phase: run_dir / phase if phase else run_dir
        )

        # Test with progress disabled
        result = self.runner.invoke(app, ["chunk", run_id, "--no-progress"])

        assert result.exit_code == 0
        # Should still have basic output but less verbose
        assert "🔄 Chunking documents" in result.stderr

    @patch("src.trailblazer.core.artifacts.phase_dir")
    def test_chunk_cli_output_format(self, mock_phase_dir):
        """Test that chunk CLI produces expected output format."""
        run_id = "test_run_007"
        run_dir = self.create_test_run(run_id)

        mock_phase_dir.side_effect = (
            lambda rid, phase: run_dir / phase if phase else run_dir
        )

        result = self.runner.invoke(app, ["chunk", run_id])

        assert result.exit_code == 0

        # Should mention key information
        assert "Input type:" in result.stderr
        assert "Documents:" in result.stderr
        assert "Chunks:" in result.stderr
        assert "Token range:" in result.stderr
        assert "Artifacts written to:" in result.stderr

    def test_chunk_group_help(self):
        """Test that chunk group help shows operator workflow."""
        result = self.runner.invoke(app, ["chunk", "--help"])

        assert result.exit_code == 0

        # Should show the operator workflow
        assert "Common operator workflow:" in result.stdout
        assert "chunk audit" in result.stdout
        assert "chunk rechunk" in result.stdout
        assert "hard token caps" in result.stdout

    def test_chunk_audit_help(self):
        """Test chunk audit command help."""
        result = self.runner.invoke(app, ["chunk", "audit", "--help"])

        assert result.exit_code == 0

        # Should show audit-specific help
        assert "Audit existing chunks" in result.stdout
        assert "--runs-glob" in result.stdout
        assert "--max-tokens" in result.stdout
        assert "oversize chunks" in result.stdout

    def test_chunk_rechunk_help(self):
        """Test chunk rechunk command help."""
        result = self.runner.invoke(app, ["chunk", "rechunk", "--help"])

        assert result.exit_code == 0

        # Should show rechunk-specific help
        assert "Re-chunk specific documents" in result.stdout
        assert "--targets-file" in result.stdout
        assert "--overlap-tokens" in result.stdout
        assert "layered splitting" in result.stdout

    @patch("src.trailblazer.core.artifacts.phase_dir")
    def test_chunk_cli_enriched_vs_normalized_preference(self, mock_phase_dir):
        """Test that CLI correctly shows input type preference."""
        run_id = "test_run_008"
        run_dir = self.temp_path / "runs" / run_id

        # Create both enriched and normalized files
        enrich_dir = run_dir / "enrich"
        enrich_dir.mkdir(parents=True, exist_ok=True)
        with open(enrich_dir / "enriched.jsonl", "w") as f:
            f.write(
                json.dumps({"id": "doc1", "text_md": "enriched content"})
                + "\n"
            )

        norm_dir = run_dir / "normalize"
        norm_dir.mkdir(parents=True, exist_ok=True)
        with open(norm_dir / "normalized.ndjson", "w") as f:
            f.write(
                json.dumps({"id": "doc1", "text_md": "normalized content"})
                + "\n"
            )

        mock_phase_dir.side_effect = (
            lambda rid, phase: run_dir / phase if phase else run_dir
        )

        result = self.runner.invoke(app, ["chunk", run_id])

        assert result.exit_code == 0

        # Should prefer enriched
        assert "Input type: enriched" in result.stderr

    @patch("src.trailblazer.core.artifacts.phase_dir")
    def test_chunk_cli_normalized_fallback(self, mock_phase_dir):
        """Test that CLI falls back to normalized when enriched is missing."""
        run_id = "test_run_009"
        run_dir = self.temp_path / "runs" / run_id

        # Create only normalized file
        norm_dir = run_dir / "normalize"
        norm_dir.mkdir(parents=True, exist_ok=True)
        with open(norm_dir / "normalized.ndjson", "w") as f:
            f.write(
                json.dumps({"id": "doc1", "text_md": "normalized content"})
                + "\n"
            )

        mock_phase_dir.side_effect = (
            lambda rid, phase: run_dir / phase if phase else run_dir
        )

        result = self.runner.invoke(app, ["chunk", run_id])

        assert result.exit_code == 0

        # Should use normalized
        assert "Input type: normalized" in result.stderr

    @patch("src.trailblazer.core.artifacts.phase_dir")
    def test_chunk_cli_error_handling(self, mock_phase_dir):
        """Test chunk CLI error handling and reporting."""
        run_id = "test_run_010"
        run_dir = self.create_test_run(run_id)

        mock_phase_dir.side_effect = (
            lambda rid, phase: run_dir / phase if phase else run_dir
        )

        # Create a scenario that might cause chunking to fail
        # (e.g., corrupt input file)
        enrich_dir = run_dir / "enrich"
        with open(enrich_dir / "enriched.jsonl", "w") as f:
            f.write("invalid json content\n")

        result = self.runner.invoke(app, ["chunk", run_id])

        # Should handle error gracefully
        assert result.exit_code == 1
        assert "❌ Chunking failed" in result.stderr

    def test_chunk_cli_help_examples(self):
        """Test that CLI help includes practical examples."""
        result = self.runner.invoke(app, ["chunk", "--help"])

        assert result.exit_code == 0

        # Should include usage examples
        assert "Example:" in result.stdout
        assert "trailblazer chunk RUN_ID_HERE" in result.stdout
        assert "--max-tokens" in result.stdout
        assert "--overlap-tokens" in result.stdout


if __name__ == "__main__":
    pytest.main([__file__])
