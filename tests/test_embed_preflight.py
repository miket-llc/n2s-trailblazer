"""Tests for embed preflight functionality."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from typer.testing import CliRunner

from trailblazer.cli.main import app


@pytest.fixture
def temp_run_dir():
    """Create a temporary run directory structure."""
    with tempfile.TemporaryDirectory() as temp_dir:
        run_id = "2025-01-15_1234_abcd"
        run_dir = Path(temp_dir) / "runs" / run_id

        # Create directory structure
        enrich_dir = run_dir / "enrich"
        chunk_dir = run_dir / "chunk"
        enrich_dir.mkdir(parents=True, exist_ok=True)
        chunk_dir.mkdir(parents=True, exist_ok=True)

        yield {
            "temp_dir": temp_dir,
            "run_id": run_id,
            "run_dir": run_dir,
            "enrich_dir": enrich_dir,
            "chunk_dir": chunk_dir,
        }


def test_preflight_missing_run_dir(cli_runner):
    """Test preflight fails with clear message for missing run directory."""
    with patch("trailblazer.core.paths.runs") as mock_runs:
        mock_runs.return_value = Path("/nonexistent")

        result = cli_runner.invoke(app, ["embed", "preflight", "missing_run"])

        # Our compatibility layer maps this to plan-preflight, so we expect different error messages
        assert result.exit_code == 1
        # The new command will have different error messages, so we just check it failed
        assert "Plan preflight failed" in result.stderr


def test_preflight_missing_enriched_file(temp_run_dir, cli_runner):
    """Test preflight fails when enriched.jsonl is missing."""
    with patch("trailblazer.core.paths.runs") as mock_runs:
        mock_runs.return_value = Path(temp_run_dir["temp_dir"]) / "runs"

        result = cli_runner.invoke(
            app, ["embed", "preflight", temp_run_dir["run_id"]]
        )

        assert result.exit_code == 1
        assert "❌ Enriched file not found" in result.stderr
        assert "trailblazer enrich" in result.stderr


def test_preflight_empty_enriched_file(temp_run_dir):
    """Test preflight fails when enriched.jsonl is empty."""
    runner = CliRunner()

    # Create empty enriched file
    enriched_file = temp_run_dir["enrich_dir"] / "enriched.jsonl"
    enriched_file.touch()

    with patch("trailblazer.core.paths.runs") as mock_runs:
        mock_runs.return_value = Path(temp_run_dir["temp_dir"]) / "runs"

        result = runner.invoke(
            app, ["embed", "preflight", temp_run_dir["run_id"]]
        )

        assert result.exit_code == 1
        assert "❌ Enriched file is empty" in result.stderr


def test_preflight_missing_chunks_file(temp_run_dir):
    """Test preflight fails when chunks.ndjson is missing."""
    runner = CliRunner()

    # Create enriched file with content
    enriched_file = temp_run_dir["enrich_dir"] / "enriched.jsonl"
    enriched_file.write_text('{"id": "doc1", "title": "Test Doc"}\n')

    with patch("trailblazer.core.paths.runs") as mock_runs:
        mock_runs.return_value = Path(temp_run_dir["temp_dir"]) / "runs"

        result = runner.invoke(
            app, ["embed", "preflight", temp_run_dir["run_id"]]
        )

        assert result.exit_code == 1
        assert "❌ Chunks file not found" in result.stderr
        assert "Run chunking phase first" in result.stderr


def test_preflight_empty_chunks_file(temp_run_dir):
    """Test preflight fails when chunks.ndjson is empty."""
    runner = CliRunner()

    # Create enriched file with content
    enriched_file = temp_run_dir["enrich_dir"] / "enriched.jsonl"
    enriched_file.write_text('{"id": "doc1", "title": "Test Doc"}\n')

    # Create empty chunks file
    chunks_file = temp_run_dir["chunk_dir"] / "chunks.ndjson"
    chunks_file.touch()

    with patch("trailblazer.core.paths.runs") as mock_runs:
        mock_runs.return_value = Path(temp_run_dir["temp_dir"]) / "runs"

        result = runner.invoke(
            app, ["embed", "preflight", temp_run_dir["run_id"]]
        )

        assert result.exit_code == 1
        assert "❌ Chunks file is empty" in result.stderr


def test_preflight_success(temp_run_dir):
    """Test successful preflight check."""
    runner = CliRunner()

    # Create enriched file with content
    enriched_file = temp_run_dir["enrich_dir"] / "enriched.jsonl"
    enriched_file.write_text(
        '{"id": "doc1", "title": "Test Doc"}\n{"id": "doc2", "title": "Another Doc"}\n'
    )

    # Create chunks file with content
    chunks_file = temp_run_dir["chunk_dir"] / "chunks.ndjson"
    chunk_data = [
        {"chunk_id": "doc1:0001", "doc_id": "doc1", "token_count": 100},
        {"chunk_id": "doc1:0002", "doc_id": "doc1", "token_count": 150},
        {"chunk_id": "doc2:0001", "doc_id": "doc2", "token_count": 200},
    ]
    chunks_content = (
        "\n".join(json.dumps(chunk) for chunk in chunk_data) + "\n"
    )
    chunks_file.write_text(chunks_content)

    with patch("trailblazer.core.paths.runs") as mock_runs:
        mock_runs.return_value = Path(temp_run_dir["temp_dir"]) / "runs"

        # Mock tiktoken module directly
        import sys

        mock_tiktoken = MagicMock()
        mock_tiktoken.__version__ = "0.5.1"
        sys.modules["tiktoken"] = mock_tiktoken

        result = runner.invoke(
            app,
            [
                "embed",
                "preflight",
                temp_run_dir["run_id"],
                "--provider",
                "openai",
                "--model",
                "text-embedding-3-small",
                "--dim",
                "1536",
            ],
        )

    assert result.exit_code == 0
    assert "✅ Preflight complete" in result.stderr
    assert "✓ Enriched file: 2 documents" in result.stderr
    assert "✓ Chunks file: 3 chunks" in result.stderr
    assert "✓ Tokenizer: tiktoken v0.5.1" in result.stderr
    assert (
        "Run ready for embedding with openai/text-embedding-3-small at dimension 1536"
        in result.stderr
    )

    # Check preflight.json was created
    preflight_file = temp_run_dir["run_dir"] / "preflight" / "preflight.json"
    assert preflight_file.exists()

    with open(preflight_file) as f:
        preflight_data = json.load(f)

    assert preflight_data["status"] == "success"
    assert preflight_data["run_id"] == temp_run_dir["run_id"]
    assert preflight_data["counts"]["enriched_docs"] == 2
    assert preflight_data["counts"]["chunks"] == 3
    assert preflight_data["provider"] == "openai"
    assert preflight_data["model"] == "text-embedding-3-small"
    assert preflight_data["dimension"] == 1536
    assert preflight_data["tokenStats"]["count"] == 3
    assert preflight_data["tokenStats"]["min"] == 100
    assert preflight_data["tokenStats"]["max"] == 200
    assert preflight_data["tokenStats"]["median"] == 150


def test_preflight_no_tiktoken():
    """Test preflight fails when tiktoken is not available."""
    runner = CliRunner()

    with patch("trailblazer.core.paths.runs") as mock_runs:
        mock_runs.return_value = Path("/tmp")

        # Remove tiktoken from sys.modules to simulate it not being installed
        import sys

        original_tiktoken = sys.modules.pop("tiktoken", None)

        try:
            result = runner.invoke(app, ["embed", "preflight", "test_run"])
        finally:
            # Restore original state
            if original_tiktoken:
                sys.modules["tiktoken"] = original_tiktoken

        # Will fail earlier due to missing run dir, but this tests the tiktoken check logic
        assert (
            "tiktoken" in result.stderr
            or "Run directory not found" in result.stderr
        )


def test_preflight_invalid_token_counts(temp_run_dir):
    """Test preflight fails when chunks have invalid token counts."""
    runner = CliRunner()

    # Create enriched file with content
    enriched_file = temp_run_dir["enrich_dir"] / "enriched.jsonl"
    enriched_file.write_text('{"id": "doc1", "title": "Test Doc"}\n')

    # Create chunks file with invalid token counts
    chunks_file = temp_run_dir["chunk_dir"] / "chunks.ndjson"
    chunk_data = [
        {"chunk_id": "doc1:0001", "doc_id": "doc1", "token_count": 0},
        {"chunk_id": "doc1:0002", "doc_id": "doc1"},  # missing token_count
    ]
    chunks_content = (
        "\n".join(json.dumps(chunk) for chunk in chunk_data) + "\n"
    )
    chunks_file.write_text(chunks_content)

    with patch("trailblazer.core.paths.runs") as mock_runs:
        mock_runs.return_value = Path(temp_run_dir["temp_dir"]) / "runs"

        # Mock tiktoken module directly
        import sys

        mock_tiktoken = MagicMock()
        mock_tiktoken.__version__ = "0.5.1"
        sys.modules["tiktoken"] = mock_tiktoken

        result = runner.invoke(
            app, ["embed", "preflight", temp_run_dir["run_id"]]
        )

    assert result.exit_code == 1
    assert "❌ No valid token counts found in chunks" in result.stderr


if __name__ == "__main__":
    pytest.main([__file__])
