"""Integration tests for attachments manifest traceability."""

import json
import pytest
from trailblazer.pipeline.steps.ingest import confluence as step

# Mark all tests as unit tests (no database needed)
pytestmark = pytest.mark.unit


def test_attachments_manifest_matches_ndjson(tmp_path, monkeypatch):
    """Test that attachments_manifest.jsonl lines match NDJSON attachments."""

    class FakeClient:
        site_base = "https://example.atlassian.net/wiki"

        def get_spaces(self, keys=None, limit=100):
            yield {"id": "111", "key": "DEV"}

        def get_pages(self, space_id=None, body_format=None, limit=100):
            yield {
                "id": "p1",
                "title": "Page with Attachments",
                "spaceId": "111",
                "version": {"number": 1, "createdAt": "2025-08-10T12:00:00Z"},
                "_links": {"webui": "/spaces/DEV/pages/p1/Test"},
                "createdAt": "2025-08-01T00:00:00Z",
                "body": {"storage": {"value": "<p>Test page</p>"}},
            }

        def get_page_by_id(self, page_id, body_format=None):
            return {}

        def get_attachments_for_page(self, page_id, limit=100):
            if page_id == "p1":
                yield {
                    "id": "att1",
                    "title": "document.pdf",
                    "mediaType": "application/pdf",
                    "fileSize": 1024,
                    "_links": {
                        "download": "/download/attachments/p1/document.pdf"
                    },
                }
                yield {
                    "id": "att2",
                    "title": "image.png",
                    "mediaType": "image/png",
                    "fileSize": 2048,
                    "_links": {
                        "download": "/download/attachments/p1/image.png"
                    },
                }

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

    # Check NDJSON attachments
    ndjson_file = out / "confluence.ndjson"
    assert ndjson_file.exists()

    with open(ndjson_file) as f:
        page_data = json.loads(f.read().strip())

    ndjson_attachments = page_data["attachments"]
    assert len(ndjson_attachments) == 2

    # Check attachments_manifest.jsonl
    manifest_file = out / "attachments_manifest.jsonl"
    assert manifest_file.exists()

    with open(manifest_file) as f:
        manifest_lines = [json.loads(line) for line in f if line.strip()]

    assert len(manifest_lines) == 2

    # Verify manifest entries match NDJSON
    for manifest_entry in manifest_lines:
        assert manifest_entry["page_id"] == "p1"

        # Find matching NDJSON attachment
        matching_attachment = next(
            a
            for a in ndjson_attachments
            if a["filename"] == manifest_entry["filename"]
        )

        assert manifest_entry["filename"] == matching_attachment["filename"]
        assert (
            manifest_entry["media_type"] == matching_attachment["media_type"]
        )
        assert manifest_entry["file_size"] == matching_attachment["file_size"]
        assert (
            manifest_entry["download_url"]
            == matching_attachment["download_url"]
        )

    # Verify specific attachments
    pdf_entry = next(
        m for m in manifest_lines if m["filename"] == "document.pdf"
    )
    assert pdf_entry["media_type"] == "application/pdf"
    assert pdf_entry["file_size"] == 1024

    png_entry = next(m for m in manifest_lines if m["filename"] == "image.png")
    assert png_entry["media_type"] == "image/png"
    assert png_entry["file_size"] == 2048

    # Check summary includes attachment refs
    summary_file = out / "summary.json"
    assert summary_file.exists()

    with open(summary_file) as f:
        summary = json.load(f)

    assert summary["total_attachments"] == 2
