"""Tests for enrichment CLI command."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from trailblazer.cli.main import app

runner = CliRunner()


class TestEnrichCLI:
    """Test the enrich CLI command."""

    def test_enrich_help(self):
        """Test enrich command help text."""
        result = runner.invoke(app, ["enrich", "--help"])
        assert result.exit_code == 0
        assert "Enrich normalized documents" in result.output
        assert "--llm" in result.output
        assert "--max-docs" in result.output
        assert "--budget" in result.output
        assert "--progress" in result.output
        assert "--no-color" in result.output

    def test_enrich_missing_run_id(self):
        """Test enrich command fails when run ID is missing."""
        result = runner.invoke(app, ["enrich"])
        assert result.exit_code == 2
        assert "Missing argument" in result.output

    @patch("trailblazer.core.artifacts.phase_dir")
    def test_enrich_nonexistent_run(self, mock_phase_dir):
        """Test enrich command fails for nonexistent run."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Mock phase_dir to return non-existent directory
            mock_phase_dir.return_value = temp_path / "nonexistent"

            result = runner.invoke(app, ["enrich", "nonexistent-run"])
            assert result.exit_code == 1
            assert (
                "not found or normalize phase not completed" in result.output
            )

    @patch("trailblazer.core.artifacts.phase_dir")
    def test_enrich_missing_normalized_file(self, mock_phase_dir):
        """Test enrich command fails when normalized file is missing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            normalize_dir = temp_path / "normalize"
            normalize_dir.mkdir()

            # Mock phase_dir to return directory without normalized.ndjson
            mock_phase_dir.return_value = normalize_dir

            result = runner.invoke(app, ["enrich", "test-run"])
            assert result.exit_code == 1
            assert "Normalized file not found" in result.output

    @patch("trailblazer.cli.main.enrich_from_normalized")
    @patch("trailblazer.core.artifacts.phase_dir")
    def test_enrich_success_rule_based_only(self, mock_phase_dir, mock_enrich):
        """Test successful enrichment with rule-based only."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Setup directories
            normalize_dir = temp_path / "normalize"
            enrich_dir = temp_path / "enrich"
            normalize_dir.mkdir()
            enrich_dir.mkdir()

            # Create normalized file
            normalized_file = normalize_dir / "normalized.ndjson"
            normalized_file.write_text(
                '{"id": "test", "text_md": "content"}\n'
            )

            # Mock phase_dir
            def mock_phase_dir_func(run_id, phase):
                if phase == "normalize":
                    return normalize_dir
                elif phase == "enrich":
                    return enrich_dir

            mock_phase_dir.side_effect = mock_phase_dir_func

            # Mock enrichment function
            mock_stats = {
                "run_id": "test-run",
                "docs_total": 1,
                "docs_llm": 0,
                "suggested_edges_total": 0,
                "quality_flags_counts": {"too_short": 1},
                "duration_seconds": 0.5,
                "llm_enabled": False,
                "completed_at": "2025-01-01T00:00:00Z",
            }
            mock_enrich.return_value = mock_stats

            result = runner.invoke(app, ["enrich", "test-run"])

            assert result.exit_code == 0

            # Verify enrichment was called with correct parameters
            mock_enrich.assert_called_once()
            call_args = mock_enrich.call_args
            assert call_args[1]["run_id"] == "test-run"
            assert call_args[1]["llm_enabled"] is False
            assert call_args[1]["max_docs"] is None
            assert call_args[1]["budget"] is None

    @patch("trailblazer.cli.main.enrich_from_normalized")
    @patch("trailblazer.core.artifacts.phase_dir")
    def test_enrich_success_with_llm(self, mock_phase_dir, mock_enrich):
        """Test successful enrichment with LLM enabled."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Setup directories
            normalize_dir = temp_path / "normalize"
            enrich_dir = temp_path / "enrich"
            normalize_dir.mkdir()
            enrich_dir.mkdir()

            # Create normalized file
            normalized_file = normalize_dir / "normalized.ndjson"
            normalized_file.write_text(
                '{"id": "test", "text_md": "content"}\n'
            )

            # Mock phase_dir
            def mock_phase_dir_func(run_id, phase):
                if phase == "normalize":
                    return normalize_dir
                elif phase == "enrich":
                    return enrich_dir

            mock_phase_dir.side_effect = mock_phase_dir_func

            # Mock enrichment function
            mock_stats = {
                "run_id": "test-run",
                "docs_total": 1,
                "docs_llm": 1,
                "suggested_edges_total": 2,
                "quality_flags_counts": {},
                "duration_seconds": 1.5,
                "llm_enabled": True,
                "completed_at": "2025-01-01T00:00:00Z",
            }
            mock_enrich.return_value = mock_stats

            result = runner.invoke(app, ["enrich", "test-run", "--llm"])

            assert result.exit_code == 0

            # Verify enrichment was called with LLM enabled
            mock_enrich.assert_called_once()
            call_args = mock_enrich.call_args
            assert call_args[1]["llm_enabled"] is True

    @patch("trailblazer.cli.main.enrich_from_normalized")
    @patch("trailblazer.core.artifacts.phase_dir")
    def test_enrich_with_custom_parameters(self, mock_phase_dir, mock_enrich):
        """Test enrichment with custom parameters."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Setup directories
            normalize_dir = temp_path / "normalize"
            enrich_dir = temp_path / "enrich"
            normalize_dir.mkdir()
            enrich_dir.mkdir()

            # Create normalized file
            normalized_file = normalize_dir / "normalized.ndjson"
            normalized_file.write_text(
                '{"id": "test", "text_md": "content"}\n'
            )

            # Mock phase_dir
            def mock_phase_dir_func(run_id, phase):
                if phase == "normalize":
                    return normalize_dir
                elif phase == "enrich":
                    return enrich_dir

            mock_phase_dir.side_effect = mock_phase_dir_func

            # Mock enrichment function
            mock_stats = {
                "run_id": "test-run",
                "docs_total": 50,
                "docs_llm": 50,
                "suggested_edges_total": 10,
                "quality_flags_counts": {"too_short": 5},
                "duration_seconds": 5.0,
                "llm_enabled": True,
                "completed_at": "2025-01-01T00:00:00Z",
            }
            mock_enrich.return_value = mock_stats

            result = runner.invoke(
                app,
                [
                    "enrich",
                    "test-run",
                    "--llm",
                    "--max-docs",
                    "50",
                    "--budget",
                    "1000",
                    "--no-progress",
                ],
            )

            assert result.exit_code == 0

            # Verify enrichment was called with custom parameters
            mock_enrich.assert_called_once()
            call_args = mock_enrich.call_args
            assert call_args[1]["llm_enabled"] is True
            assert call_args[1]["max_docs"] == 50
            assert call_args[1]["budget"] == "1000"
            assert call_args[1]["progress_callback"] is None  # No progress

    @patch("trailblazer.cli.main.enrich_from_normalized")
    @patch("trailblazer.core.artifacts.phase_dir")
    def test_enrich_generates_assurance_files(
        self, mock_phase_dir, mock_enrich
    ):
        """Test that enrichment generates assurance files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Setup directories
            normalize_dir = temp_path / "normalize"
            enrich_dir = temp_path / "enrich"
            normalize_dir.mkdir()
            enrich_dir.mkdir()

            # Create normalized file
            normalized_file = normalize_dir / "normalized.ndjson"
            normalized_file.write_text(
                '{"id": "test", "text_md": "content"}\n'
            )

            # Mock phase_dir
            def mock_phase_dir_func(run_id, phase):
                if phase == "normalize":
                    return normalize_dir
                elif phase == "enrich":
                    return enrich_dir

            mock_phase_dir.side_effect = mock_phase_dir_func

            # Mock enrichment function
            mock_stats = {
                "run_id": "test-run",
                "docs_total": 1,
                "docs_llm": 0,
                "suggested_edges_total": 0,
                "quality_flags_counts": {"too_short": 1},
                "duration_seconds": 0.5,
                "llm_enabled": False,
                "completed_at": "2025-01-01T00:00:00Z",
            }
            mock_enrich.return_value = mock_stats

            result = runner.invoke(app, ["enrich", "test-run"])

            assert result.exit_code == 0

            # Verify assurance files were created
            assurance_json = enrich_dir / "assurance.json"
            assurance_md = enrich_dir / "assurance.md"

            assert assurance_json.exists()
            assert assurance_md.exists()

            # Verify JSON content
            with open(assurance_json) as f:
                data = json.load(f)
            assert data["run_id"] == "test-run"
            assert data["docs_total"] == 1

            # Verify Markdown content
            md_content = assurance_md.read_text()
            assert "# Enrichment Assurance Report" in md_content
            assert "test-run" in md_content
            assert "Documents processed: 1" in md_content

    @patch("trailblazer.cli.main.enrich_from_normalized")
    @patch("trailblazer.core.artifacts.phase_dir")
    def test_enrich_handles_error(self, mock_phase_dir, mock_enrich):
        """Test error handling in enrichment command."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Setup directories
            normalize_dir = temp_path / "normalize"
            enrich_dir = temp_path / "enrich"
            normalize_dir.mkdir()
            enrich_dir.mkdir()

            # Create normalized file
            normalized_file = normalize_dir / "normalized.ndjson"
            normalized_file.write_text(
                '{"id": "test", "text_md": "content"}\n'
            )

            # Mock phase_dir
            def mock_phase_dir_func(run_id, phase):
                if phase == "normalize":
                    return normalize_dir
                elif phase == "enrich":
                    return enrich_dir

            mock_phase_dir.side_effect = mock_phase_dir_func

            # Mock enrichment function to raise error
            mock_enrich.side_effect = Exception("Test error")

            result = runner.invoke(app, ["enrich", "test-run"])

            assert result.exit_code == 1
            assert "Enrichment failed: Test error" in result.output

    @patch("trailblazer.cli.main.enrich_from_normalized")
    @patch("trailblazer.core.artifacts.phase_dir")
    def test_enrich_ndjson_events(self, mock_phase_dir, mock_enrich):
        """Test that enrichment emits NDJSON events to stdout."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Setup directories
            normalize_dir = temp_path / "normalize"
            enrich_dir = temp_path / "enrich"
            normalize_dir.mkdir()
            enrich_dir.mkdir()

            # Create normalized file
            normalized_file = normalize_dir / "normalized.ndjson"
            normalized_file.write_text(
                '{"id": "test", "text_md": "content"}\n'
            )

            # Mock phase_dir
            def mock_phase_dir_func(run_id, phase):
                if phase == "normalize":
                    return normalize_dir
                elif phase == "enrich":
                    return enrich_dir

            mock_phase_dir.side_effect = mock_phase_dir_func

            # Mock enrichment function and capture emit_event calls

            def mock_enrich_func(**kwargs):
                emit_event = kwargs.get("emit_event")
                if emit_event:
                    # Simulate some events
                    emit_event("enrich.begin", run_id="test-run")
                    emit_event("enrich.doc", doc_id="test", docs_processed=1)
                    emit_event("enrich.end", docs_total=1)

                return {
                    "run_id": "test-run",
                    "docs_total": 1,
                    "docs_llm": 0,
                    "suggested_edges_total": 0,
                    "quality_flags_counts": {},
                    "duration_seconds": 0.5,
                    "llm_enabled": False,
                    "completed_at": "2025-01-01T00:00:00Z",
                }

            mock_enrich.side_effect = mock_enrich_func

            result = runner.invoke(app, ["enrich", "test-run"])

            assert result.exit_code == 0

            # Parse NDJSON events from stdout
            stdout_lines = (
                result.stdout.strip().split("\n")
                if result.stdout.strip()
                else []
            )
            events = []
            for line in stdout_lines:
                if line.strip():
                    try:
                        event = json.loads(line)
                        events.append(event)
                    except json.JSONDecodeError:
                        pass  # Skip non-JSON lines

            # Verify events were emitted
            assert len(events) > 0

            # Find specific events
            begin_events = [
                e for e in events if e.get("event") == "enrich.begin"
            ]
            complete_events = [
                e for e in events if e.get("event") == "enrich.complete"
            ]

            assert len(begin_events) >= 1
            assert len(complete_events) >= 1

            # Verify event structure
            for event in events:
                assert "timestamp" in event
                assert "event" in event
                assert "run_id" in event

    def test_enrich_no_progress_flag(self):
        """Test that --no-progress flag disables progress output."""
        # This would need more complex mocking to fully test
        # For now, just verify the flag is recognized
        result = runner.invoke(app, ["enrich", "--help"])
        assert result.exit_code == 0
        assert "--progress/--no-progress" in result.output

    def test_enrich_no_color_flag(self):
        """Test that --no-color flag is recognized."""
        result = runner.invoke(app, ["enrich", "--help"])
        assert result.exit_code == 0
        assert "--no-color" in result.output


class TestEnrichmentAssuranceMarkdown:
    """Test enrichment assurance markdown generation."""

    def test_generate_enrichment_assurance_md_basic(self):
        """Test basic assurance markdown generation."""
        from trailblazer.cli.main import _generate_enrichment_assurance_md

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "assurance.md"

            stats = {
                "run_id": "test-run-123",
                "docs_total": 100,
                "docs_llm": 50,
                "suggested_edges_total": 25,
                "quality_flags_counts": {"too_short": 10, "no_structure": 5},
                "duration_seconds": 30.5,
                "llm_enabled": True,
                "completed_at": "2025-01-01T12:00:00Z",
            }

            _generate_enrichment_assurance_md(stats, output_path)

            assert output_path.exists()
            content = output_path.read_text()

            # Verify required sections
            assert "# Enrichment Assurance Report" in content
            assert "test-run-123" in content
            assert "Documents processed: 100" in content
            assert "LLM enriched: 50" in content
            assert "Suggested edges: 25" in content
            assert "too_short: 10" in content
            assert "no_structure: 5" in content
            assert "3.3 documents/second" in content  # 100/30.5
            assert "enriched.jsonl" in content
            assert "fingerprints.jsonl" in content
            assert "suggested_edges.jsonl" in content

    def test_generate_enrichment_assurance_md_no_llm(self):
        """Test assurance markdown generation without LLM."""
        from trailblazer.cli.main import _generate_enrichment_assurance_md

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "assurance.md"

            stats = {
                "run_id": "test-run-456",
                "docs_total": 200,
                "docs_llm": 0,
                "suggested_edges_total": 0,
                "quality_flags_counts": {},
                "duration_seconds": 10.0,
                "llm_enabled": False,
                "completed_at": "2025-01-01T12:00:00Z",
            }

            _generate_enrichment_assurance_md(stats, output_path)

            content = output_path.read_text()

            # Verify LLM-specific content is appropriate
            assert "LLM enabled: False" in content
            assert "No quality flags detected" in content
            assert (
                "suggested_edges.jsonl" not in content
            )  # Should not mention edges file

    def test_generate_enrichment_assurance_md_empty_quality_flags(self):
        """Test assurance markdown generation with no quality flags."""
        from trailblazer.cli.main import _generate_enrichment_assurance_md

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "assurance.md"

            stats = {
                "run_id": "clean-run",
                "docs_total": 50,
                "docs_llm": 25,
                "suggested_edges_total": 10,
                "quality_flags_counts": {},
                "duration_seconds": 5.0,
                "llm_enabled": True,
                "completed_at": "2025-01-01T12:00:00Z",
            }

            _generate_enrichment_assurance_md(stats, output_path)

            content = output_path.read_text()
            assert "No quality flags detected" in content
