from trailblazer.adapters.confluence_api import ConfluenceClient


def test_next_link_parsing(monkeypatch):
    c = ConfluenceClient(
        base_url="https://example.atlassian.net/wiki", email="e", token="t"
    )

    # simulate response with _links.next
    class FakeResp:
        headers = {}

        def json(self):
            return {
                "results": [{"id": "1"}],
                "_links": {
                    "next": "https://example.atlassian.net/wiki/api/v2/pages?cursor=abc"
                },
            }

    nxt = c._next_link(FakeResp(), FakeResp().json())
    assert "cursor=abc" in nxt
