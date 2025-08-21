"""Integration tests for comprehensive graph traceability features."""

import json
import pytest
from trailblazer.pipeline.steps.ingest import confluence as step

# Mark all tests as unit tests (no database needed)
pytestmark = pytest.mark.unit


def test_comprehensive_traceability_adf(tmp_path, monkeypatch):
    """Test complete traceability with ADF format including media, labels, hierarchy."""

    class FakeClient:
        site_base = "https://example.atlassian.net/wiki"

        def get_spaces(self, keys=None, limit=100):
            yield {
                "id": "111",
                "key": "DEV",
                "name": "Development Space",
                "type": "global",
            }

        def get_pages(self, space_id=None, body_format=None, limit=100):
            yield {
                "id": "p1",
                "title": "Test Page with Media",
                "spaceId": "111",
                "authorId": {
                    "accountId": "user123",
                    "displayName": "John Doe",
                },
                "version": {
                    "number": 1,
                    "createdAt": "2025-08-10T12:00:00Z",
                    "authorId": {
                        "accountId": "user456",
                        "displayName": "Jane Smith",
                    },
                },
                "_links": {"webui": "/spaces/DEV/pages/p1/Test"},
                "createdAt": "2025-08-01T00:00:00Z",
                "body": {
                    "atlas_doc_format": {
                        "value": {
                            "type": "doc",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [
                                        {"type": "text", "text": "Visit "},
                                        {
                                            "type": "text",
                                            "text": "external site",
                                            "marks": [
                                                {
                                                    "type": "link",
                                                    "attrs": {
                                                        "href": "https://example.com"
                                                    },
                                                }
                                            ],
                                        },
                                    ],
                                },
                                {
                                    "type": "mediaSingle",
                                    "content": [
                                        {
                                            "type": "media",
                                            "attrs": {
                                                "id": "media123",
                                                "type": "file",
                                                "url": "/download/attachments/p1/image.png",
                                                "alt": "Test image",
                                                "width": 400,
                                                "height": 300,
                                            },
                                        }
                                    ],
                                },
                                {
                                    "type": "paragraph",
                                    "content": [
                                        {"type": "text", "text": "See also "},
                                        {
                                            "type": "text",
                                            "text": "related page",
                                            "marks": [
                                                {
                                                    "type": "link",
                                                    "attrs": {
                                                        "href": "/spaces/DEV/pages/456/Related"
                                                    },
                                                }
                                            ],
                                        },
                                    ],
                                },
                            ],
                        }
                    }
                },
            }

        def get_page_by_id(self, page_id, body_format=None):
            return {}

        def get_attachments_for_page(self, page_id, limit=100):
            if page_id == "p1":
                yield {
                    "id": "att1",
                    "title": "image.png",
                    "mediaType": "image/png",
                    "fileSize": 2048,
                    "_links": {
                        "download": "/download/attachments/p1/image.png"
                    },
                }

        def get_page_labels(self, page_id):
            if page_id == "p1":
                return [
                    {"name": "important"},
                    {"name": "documentation"},
                ]
            return []

        def get_page_ancestors(self, page_id):
            if page_id == "p1":
                return [
                    {
                        "id": "parent1",
                        "title": "Parent Page",
                        "_links": {
                            "webui": "/spaces/DEV/pages/parent1/Parent"
                        },
                    }
                ]
            return []

        def get_space_details(self, space_key):
            if space_key == "DEV":
                return {"name": "Development Space", "type": "global"}
            return {}

        def search_cql(self, cql, start=0, limit=50, expand=None):
            return {"results": []}

    monkeypatch.setattr(step, "ConfluenceClient", lambda: FakeClient())
    out = tmp_path / "out"

    step.ingest_confluence(
        str(out),
        space_keys=["DEV"],
        since=None,
        body_format="atlas_doc_format",
        max_pages=None,
    )

    # Verify main NDJSON has complete record
    ndjson_file = out / "confluence.ndjson"
    assert ndjson_file.exists()

    with open(ndjson_file) as f:
        page_data = json.loads(f.read().strip())

    # Check canonical page record fields
    assert page_data["source_system"] == "confluence"
    assert page_data["space_id"] == "111"
    assert page_data["space_key"] == "DEV"
    assert page_data["space_name"] == "Development Space"
    assert page_data["space_type"] == "global"
    assert page_data["id"] == "p1"
    assert page_data["title"] == "Test Page with Media"
    assert (
        page_data["url"]
        == "https://example.atlassian.net/wiki/spaces/DEV/pages/p1/Test"
    )
    assert page_data["version"] == 1
    assert page_data["created_at"] == "2025-08-01T00:00:00Z"
    assert page_data["updated_at"] == "2025-08-10T12:00:00Z"

    # Check user information
    assert page_data["created_by"]["account_id"] == "user123"
    assert page_data["created_by"]["display_name"] == "John Doe"
    assert page_data["updated_by"]["account_id"] == "user456"
    assert page_data["updated_by"]["display_name"] == "Jane Smith"

    # Check labels
    assert page_data["labels"] == ["important", "documentation"]
    assert page_data["label_count"] == 2

    # Check ancestors
    assert len(page_data["ancestors"]) == 1
    assert page_data["ancestors"][0]["id"] == "parent1"
    assert page_data["ancestors"][0]["title"] == "Parent Page"
    assert page_data["ancestor_count"] == 1

    # Check content hash
    assert "content_sha256" in page_data
    assert len(page_data["content_sha256"]) == 64  # SHA256 hex string

    # Check attachment counts
    assert page_data["attachment_count"] == 1

    # Check attachments
    assert len(page_data["attachments"]) == 1
    attachment = page_data["attachments"][0]
    assert attachment["id"] == "att1"
    assert attachment["filename"] == "image.png"
    assert attachment["media_type"] == "image/png"
    assert attachment["file_size"] == 2048

    # Verify links.jsonl has correct link data
    links_file = out / "links.jsonl"
    assert links_file.exists()

    with open(links_file) as f:
        link_lines = [json.loads(line) for line in f if line.strip()]

    assert len(link_lines) == 2

    # Find external and internal links
    external_link = next(
        link for link in link_lines if link["target_type"] == "external"
    )
    internal_link = next(
        link for link in link_lines if link["target_type"] == "confluence"
    )

    assert external_link["from_page_id"] == "p1"
    assert external_link["target_url"] == "https://example.com"
    assert external_link["target_page_id"] is None

    assert internal_link["from_page_id"] == "p1"
    assert internal_link["target_page_id"] == "456"
    assert internal_link["target_url"] == "/spaces/DEV/pages/456/Related"

    # Verify ingest_media.jsonl has media data
    media_file = out / "ingest_media.jsonl"
    assert media_file.exists()

    with open(media_file) as f:
        media_lines = [json.loads(line) for line in f if line.strip()]

    assert len(media_lines) == 1
    media = media_lines[0]
    assert media["page_id"] == "p1"
    assert media["order"] == 0
    assert media["type"] == "image"
    assert media["filename"] == "image.png"
    assert media["attachment_id"] == "media123"
    assert media["context"]["alt"] == "Test image"

    # Verify edges.jsonl has hierarchy and label edges
    edges_file = out / "edges.jsonl"
    assert edges_file.exists()

    with open(edges_file) as f:
        edge_lines = [json.loads(line) for line in f if line.strip()]

    # Should have: 1 parent edge + 2 label edges + 1 space containment = 4 edges
    assert len(edge_lines) == 4

    parent_edge = next(
        edge for edge in edge_lines if edge["type"] == "PARENT_OF"
    )
    assert parent_edge["src"] == "parent1"
    assert parent_edge["dst"] == "p1"

    space_edge = next(
        edge for edge in edge_lines if edge["type"] == "CONTAINS"
    )
    assert space_edge["src"] == "space:DEV"
    assert space_edge["dst"] == "p1"

    label_edges = [edge for edge in edge_lines if edge["type"] == "LABELED_AS"]
    assert len(label_edges) == 2
    label_targets = {edge["dst"] for edge in label_edges}
    assert label_targets == {"label:important", "label:documentation"}

    # Verify labels.jsonl
    labels_file = out / "labels.jsonl"
    assert labels_file.exists()

    with open(labels_file) as f:
        label_lines = [json.loads(line) for line in f if line.strip()]

    assert len(label_lines) == 2
    labels = {line["label"] for line in label_lines}
    assert labels == {"important", "documentation"}

    # Verify breadcrumbs.jsonl
    breadcrumbs_file = out / "breadcrumbs.jsonl"
    assert breadcrumbs_file.exists()

    with open(breadcrumbs_file) as f:
        breadcrumb_lines = [json.loads(line) for line in f if line.strip()]

    assert len(breadcrumb_lines) == 1
    breadcrumbs = breadcrumb_lines[0]
    assert breadcrumbs["page_id"] == "p1"
    assert breadcrumbs["breadcrumbs"] == [
        "Development Space",
        "Parent Page",
        "Test Page with Media",
    ]

    # Verify attachments_manifest.jsonl
    manifest_file = out / "attachments_manifest.jsonl"
    assert manifest_file.exists()

    with open(manifest_file) as f:
        manifest_lines = [json.loads(line) for line in f if line.strip()]

    assert len(manifest_lines) == 1
    manifest = manifest_lines[0]
    assert manifest["page_id"] == "p1"
    assert manifest["filename"] == "image.png"
    assert manifest["media_type"] == "image/png"

    # Verify enhanced summary.json
    summary_file = out / "summary.json"
    assert summary_file.exists()

    with open(summary_file) as f:
        summary = json.load(f)

    assert summary["total_pages"] == 1
    assert summary["links_total"] == 2
    assert summary["links_external"] == 1
    assert summary["links_internal"] == 1
    assert summary["media_refs_total"] == 1
    assert summary["labels_total"] == 2
    assert summary["ancestors_total"] == 1


