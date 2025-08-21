# Test constants for magic numbers
EXPECTED_COUNT_2 = 2
EXPECTED_COUNT_3 = 3
EXPECTED_COUNT_4 = 4

import json

import pytest

# Mark all tests as unit tests (no database needed)
pytestmark = pytest.mark.unit


def test_ingest_writes_ndjson(tmp_path, monkeypatch):
    # fake client methods
    from trailblazer.pipeline.steps.ingest import confluence as step

    class FakeClient:
        site_base = "https://example.atlassian.net/wiki"

        def get_spaces(self, _keys=None, _limit=100):
            yield {"id": "111", "key": "DEV"}

        def get_pages(self, _space_id=None, _body_format=None, _limit=100):
            yield {
                "id": "p1",
                "title": "T1",
                "spaceId": "111",
                "version": {"number": 1, "createdAt": "2025-08-10T12:00:00Z"},
                "_links": {"webui": "/spaces/DEV/pages/p1/T1"},
                "createdAt": "2025-08-01T00:00:00Z",
                "body": {"storage": {"value": "<p>hi</p>"}},
            }
            yield {
                "id": "p2",
                "title": "T2",
                "spaceId": "111",
                "version": {"number": 2, "createdAt": "2025-08-11T12:00:00Z"},
                "_links": {"webui": "/spaces/DEV/pages/p2/T2"},
                "createdAt": "2025-08-02T00:00:00Z",
                "body": {"storage": {"value": "<p>bye</p>"}},
            }

        def get_page_by_id(self, _page_id, _body_format=None):
            if _page_id == "p1":
                return {
                    "id": "p1",
                    "title": "T1",
                    "spaceId": "111",
                    "version": {
                        "number": 1,
                        "createdAt": "2025-08-10T12:00:00Z",
                    },
                    "_links": {"webui": "/spaces/DEV/pages/p1/T1"},
                    "createdAt": "2025-08-01T00:00:00Z",
                    "body": {"storage": {"value": "<p>hi</p>"}},
                }
            elif _page_id == "p2":
                return {
                    "id": "p2",
                    "title": "T2",
                    "spaceId": "111",
                    "version": {
                        "number": 2,
                        "createdAt": "2025-08-11T12:00:00Z",
                    },
                    "_links": {"webui": "/spaces/DEV/pages/p2/T2"},
                    "createdAt": "2025-08-02T00:00:00Z",
                    "body": {"storage": {"value": "<p>bye</p>"}},
                }
            return {}

        def get_attachments_for_page(self, _page_id, _limit=100):
            if _page_id == "p1":
                yield {
                    "id": "a1",
                    "title": "file.png",
                    "_links": {"download": "/download/attachments/p1/file.png"},
                }

        def search_cql(self, _cql, _start=0, _limit=50, _expand=None):
            return {"results": []}

    monkeypatch.setattr(step, "ConfluenceClient", lambda: FakeClient())
    out = tmp_path / "out"
    step.ingest_confluence(
        str(out),
        space_keys=["DEV"],
        since=None,
        body_format="storage",
        max_pages=None,
    )

    nd = out / "confluence.ndjson"
    assert nd.exists()
    lines = nd.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == EXPECTED_COUNT_2
    rec = json.loads(lines[0])
    assert rec["id"] == "p1"
    assert rec["attachments"][0]["filename"] == "file.png"

    # Verify all required traceability fields from prompt
    required_fields = [
        "id",
        "url",
        "space_id",
        "space_key",
        "version",
        "created_at",
        "updated_at",
        "labels",
        "ancestors",
        "attachments",
        "content_sha256",
    ]
    for field in required_fields:
        assert field in rec, f"Required field '{field}' missing from output"

    # Verify attachment structure includes filename and download_url
    if rec["attachments"]:
        att = rec["attachments"][0]
        assert "filename" in att
        assert "download_url" in att
    m = json.loads((out / "metrics.json").read_text())
    assert m["pages"] == 2
