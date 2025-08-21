import pytest

# Mark all tests as unit tests (no database needed)
pytestmark = pytest.mark.unit


def test_placeholder():
    assert 1 == 1