def test_storage_format_traceability(tmp_path, monkeypatch):
    """Test traceability features with Storage format."""

    class FakeClient:
        site_base = "https://example.atlassian.net/wiki"

        def get_spaces(self, keys=None, limit=100):
            yield {"id": "222", "key": "PROD"}

        def get_pages(self, space_id=None, body_format=None, limit=100):
            yield {
                "id": "p2",
                "title": "Storage Format Page",
                "spaceId": "222",
                "version": {"number": 2, "createdAt": "2025-08-11T12:00:00Z"},
                "_links": {"webui": "/spaces/PROD/pages/p2/Storage"},
                "createdAt": "2025-08-02T00:00:00Z",
                "body": {
                    "storage": {
                        "value": """
                        <p>Check out <a href="https://external.com">External</a> and 
                        <a href="/spaces/PROD/pages/789/Other">Internal</a></p>
                        <ac:image ac:width="200" ac:height="150" ac:alt="Test image">
                            <ri:attachment ri:filename="screenshot.png" ri:content-id="att123"/>
                        </ac:image>
                        <p>Download <ri:attachment ri:filename="document.pdf" ri:content-id="doc456"/></p>
                        """
                    }
                },
            }

        def get_page_by_id(self, page_id, body_format=None):
            return {}

        def get_attachments_for_page(self, page_id, limit=100):
            if page_id == "p2":
                yield {
                    "id": "att123",
                    "title": "screenshot.png",
                    "mediaType": "image/png",
                    "fileSize": 1024,
                    "_links": {
                        "download": "/download/attachments/p2/screenshot.png"
                    },
                }
                yield {
                    "id": "doc456",
                    "title": "document.pdf",
                    "mediaType": "application/pdf",
                    "fileSize": 4096,
                    "_links": {
                        "download": "/download/attachments/p2/document.pdf"
                    },
                }

        def get_page_labels(self, page_id):
            return []

        def get_page_ancestors(self, page_id):
            return []

        def get_space_details(self, space_key):
            return {}

        def search_cql(self, cql, start=0, limit=50, expand=None):
            return {"results": []}

    monkeypatch.setattr(step, "ConfluenceClient", lambda: FakeClient())
    out = tmp_path / "out"

    step.ingest_confluence(
        str(out),
        space_keys=["PROD"],
        since=None,
        body_format="storage",
        max_pages=None,
    )

    # Verify media extraction from Storage format
    media_file = out / "ingest_media.jsonl"
    assert media_file.exists()

    with open(media_file) as f:
        media_lines = [json.loads(line) for line in f if line.strip()]

    assert len(media_lines) == 2

    # Check image media
    image_media = next(
        m for m in media_lines if m["filename"] == "screenshot.png"
    )
    assert image_media["type"] == "image"
    assert image_media["attachment_id"] == "att123"
    assert image_media["context"]["alt"] == "Test image"
    assert image_media["context"]["width"] == "200"

    # Check file media
    file_media = next(
        m for m in media_lines if m["filename"] == "document.pdf"
    )
    assert file_media["type"] == "file"
    assert file_media["attachment_id"] == "doc456"

    # Verify links extraction from Storage
    links_file = out / "links.jsonl"
    assert links_file.exists()

    with open(links_file) as f:
        link_lines = [json.loads(line) for line in f if line.strip()]

    assert len(link_lines) == 2

    external_link = next(
        link for link in link_lines if link["target_type"] == "external"
    )
    internal_link = next(
        link for link in link_lines if link["target_type"] == "confluence"
    )

    assert external_link["target_url"] == "https://external.com"
    assert internal_link["target_page_id"] == "789"
