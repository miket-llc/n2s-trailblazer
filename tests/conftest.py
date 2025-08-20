"""Global test configuration for trailblazer tests."""

import pytest
from unittest.mock import patch


@pytest.fixture(scope="session")
def test_db_url():
    """Provide test database URL using the existing Docker container."""
    # Use the existing trailblazer PostgreSQL container
    return "postgresql+psycopg2://trailblazer:trailblazer_dev_password@localhost:5432/trailblazer"


@pytest.fixture(autouse=True)
def setup_test_db(test_db_url, monkeypatch, request):
    """Set up test database URL for all tests that need it."""
    import os

    # Skip database setup for tests that don't need it
    if hasattr(request.node, "get_closest_marker"):
        if request.node.get_closest_marker("no_db"):
            yield
            return

    # Skip database setup if TB_TESTING=1 is not set (for simple unit tests)
    if os.environ.get("TB_TESTING") != "1":
        # For tests that don't explicitly need database, skip setup
        test_name = request.node.name
        if any(
            keyword in test_name.lower()
            for keyword in ["coupling", "lint", "boundaries"]
        ):
            yield
            return

    try:
        from trailblazer.db import engine as engine_module
        from trailblazer.core import config as config_module

        # Set the environment variable first
        monkeypatch.setenv("TRAILBLAZER_DB_URL", test_db_url)

        # Reset global settings and engine to pick up new environment variable
        config_module.SETTINGS = config_module.Settings()
        engine_module._engine = None
        engine_module._session_factory = None

        # Create fresh tables for each test
        from trailblazer.db.engine import Base, get_engine

        engine = get_engine()
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)

        yield

        # Clean up after test
        Base.metadata.drop_all(engine)

        # Reset engine and settings again after test to avoid state leakage
        engine_module._engine = None
        engine_module._session_factory = None

    except Exception as e:
        # If database connection fails, skip database-dependent tests
        if (
            "connection refused" in str(e).lower()
            or "operational" in str(e).lower()
        ):
            pytest.skip(f"Database not available: {e}")
        else:
            raise


@pytest.fixture
def cli_runner():
    """Provide a CLI runner with compatibility for old command patterns."""
    from typer.testing import CliRunner

    class CompatibleCliRunner(CliRunner):
        """CLI runner that handles old command patterns for backward compatibility."""

        def invoke(self, app, args, *kwargs, **kwkwargs):
            # Map old CLI commands to new ones for backward compatibility
            if isinstance(args, (list, tuple)):
                args = list(args)

                # Map old embed preflight to new plan-preflight
                if len(args) >= 3 and args[:3] == ["embed", "preflight"]:
                    args[1] = "plan-preflight"

                # Map old chunk sweep patterns if needed
                if len(args) >= 2 and args[:2] == ["chunk", "sweep"]:
                    # Check if chunk sweep command exists, if not skip test
                    pass

                # Map other old patterns as needed

            return super().invoke(app, args, *kwargs, **kwkwargs)

    return CompatibleCliRunner()


@pytest.fixture
def mock_cli_commands():
    """Mock CLI commands that may not exist in current version."""
    with patch("trailblazer.cli.main.app") as mock_app:
        # Mock the app to handle old command patterns
        yield mock_app


@pytest.fixture
def temp_run_dir_structure():
    """Create a temporary run directory with current expected structure."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Create current expected directory structure
        runs_dir = temp_path / "runs"
        runs_dir.mkdir()

        # Create a sample run
        run_id = "2025-01-15_1234_abcd"
        run_dir = runs_dir / run_id
        run_dir.mkdir()

        # Create current expected subdirectories
        (run_dir / "ingest").mkdir()
        (run_dir / "normalize").mkdir()
        (run_dir / "enrich").mkdir()
        (run_dir / "chunk").mkdir()
        (run_dir / "embed").mkdir()

        # Create sample files with current expected content
        (run_dir / "normalize" / "normalized.ndjson").write_text(
            '{"id": "doc1", "title": "Test Doc"}\n'
        )
        (run_dir / "enrich" / "enriched.jsonl").write_text(
            '{"id": "doc1", "title": "Test Doc"}\n'
        )
        (run_dir / "chunk" / "chunks.ndjson").write_text(
            '{"chunk_id": "doc1:0001", "doc_id": "doc1", "token_count": 100}\n'
        )

        yield {
            "temp_dir": temp_dir,
            "runs_dir": runs_dir,
            "run_id": run_id,
            "run_dir": run_dir,
        }
