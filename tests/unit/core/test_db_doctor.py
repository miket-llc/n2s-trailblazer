"""Test database doctor command functionality."""

import os
import pytest
from unittest.mock import patch
from typer.testing import CliRunner

from trailblazer.cli.main import app

# Mark all tests in this file as unit tests
pytestmark = pytest.mark.unit


def test_db_doctor_postgres_healthy():
    """Test db doctor with healthy PostgreSQL and pgvector."""
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
            return_value="postgresql://user:***@localhost:5432/test_db",
        ):
            with patch("trailblazer.db.engine.get_session") as mock_session:
                # Mock the session and query result for embedding dimensions
                mock_session.return_value.__enter__.return_value.execute.return_value = []

                runner = CliRunner()
                result = runner.invoke(app, ["db", "doctor"])

                assert result.exit_code == 0
                assert (
                    "Database Doctor - Comprehensive Health Check"
                    in result.stdout
                )
                assert "Connection successful!" in result.stdout
                assert "PostgreSQL-specific checks:" in result.stdout
                assert "pgvector extension: available" in result.stdout
                assert (
                    "Database health check completed successfully!"
                    in result.stdout
                )


def test_db_doctor_postgres_missing_pgvector():
    """Test db doctor with PostgreSQL but missing pgvector."""
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
            return_value="postgresql://user:***@localhost:5432/test_db",
        ):
            runner = CliRunner()
            result = runner.invoke(app, ["db", "doctor"])

            assert result.exit_code == 1
            assert "pgvector extension: NOT available" in result.stdout
            assert "Run 'trailblazer db init' or manually:" in result.stdout


def test_db_doctor_sqlite_in_test_mode():
    """Test db doctor with SQLite (should be rejected)."""
    mock_health_info = {
        "status": "ok",
        "dialect": "sqlite",
        "database": "test.db",
        "pgvector": False,
        "host": "localhost",
    }

    with patch(
        "trailblazer.db.engine.check_db_health", return_value=mock_health_info
    ):
        with patch(
            "trailblazer.db.engine.get_db_url",
            return_value="sqlite:///test.db",
        ):
            # TB_TESTING should be set by conftest.py, but let's be explicit
            with patch.dict(os.environ, {"TB_TESTING": "1"}):
                runner = CliRunner()
                result = runner.invoke(app, ["db", "doctor"])

                assert result.exit_code == 1
                assert "Unsupported database: sqlite" in result.stdout


def test_db_doctor_sqlite_in_production_mode():
    """Test db doctor with SQLite (should also be rejected)."""
    mock_health_info = {
        "status": "ok",
        "dialect": "sqlite",
        "database": "test.db",
        "pgvector": False,
        "host": "localhost",
    }

    with patch(
        "trailblazer.db.engine.check_db_health", return_value=mock_health_info
    ):
        with patch(
            "trailblazer.db.engine.get_db_url",
            return_value="sqlite:///test.db",
        ):
            # Remove TB_TESTING to simulate production mode
            with patch.dict(os.environ, {}, clear=True):
                runner = CliRunner()
                result = runner.invoke(app, ["db", "doctor"])

                assert result.exit_code == 1
                assert "Unsupported database: sqlite" in result.stdout


def test_db_doctor_connection_failure():
    """Test db doctor when database connection fails."""
    with patch(
        "trailblazer.db.engine.check_db_health",
        side_effect=Exception("Connection refused"),
    ):
        with patch(
            "trailblazer.db.engine.get_db_url",
            return_value="postgresql://user:***@localhost:5432/test_db",
        ):
            runner = CliRunner()
            result = runner.invoke(app, ["db", "doctor"])

            assert result.exit_code == 1
            assert (
                "Database doctor failed: Connection refused" in result.stderr
            )
            assert (
                "1. Check TRAILBLAZER_DB_URL in your .env file"
                in result.stdout
            )


def test_db_doctor_with_embedding_dimensions():
    """Test db doctor showing existing embedding dimensions."""
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
            return_value="postgresql://user:***@localhost:5432/test_db",
        ):
            with patch("trailblazer.db.engine.get_session") as mock_session:
                # Mock finding some embedding dimensions
                mock_result = mock_session.return_value.__enter__.return_value.execute.return_value
                mock_result.__iter__.return_value = [(384,), (768,)]

                runner = CliRunner()
                result = runner.invoke(app, ["db", "doctor"])

                assert result.exit_code == 0
                assert (
                    "Embedding dimensions found: [384, 768]" in result.stdout
                )
