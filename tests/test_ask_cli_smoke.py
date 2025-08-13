"""Smoke test for the ask CLI command."""

import json
import tempfile
from pathlib import Path
from datetime import datetime

import pytest
from typer.testing import CliRunner
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from trailblazer.cli.main import app
from trailblazer.db.engine import Base, Document, Chunk, ChunkEmbedding


@pytest.fixture
def test_db_with_data():
    """Create a test database with sample data."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    db_url = f"sqlite:///{db_path}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)
    session = Session()

    # Add test document
    doc = Document(
        doc_id="test_doc_001",
        source="test",
        title="Test Guide: How to Configure SSO",
        url="http://example.com/sso-guide",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        body_repr="storage",
        meta={"space": "TEST"},
    )
    session.add(doc)

    # Add test chunks
    chunks = [
        Chunk(
            chunk_id="test_doc_001:0001",
            doc_id="test_doc_001",
            ord=1,
            text_md="# SSO Configuration\n\nTo configure Single Sign-On (SSO) in your application, follow these steps:",
            char_count=92,
            token_count=18,
        ),
        Chunk(
            chunk_id="test_doc_001:0002",
            doc_id="test_doc_001",
            ord=2,
            text_md="## Step 1: SAML Setup\n\nFirst, configure your SAML provider settings in the admin panel.",
            char_count=88,
            token_count=17,
        ),
        Chunk(
            chunk_id="test_doc_001:0003",
            doc_id="test_doc_001",
            ord=3,
            text_md="## Step 2: User Mapping\n\nMap user attributes from your identity provider to application fields.",
            char_count=94,
            token_count=16,
        ),
    ]
    session.add_all(chunks)

    # Add dummy embeddings
    for chunk in chunks:
        # Create simple deterministic embeddings
        text_hash = hash(chunk.text_md) % 1000
        # Create 384-dimensional embedding to match dummy provider
        embedding = []
        for i in range(384):
            val = 0.5 + ((text_hash + i) % 100) * 0.001  # 0.5 to 0.599
            embedding.append(val)

        chunk_emb = ChunkEmbedding(
            chunk_id=chunk.chunk_id,
            provider="dummy",
            dim=384,
            embedding=embedding,
        )
        session.add(chunk_emb)

    session.commit()
    session.close()

    yield db_url

    # Cleanup
    Path(db_path).unlink(missing_ok=True)


def test_ask_cli_basic_functionality(test_db_with_data):
    """Test basic ask CLI functionality."""
    runner = CliRunner()

    with tempfile.TemporaryDirectory() as temp_dir:
        result = runner.invoke(
            app,
            [
                "ask",
                "How do I configure SSO?",
                "--provider",
                "dummy",
                "--db-url",
                test_db_with_data,
                "--out",
                temp_dir,
                "--top-k",
                "3",
            ],
        )

        # Command should succeed
        assert result.exit_code == 0

        # Check that output mentions the question
        assert "How do I configure SSO?" in result.stdout
        assert "Provider: dummy" in result.stdout
        assert "✅ Artifacts written to:" in result.stdout

        # Check that artifact files are created
        out_path = Path(temp_dir)
        assert (out_path / "hits.jsonl").exists()
        assert (out_path / "summary.json").exists()
        assert (out_path / "context.txt").exists()

        # Verify hits.jsonl content
        with open(out_path / "hits.jsonl") as f:
            hits = [json.loads(line) for line in f]

        assert len(hits) == 3  # All chunks should be returned

        # Each hit should have required fields
        for hit in hits:
            assert "chunk_id" in hit
            assert "doc_id" in hit
            assert "text_md" in hit
            assert "title" in hit
            assert "url" in hit
            assert "score" in hit
            assert hit["doc_id"] == "test_doc_001"
            assert hit["title"] == "Test Guide: How to Configure SSO"

        # Verify summary.json content
        with open(out_path / "summary.json") as f:
            summary = json.load(f)

        assert summary["query"] == "How do I configure SSO?"
        assert summary["provider"] == "dummy"
        assert summary["total_hits"] == 3
        assert summary["unique_documents"] == 1
        assert "timing" in summary
        assert "score_stats" in summary

        # Verify context.txt content
        with open(out_path / "context.txt") as f:
            context = f.read()

        assert "SSO Configuration" in context
        assert "SAML Setup" in context
        assert "User Mapping" in context
        assert "score:" in context  # Should have score info


def test_ask_cli_json_output(test_db_with_data):
    """Test ask CLI with JSON output format."""
    runner = CliRunner()

    with tempfile.TemporaryDirectory() as temp_dir:
        result = runner.invoke(
            app,
            [
                "ask",
                "SAML configuration steps",
                "--provider",
                "dummy",
                "--db-url",
                test_db_with_data,
                "--out",
                temp_dir,
                "--format",
                "json",
            ],
        )

        assert result.exit_code == 0

        # Output should be valid JSON
        try:
            output_json = json.loads(
                result.stdout.split("\n")[-2]
            )  # Last non-empty line before artifacts message
            assert "query" in output_json
            assert "total_hits" in output_json
            assert "provider" in output_json
        except (json.JSONDecodeError, IndexError):
            # JSON might be mixed with other output, check that JSON-like content exists
            assert '"query"' in result.stdout
            assert '"total_hits"' in result.stdout


def test_ask_cli_with_limits(test_db_with_data):
    """Test ask CLI with various limits."""
    runner = CliRunner()

    with tempfile.TemporaryDirectory() as temp_dir:
        result = runner.invoke(
            app,
            [
                "ask",
                "configuration guide",
                "--provider",
                "dummy",
                "--db-url",
                test_db_with_data,
                "--out",
                temp_dir,
                "--top-k",
                "2",
                "--max-chunks-per-doc",
                "1",
                "--max-chars",
                "500",
            ],
        )

        assert result.exit_code == 0

        # Check hits file has correct number of results
        out_path = Path(temp_dir)
        with open(out_path / "hits.jsonl") as f:
            hits = [json.loads(line) for line in f]

        # With max-chunks-per-doc=1, should have at most 1 chunk per doc
        doc_counts = {}
        for hit in hits:
            doc_id = hit["doc_id"]
            doc_counts[doc_id] = doc_counts.get(doc_id, 0) + 1

        for count in doc_counts.values():
            assert count <= 1

        # Check context file respects character limit
        with open(out_path / "context.txt") as f:
            context = f.read()

        # Context should be reasonably close to limit (allowing for separators)
        # But this is approximate due to separator overhead
        assert len(context) <= 800  # Some buffer for separators


def test_ask_cli_no_results():
    """Test ask CLI behavior when no results are found."""
    # Create empty database
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    db_url = f"sqlite:///{db_path}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    try:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = runner.invoke(
                app,
                [
                    "ask",
                    "nonexistent query",
                    "--provider",
                    "dummy",
                    "--db-url",
                    db_url,
                    "--out",
                    temp_dir,
                ],
            )

            # Should exit with error
            assert result.exit_code == 1
            assert "No results found" in result.stdout

    finally:
        Path(db_path).unlink(missing_ok=True)


def test_ask_cli_default_output_dir(test_db_with_data):
    """Test that default output directory is created correctly."""
    runner = CliRunner()

    # Don't specify --out, should use default runs/<run_id>/ask/
    result = runner.invoke(
        app,
        [
            "ask",
            "SSO setup",
            "--provider",
            "dummy",
            "--db-url",
            test_db_with_data,
        ],
    )

    assert result.exit_code == 0

    # Should mention where artifacts were written
    assert "Artifacts written to:" in result.stdout

    # Extract the path from output
    output_lines = result.stdout.split("\n")
    artifacts_line = [
        line for line in output_lines if "Artifacts written to:" in line
    ][0]
    out_path = Path(artifacts_line.split("Artifacts written to: ")[1])

    # Should be under runs/ directory
    assert "runs" in str(out_path)
    assert "ask" in str(out_path)

    # Files should exist
    assert (out_path / "hits.jsonl").exists()
    assert (out_path / "summary.json").exists()
    assert (out_path / "context.txt").exists()


def test_ask_cli_score_ordering(test_db_with_data):
    """Test that results are properly ordered by score."""
    runner = CliRunner()

    with tempfile.TemporaryDirectory() as temp_dir:
        result = runner.invoke(
            app,
            [
                "ask",
                "configuration SSO SAML",  # Query that should match different chunks differently
                "--provider",
                "dummy",
                "--db-url",
                test_db_with_data,
                "--out",
                temp_dir,
            ],
        )

        assert result.exit_code == 0

        # Load hits and verify ordering
        out_path = Path(temp_dir)
        with open(out_path / "hits.jsonl") as f:
            hits = [json.loads(line) for line in f]

        # Scores should be in descending order
        scores = [hit["score"] for hit in hits]
        assert scores == sorted(scores, reverse=True)

        # All scores should be between 0 and 1
        for score in scores:
            assert 0.0 <= score <= 1.0
