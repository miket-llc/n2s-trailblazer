"""Integration tests for link extraction in storage and ADF formats."""

import json
from trailblazer.pipeline.steps.ingest import confluence as step


def test_trace_links_storage_format(tmp_path, monkeypatch):
    """Test that storage format produces expected links.jsonl lines."""

    class FakeClient:
        site_base = "https://example.atlassian.net/wiki"

        def get_spaces(self, keys=None, limit=100):
            yield {"id": "111", "key": "DEV"}

        def get_pages(self, space_id=None, body_format=None, limit=100):
            yield {
                "id": "p1",
                "title": "Test Page",
                "spaceId": "111",
                "version": {"number": 1, "createdAt": "2025-08-10T12:00:00Z"},
                "_links": {"webui": "/spaces/DEV/pages/p1/Test"},
                "createdAt": "2025-08-01T00:00:00Z",
                "body": {
                    "storage": {
                        "value": """
                        <p>Visit <a href="https://external.com">External</a> and
                        <a href="/spaces/DEV/pages/123456/Internal">Internal</a> and
                        <a href="/download/attachments/p1/file.pdf">Attachment</a></p>
                        """
                    }
                },
            }

        def get_page_by_id(self, page_id, body_format=None):
            return {}

        def get_attachments_for_page(self, page_id, limit=100):
            return []

        def search_cql(self, cql, start=0, limit=50, expand=None):
            return {"results": []}

        def get_page_labels(self, page_id):
            return []

        def get_page_ancestors(self, page_id):
            return []

        def get_space_details(self, space_key):
            return {}

    monkeypatch.setattr(step, "ConfluenceClient", lambda: FakeClient())
    out = tmp_path / "out"

    step.ingest_confluence(
        str(out),
        space_keys=["DEV"],
        since=None,
        body_format="storage",
        max_pages=None,
    )

    # Check links.jsonl
    links_file = out / "links.jsonl"
    assert links_file.exists()

    with open(links_file) as f:
        link_lines = [json.loads(line) for line in f if line.strip()]

    assert len(link_lines) == 3

    # Find links by target type
    external_link = next(
        link for link in link_lines if link["target_type"] == "external"
    )
    confluence_link = next(
        link for link in link_lines if link["target_type"] == "confluence"
    )
    attachment_link = next(
        link for link in link_lines if link["target_type"] == "attachment"
    )

    # Verify external link
    assert external_link["from_page_id"] == "p1"
    assert external_link["target_url"] == "https://external.com"
    assert external_link["target_page_id"] is None
    assert external_link["rel"] == "links_to"

    # Verify confluence link with parsed page ID
    assert confluence_link["from_page_id"] == "p1"
    assert confluence_link["target_page_id"] == "123456"
    assert confluence_link["target_url"] == "/spaces/DEV/pages/123456/Internal"

    # Verify attachment link
    assert attachment_link["from_page_id"] == "p1"
    assert attachment_link["target_url"] == "/download/attachments/p1/file.pdf"


def test_trace_links_adf_format(tmp_path, monkeypatch):
    """Test that ADF format produces expected links.jsonl lines."""

    class FakeClient:
        site_base = "https://example.atlassian.net/wiki"

        def get_spaces(self, keys=None, limit=100):
            yield {"id": "111", "key": "DEV"}

        def get_pages(self, space_id=None, body_format=None, limit=100):
            yield {
                "id": "p2",
                "title": "ADF Test Page",
                "spaceId": "111",
                "version": {"number": 1, "createdAt": "2025-08-10T12:00:00Z"},
                "_links": {"webui": "/spaces/DEV/pages/p2/ADF-Test"},
                "createdAt": "2025-08-01T00:00:00Z",
                "body": {
                    "atlas_doc_format": {
                        "value": {
                            "type": "doc",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [
                                        {
                                            "type": "text",
                                            "text": "See ",
                                        },
                                        {
                                            "type": "text",
                                            "text": "Google",
                                            "marks": [
                                                {
                                                    "type": "link",
                                                    "attrs": {
                                                        "href": "https://google.com#search"
                                                    },
                                                }
                                            ],
                                        },
                                        {
                                            "type": "text",
                                            "text": " and ",
                                        },
                                        {
                                            "type": "text",
                                            "text": "other page",
                                            "marks": [
                                                {
                                                    "type": "link",
                                                    "attrs": {
                                                        "href": "/wiki/spaces/PROD/pages/789012/Other"
                                                    },
                                                }
                                            ],
                                        },
                                    ],
                                }
                            ],
                        }
                    }
                },
            }

        def get_page_by_id(self, page_id, body_format=None):
            return {}

        def get_attachments_for_page(self, page_id, limit=100):
            return []

        def search_cql(self, cql, start=0, limit=50, expand=None):
            return {"results": []}

        def get_page_labels(self, page_id):
            return []

        def get_page_ancestors(self, page_id):
            return []

        def get_space_details(self, space_key):
            return {}

    monkeypatch.setattr(step, "ConfluenceClient", lambda: FakeClient())
    out = tmp_path / "out"

    step.ingest_confluence(
        str(out),
        space_keys=["DEV"],
        since=None,
        body_format="atlas_doc_format",
        max_pages=None,
    )

    # Check links.jsonl
    links_file = out / "links.jsonl"
    assert links_file.exists()

    with open(links_file) as f:
        link_lines = [json.loads(line) for line in f if line.strip()]

    assert len(link_lines) == 2

    # Find links by URL
    google_link = next(
        link for link in link_lines if "google.com" in link["target_url"]
    )
    internal_link = next(
        link for link in link_lines if "PROD" in link["target_url"]
    )

    # Verify external link with anchor
    assert google_link["from_page_id"] == "p2"
    assert google_link["target_type"] == "external"
    assert google_link["anchor"] == "search"
    assert google_link["target_page_id"] is None

    # Verify internal link with parsed page ID
    assert internal_link["from_page_id"] == "p2"
    assert internal_link["target_type"] == "confluence"
    assert internal_link["target_page_id"] == "789012"

    # Check summary includes link stats
    summary_file = out / "summary.json"
    assert summary_file.exists()

    with open(summary_file) as f:
        summary = json.load(f)

    assert summary["links_total"] == 2
    assert summary["links_external"] == 1
    assert summary["links_internal"] == 1
    assert summary["links_unresolved"] == 0
