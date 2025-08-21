# Test constants for magic numbers
EXPECTED_COUNT_2 = 2
EXPECTED_COUNT_3 = 3
EXPECTED_COUNT_4 = 4

import pytest

from trailblazer.core.artifacts import new_run_id

# Mark all tests as unit tests (no database needed)
pytestmark = pytest.mark.unit


def test_run_id_shape():
    rid = new_run_id()
    assert "_" in rid and len(rid.split("_")[-1]) == 4
