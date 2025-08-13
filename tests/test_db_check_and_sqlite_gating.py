"""Test database check functionality and SQLite gating."""

import os
import tempfile
from unittest.mock import patch
from typer.testing import CliRunner

import pytest
from sqlalchemy import create_engine

from trailblazer.cli.main import app
from trailblazer.db.engine import Base, check_db_health


def test_db_check_with_postgres_and_pgvector():
    """Test db check with PostgreSQL and pgvector available."""
    mock_health_info = {
        "status": "ok",
        "dialect": "postgresql",
        "database": "test_db",
        "pgvector": True,
        "host": "localhost",
    }

    with patch(
        "trailblazer.db.engine.check_db_health", return_value=mock_health_info
    ):
        with patch(
            "trailblazer.db.engine.get_db_url",
            return_value="postgresql://user:pass@localhost/test",
        ):
            runner = CliRunner()
            result = runner.invoke(app, ["db", "check"])

            assert result.exit_code == 0
            assert "Database connection successful" in result.stdout
            assert "Engine: postgresql" in result.stdout
            assert "pgvector: ✅ available" in result.stdout


def test_db_check_with_postgres_missing_pgvector():
    """Test db check with PostgreSQL but missing pgvector."""
    mock_health_info = {
        "status": "ok",
        "dialect": "postgresql",
        "database": "test_db",
        "pgvector": False,
        "host": "localhost",
    }

    with patch(
        "trailblazer.db.engine.check_db_health", return_value=mock_health_info
    ):
        with patch(
            "trailblazer.db.engine.get_db_url",
            return_value="postgresql://user:pass@localhost/test",
        ):
            runner = CliRunner()
            result = runner.invoke(app, ["db", "check"])

            assert result.exit_code == 1
            assert "pgvector: ❌ not available" in result.stdout
            assert "pgvector extension not found" in result.stderr


def test_sqlite_gating_without_env_var():
    """Test that SQLite usage fails without TB_TESTING=1."""
    # Remove the environment variable if it exists
    old_val = os.environ.pop("TB_TESTING", None)

    try:
        with tempfile.NamedTemporaryFile(suffix=".db") as f:
            db_url = f"sqlite:///{f.name}"

            with patch(
                "trailblazer.db.engine.get_db_url", return_value=db_url
            ):
                # Clear any cached engine to force fresh evaluation
                import trailblazer.db.engine

                trailblazer.db.engine._engine = None
                trailblazer.db.engine._session_factory = None

                from trailblazer.db.engine import get_engine

                with pytest.raises(
                    ValueError, match="SQLite is only allowed for tests"
                ):
                    get_engine()
    finally:
        # Restore the environment variable
        if old_val is not None:
            os.environ["TB_TESTING"] = old_val


def test_sqlite_gating_with_env_var():
    """Test that SQLite usage works with TB_TESTING=1."""
    # Ensure the environment variable is set
    os.environ["TB_TESTING"] = "1"

    try:
        with tempfile.NamedTemporaryFile(suffix=".db") as f:
            db_url = f"sqlite:///{f.name}"

            with patch(
                "trailblazer.db.engine.get_db_url", return_value=db_url
            ):
                # Clear any cached engine to force fresh evaluation
                import trailblazer.db.engine

                trailblazer.db.engine._engine = None
                trailblazer.db.engine._session_factory = None

                from trailblazer.db.engine import get_engine

                # This should not raise an exception
                engine = get_engine()
                assert engine is not None
                assert "sqlite" in str(engine.url)

    finally:
        pass  # The conftest.py fixture will handle cleanup


def test_embed_load_requires_postgres_without_test_env():
    """Test that embed load fails with SQLite when not in test environment."""
    with patch(
        "trailblazer.db.engine.get_db_url", return_value="sqlite:///test.db"
    ):
        with patch(
            "trailblazer.db.engine.get_engine",
            side_effect=ValueError(
                "SQLite is only allowed for tests. Set TB_TESTING=1 for tests, "
                "or configure TRAILBLAZER_DB_URL with PostgreSQL for production use. "
                "Run 'make db.up' then 'trailblazer db doctor' to get started."
            ),
        ):
            runner = CliRunner()
            result = runner.invoke(
                app,
                [
                    "embed",
                    "load",
                    "--run-id",
                    "test-run",
                    "--provider",
                    "dummy",
                ],
            )

            assert result.exit_code == 1
            assert "Database preflight failed" in result.stderr
            assert "SQLite is only allowed for tests" in result.stderr


def test_ask_requires_postgres_without_test_env():
    """Test that ask command fails with SQLite when not in test environment."""
    with patch(
        "trailblazer.db.engine.get_db_url", return_value="sqlite:///test.db"
    ):
        with patch(
            "trailblazer.db.engine.get_engine",
            side_effect=ValueError(
                "SQLite is only allowed for tests. Set TB_TESTING=1 for tests, "
                "or configure TRAILBLAZER_DB_URL with PostgreSQL for production use. "
                "Run 'make db.up' then 'trailblazer db doctor' to get started."
            ),
        ):
            runner = CliRunner()
            result = runner.invoke(
                app, ["ask", "What is SSO?", "--provider", "dummy"]
            )

            assert result.exit_code == 1
            assert "Database preflight failed" in result.stderr
            assert "SQLite is only allowed for tests" in result.stderr


def test_check_db_health_sqlite():
    """Test check_db_health function with SQLite."""
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        db_url = f"sqlite:///{f.name}"
        engine = create_engine(db_url)
        Base.metadata.create_all(engine)

        with patch("trailblazer.db.engine.get_engine", return_value=engine):
            with patch(
                "trailblazer.db.engine.get_db_url", return_value=db_url
            ):
                health_info = check_db_health()

                assert health_info["status"] == "ok"
                assert health_info["dialect"] == "sqlite"
                assert health_info["pgvector"] is False
                assert "host" in health_info


def test_check_db_health_postgres_mock():
    """Test check_db_health function with mock PostgreSQL."""
    # Create a mock engine with PostgreSQL dialect
    mock_engine = patch("trailblazer.db.engine.get_engine")

    with mock_engine as mock_get_engine:
        # Configure the mock engine
        engine_instance = mock_get_engine.return_value
        engine_instance.dialect.name = "postgresql"

        # Mock the connection and execution
        mock_conn = engine_instance.connect.return_value.__enter__.return_value

        # Mock the pgvector extension check
        mock_result = mock_conn.execute.return_value
        mock_result.fetchone.return_value = ("vector",)

        with patch(
            "trailblazer.db.engine.get_db_url",
            return_value="postgresql://user:pass@localhost:5432/testdb",
        ):
            health_info = check_db_health()

            assert health_info["status"] == "ok"
            assert health_info["dialect"] == "postgresql"
            assert health_info["database"] == "testdb"
            assert health_info["host"] == "localhost"
            assert health_info["pgvector"] is True
