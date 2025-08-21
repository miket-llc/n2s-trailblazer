# Test constants for magic numbers
EXPECTED_COUNT_2 = 2
EXPECTED_COUNT_3 = 3
EXPECTED_COUNT_4 = 4

import pytest

from trailblazer.adapters.confluence_api import ConfluenceClient

# Mark all tests as unit tests (no database needed)
pytestmark = pytest.mark.unit


def test_next_link_parsing(monkeypatch):
    c = ConfluenceClient(base_url="https://example.atlassian.net/wiki", email="e", token="t")

    # simulate response with _links.next
    class FakeResp:
        headers = {}

        def json(self):
            return {
                "results": [{"id": "1"}],
                "_links": {"next": "https://example.atlassian.net/wiki/api/v2/pages?cursor=abc"},
            }

    nxt = c._next_link(FakeResp(), FakeResp().json())
    assert "cursor=abc" in nxt
