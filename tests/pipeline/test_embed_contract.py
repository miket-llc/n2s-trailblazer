"""Test embed pipeline contract: no on-the-fly chunking allowed."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from typer.testing import CliRunner

from trailblazer.cli.main import app


class TestEmbedContract:
    """Test that embed enforces contract to use only pre-chunked data."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

    def create_test_run_without_chunks(self, run_id: str) -> Path:
        """Create a test run directory without chunks."""
        run_dir = self.temp_path / "runs" / run_id
        enrich_dir = run_dir / "enrich"
        enrich_dir.mkdir(parents=True, exist_ok=True)

        # Create enriched.jsonl (but no chunks)
        enriched_file = enrich_dir / "enriched.jsonl"
        enriched_file.write_text(
            json.dumps(
                {
                    "id": "test-doc-1",
                    "title": "Test Document",
                    "text_md": "Test content",
                    "source_system": "test",
                }
            )
            + "\n"
        )

        return run_dir

    def create_test_run_with_chunks(self, run_id: str) -> Path:
        """Create a test run directory with chunks."""
        run_dir = self.create_test_run_without_chunks(run_id)
        chunk_dir = run_dir / "chunk"
        chunk_dir.mkdir(parents=True, exist_ok=True)

        # Create chunks.ndjson
        chunks_file = chunk_dir / "chunks.ndjson"
        chunks_file.write_text(
            json.dumps(
                {
                    "chunk_id": f"{run_id}:0001",
                    "doc_id": "test-doc-1",
                    "ord": 0,
                    "text_md": "Test content chunk",
                    "char_count": 18,
                    "token_count": 5,
                    "chunk_type": "text",
                }
            )
            + "\n"
        )

        return run_dir

    @patch.dict(os.environ, {"TB_TESTING": "1"})
    def test_embed_load_fails_without_chunks(self):
        """Test that embed load fails when no chunks are materialized."""
        run_id = "test-run-no-chunks"
        self.create_test_run_without_chunks(run_id)

        with patch("trailblazer.core.paths.runs") as mock_runs:
            mock_runs.return_value = self.temp_path / "runs"

            result = self.runner.invoke(
                app,
                [
                    "embed",
                    "load",
                    "--run-id",
                    run_id,
                    "--provider",
                    "dummy",
                ],
            )

        assert result.exit_code != 0
        assert "embed requires materialized chunks" in result.stdout
        assert f"run 'trailblazer chunk run {run_id}' first" in result.stdout

    @patch.dict(os.environ, {"TB_TESTING": "1"})
    def test_embed_load_fails_with_empty_chunks(self):
        """Test that embed load fails when chunks file is empty."""
        run_id = "test-run-empty-chunks"
        run_dir = self.create_test_run_without_chunks(run_id)

        # Create empty chunks file
        chunk_dir = run_dir / "chunk"
        chunk_dir.mkdir(parents=True, exist_ok=True)
        chunks_file = chunk_dir / "chunks.ndjson"
        chunks_file.write_text("")

        with patch("trailblazer.core.paths.runs") as mock_runs:
            mock_runs.return_value = self.temp_path / "runs"

            result = self.runner.invoke(
                app,
                [
                    "embed",
                    "load",
                    "--run-id",
                    run_id,
                    "--provider",
                    "dummy",
                ],
            )

        assert result.exit_code != 0
        assert "embed requires materialized chunks" in result.stdout
        assert "empty chunks file" in result.stdout

    @patch.dict(os.environ, {"TB_TESTING": "1"})
    @patch("trailblazer.pipeline.steps.embed.loader.get_session_factory")
    def test_embed_load_succeeds_with_chunks(self, mock_session_factory):
        """Test that embed load succeeds when chunks are materialized."""
        from unittest.mock import MagicMock

        # Mock database session
        mock_session = MagicMock()
        mock_session_factory.return_value.__enter__.return_value = mock_session
        mock_session.query.return_value.filter_by.return_value.first.return_value = None
        mock_session.get.return_value = None

        run_id = "test-run-with-chunks"
        self.create_test_run_with_chunks(run_id)

        with patch("trailblazer.core.paths.runs") as mock_runs:
            mock_runs.return_value = self.temp_path / "runs"

            result = self.runner.invoke(
                app,
                [
                    "embed",
                    "load",
                    "--run-id",
                    run_id,
                    "--provider",
                    "dummy",
                    "--max-chunks",
                    "1",
                ],
            )

        assert result.exit_code == 0
        assert "Loading embeddings from materialized chunks" in result.stderr

    def test_embed_validates_no_chunk_imports(self):
        """Test that embed validates no chunk imports at runtime."""
        import sys

        # Simulate chunk module being imported
        sys.modules["trailblazer.pipeline.steps.chunk.engine"] = MagicMock()

        try:
            from trailblazer.pipeline.steps.embed.loader import (
                _validate_no_chunk_imports,
            )

            with pytest.raises(RuntimeError) as exc_info:
                _validate_no_chunk_imports()

            assert "embed requires materialized chunks" in str(exc_info.value)
            assert "on-the-fly chunking is forbidden" in str(exc_info.value)
            assert "trailblazer.pipeline.steps.chunk.engine" in str(
                exc_info.value
            )

        finally:
            # Clean up
            if "trailblazer.pipeline.steps.chunk.engine" in sys.modules:
                del sys.modules["trailblazer.pipeline.steps.chunk.engine"]

    @patch.dict(os.environ, {"TB_TESTING": "1"})
    def test_embed_load_with_chunks_file_parameter(self):
        """Test that embed load works with --chunks-file parameter."""
        run_id = "test-run-chunks-file"
        run_dir = self.create_test_run_with_chunks(run_id)
        chunks_file = run_dir / "chunk" / "chunks.ndjson"

        with patch(
            "trailblazer.pipeline.steps.embed.loader.get_session_factory"
        ) as mock_session_factory:
            # Mock database session
            mock_session = MagicMock()
            mock_session_factory.return_value.__enter__.return_value = (
                mock_session
            )
            mock_session.query.return_value.filter_by.return_value.first.return_value = None
            mock_session.get.return_value = None

            result = self.runner.invoke(
                app,
                [
                    "embed",
                    "load",
                    "--chunks-file",
                    str(chunks_file),
                    "--provider",
                    "dummy",
                    "--max-chunks",
                    "1",
                ],
            )

        assert result.exit_code == 0
        assert "Loading embeddings from materialized chunks" in result.stderr

    def test_embed_contract_error_message_format(self):
        """Test that embed contract error messages are properly formatted."""
        from trailblazer.pipeline.steps.embed.loader import (
            _validate_materialized_chunks,
        )

        with patch("trailblazer.core.paths.runs") as mock_runs:
            mock_runs.return_value = self.temp_path / "runs"

            with pytest.raises(FileNotFoundError) as exc_info:
                _validate_materialized_chunks("non-existent-run")

            error_msg = str(exc_info.value)
            assert "embed requires materialized chunks" in error_msg
            assert (
                "run 'trailblazer chunk run non-existent-run' first"
                in error_msg
            )
            assert "missing:" in error_msg
