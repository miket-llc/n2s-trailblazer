"""Tests for the ask CLI command."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from typer.testing import CliRunner

from trailblazer.cli.main import app
from trailblazer.pipeline.steps.retrieve.retriever import SearchHit

# Mark all tests in this file as integration tests (need database)
pytestmark = pytest.mark.integration


runner = CliRunner()


@pytest.fixture
def mock_search_hits():
    """Mock search hits for testing."""
    return [
        SearchHit(
            chunk_id="test:0000",
            doc_id="test",
            title="Test Document",
            url="http://test.com",
            text_md="This is test content about testing.",
            score=0.95,
            source_system="confluence",
        ),
        SearchHit(
            chunk_id="test:0001",
            doc_id="test",
            title="Test Document",
            url="http://test.com",
            text_md="More test content with additional information.",
            score=0.85,
            source_system="confluence",
        ),
    ]


def test_ask_help():
    """Test ask command help text."""
    result = runner.invoke(app, ["ask", "--help"])
    assert result.exit_code == 0
    assert "Ask a question using dense retrieval" in result.output
    assert "--top-k" in result.output
    assert "--max-chunks-per-doc" in result.output
    assert "--provider" in result.output
    assert "--max-chars" in result.output
    assert "--format" in result.output


def test_ask_requires_db_url():
    """Test that ask command requires database URL."""
    with patch.dict(os.environ, {}, clear=True):
        result = runner.invoke(app, ["ask", "test question"])
        assert result.exit_code == 1
        assert "TRAILBLAZER_DB_URL required" in result.output


def test_ask_smoke_test_with_mocked_retriever(mock_search_hits):
    """Smoke test for ask command with mocked retriever."""
    with tempfile.TemporaryDirectory() as temp_dir:
        with patch("trailblazer.cli.main._run_db_preflight_check"):
            with patch(
                "trailblazer.retrieval.dense.create_retriever"
            ) as mock_create_retriever:
                mock_retriever = MagicMock()
                mock_retriever.search.return_value = [
                    {
                        "chunk_id": hit.chunk_id,
                        "doc_id": hit.doc_id,
                        "text_md": hit.text_md,
                        "title": hit.title,
                        "url": hit.url,
                        "score": hit.score,
                    }
                    for hit in mock_search_hits
                ]
                mock_create_retriever.return_value = mock_retriever

                result = runner.invoke(
                    app,
                    [
                        "ask",
                        "test question",
                        "--out",
                        temp_dir,
                        "--db-url",
                        "postgresql://test:test@localhost:5432/test",
                    ],
                )

                assert result.exit_code == 0

                # Check that artifacts were created
                output_path = Path(temp_dir)
                assert (output_path / "hits.jsonl").exists()
                assert (output_path / "summary.json").exists()
                assert (output_path / "context.txt").exists()

                # Check hits.jsonl content
                with open(output_path / "hits.jsonl") as f:
                    hits_lines = f.readlines()
                    assert len(hits_lines) == 2
                    hit1 = json.loads(hits_lines[0])
                    assert hit1["chunk_id"] == "test:0000"
                    assert hit1["score"] == 0.95

                    # Check summary.json content
                    with open(output_path / "summary.json") as f:
                        summary = json.load(f)
                        assert summary["query"] == "test question"
                        assert summary["provider"] == "dummy"
                        assert summary["total_hits"] == 2
                        assert summary["unique_documents"] == 1
                        assert "timing" in summary

                    # Check context.txt exists and has content
                    with open(output_path / "context.txt") as f:
                        context = f.read()
                        assert "Test Document" in context
                        assert "test content" in context


def test_ask_json_format(mock_search_hits):
    """Test ask command with JSON output format."""
    with tempfile.TemporaryDirectory() as temp_dir:
        with patch("trailblazer.cli.main._run_db_preflight_check"):
            with patch(
                "trailblazer.retrieval.dense.create_retriever"
            ) as mock_create_retriever:
                mock_retriever = MagicMock()
                mock_retriever.search.return_value = [
                    {
                        "chunk_id": hit.chunk_id,
                        "doc_id": hit.doc_id,
                        "text_md": hit.text_md,
                        "title": hit.title,
                        "url": hit.url,
                        "score": hit.score,
                    }
                    for hit in mock_search_hits
                ]
                mock_create_retriever.return_value = mock_retriever

                result = runner.invoke(
                    app,
                    [
                        "ask",
                        "test question",
                        "--format",
                        "json",
                        "--out",
                        temp_dir,
                        "--db-url",
                        "postgresql://test:test@localhost:5432/test",
                    ],
                )

                assert result.exit_code == 0
                # When format is json, summary should be in stderr
                assert (
                    "query" in result.stderr
                    or "test question" in result.stderr
                )


def test_ask_no_results(mock_search_hits):
    """Test ask command when no results are found."""
    with tempfile.TemporaryDirectory() as temp_dir:
        with patch("trailblazer.cli.main._run_db_preflight_check"):
            with patch(
                "trailblazer.retrieval.dense.create_retriever"
            ) as mock_create_retriever:
                mock_retriever = MagicMock()
                mock_retriever.search.return_value = []  # No results
                mock_create_retriever.return_value = mock_retriever

                result = runner.invoke(
                    app,
                    [
                        "ask",
                        "test question",
                        "--out",
                        temp_dir,
                        "--db-url",
                        "postgresql://test:test@localhost:5432/test",
                    ],
                )

                assert result.exit_code == 1
                assert "No results found" in result.output


def test_ask_ndjson_events(mock_search_hits):
    """Test that ask command emits proper NDJSON events."""
    with tempfile.TemporaryDirectory() as temp_dir:
        with patch("trailblazer.cli.main._run_db_preflight_check"):
            with patch(
                "trailblazer.retrieval.dense.create_retriever"
            ) as mock_create_retriever:
                mock_retriever = MagicMock()
                mock_retriever.search.return_value = [
                    {
                        "chunk_id": hit.chunk_id,
                        "doc_id": hit.doc_id,
                        "text_md": hit.text_md,
                        "title": hit.title,
                        "url": hit.url,
                        "score": hit.score,
                    }
                    for hit in mock_search_hits
                ]
                mock_create_retriever.return_value = mock_retriever

                result = runner.invoke(
                    app,
                    [
                        "ask",
                        "test question",
                        "--out",
                        temp_dir,
                        "--db-url",
                        "postgresql://test:test@localhost:5432/test",
                    ],
                )

                assert result.exit_code == 0

                # Parse NDJSON events from stdout
                events = []
                for line in result.stdout.strip().split("\n"):
                    if line.strip():
                        try:
                            events.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass  # Skip non-JSON lines

                # Should have multiple events
                assert len(events) >= 3

                # Find specific event types
                event_types = [event.get("event") for event in events]
                assert "ask.start" in event_types
                assert "ask.complete" in event_types

                # Check ask.start event has required fields
                start_event = next(
                    e for e in events if e.get("event") == "ask.start"
                )
                assert start_event["question"] == "test question"
                assert start_event["provider"] == "dummy"
                assert "run_id" in start_event
                assert "timestamp" in start_event


def test_ask_custom_parameters(mock_search_hits):
    """Test ask command with custom parameters."""
    with tempfile.TemporaryDirectory() as temp_dir:
        with patch("trailblazer.cli.main._run_db_preflight_check"):
            with patch(
                "trailblazer.retrieval.dense.create_retriever"
            ) as mock_create_retriever:
                mock_retriever = MagicMock()
                mock_retriever.search.return_value = [
                    {
                        "chunk_id": hit.chunk_id,
                        "doc_id": hit.doc_id,
                        "text_md": hit.text_md,
                        "title": hit.title,
                        "url": hit.url,
                        "score": hit.score,
                    }
                    for hit in mock_search_hits
                ]
                mock_create_retriever.return_value = mock_retriever

                result = runner.invoke(
                    app,
                    [
                        "ask",
                        "test question",
                        "--top-k",
                        "5",
                        "--max-chunks-per-doc",
                        "2",
                        "--provider",
                        "openai",
                        "--max-chars",
                        "3000",
                        "--out",
                        temp_dir,
                        "--db-url",
                        "postgresql://test:test@localhost:5432/test",
                    ],
                )

                assert result.exit_code == 0

                # Verify retriever was called with correct parameters
                mock_retriever.search.assert_called_once()
                call_args = mock_retriever.search.call_args
                # Check that search was called with the question and emit_event
                assert len(call_args[0]) >= 1  # At least the question argument
                assert call_args[1]["top_k"] == 5  # top_k parameter

                # Verify retriever was initialized with correct provider
                mock_create_retriever.assert_called_once()
                init_call = mock_create_retriever.call_args
                assert init_call[1]["provider_name"] == "openai"
