"""Global test configuration for trailblazer tests."""

import pytest
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def postgres_container():
    """Provide a PostgreSQL container for testing."""
    with PostgresContainer(
        "postgres:15-alpine",
        username="test",
        password="test",
        dbname="test",
    ) as postgres:
        # Install pgvector extension
        postgres.exec(
            "psql -U test -d test -c 'CREATE EXTENSION IF NOT EXISTS vector;'"
        )
        yield postgres


@pytest.fixture(scope="session")
def test_db_url(postgres_container):
    """Provide test database URL."""
    return postgres_container.get_connection_url()


@pytest.fixture(autouse=True)
def setup_test_db(test_db_url, monkeypatch):
    """Set up test database URL for all tests."""
    from trailblazer.db.engine import Base, get_engine

    monkeypatch.setenv("TRAILBLAZER_DB_URL", test_db_url)

    # Create fresh tables for each test
    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    yield

    # Clean up after test
    Base.metadata.drop_all(engine)
