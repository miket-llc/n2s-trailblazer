"""Global test configuration for trailblazer tests."""

import os
import pytest


@pytest.fixture(autouse=True)
def enable_sqlite_for_tests():
    """Enable SQLite for all tests by setting the environment variable."""
    os.environ["TB_TESTING"] = "1"
    yield
    # Clean up after test (optional)
    if "TB_TESTING" in os.environ:
        del os.environ["TB_TESTING"]
