"""Global test configuration for trailblazer tests."""

import os
import pytest


@pytest.fixture(autouse=True)
def enable_sqlite_for_tests():
    """Enable SQLite for all tests by setting the environment variable."""
    os.environ["ALLOW_SQLITE_FOR_TESTS"] = "1"
    yield
    # Clean up after test (optional)
    if "ALLOW_SQLITE_FOR_TESTS" in os.environ:
        del os.environ["ALLOW_SQLITE_FOR_TESTS"]
