"""Global test configuration for trailblazer tests."""

import pytest


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
