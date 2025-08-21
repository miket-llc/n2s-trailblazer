# Test constants for magic numbers
EXPECTED_COUNT_2 = 2
EXPECTED_COUNT_3 = 3
EXPECTED_COUNT_4 = 4

"""Integration tests for traceability preservation in normalize."""

import json
from unittest.mock import patch

import pytest

from trailblazer.pipeline.steps.normalize.html_to_md import (
    normalize_from_ingest,
)

# Mark all tests as unit tests (no database needed)
pytestmark = pytest.mark.unit


def test_normalize_preserves_traceability_fields(tmp_path):
    """Test that normalized records retain url, space_key, links, and attachments."""
    rid = "2025-08-13_trace"
    ingest = tmp_path / "var" / "runs" / rid / "ingest"
    outdir = tmp_path / "var" / "runs" / rid / "normalize"
    ingest.mkdir(parents=True, exist_ok=True)
    outdir.mkdir(parents=True, exist_ok=True)

    # Create test data with full traceability fields
    rec = {
        "id": "p1",
        "title": "Traceability Test Page",
        "space_key": "DEV",
        "space_id": "111",
        "url": "https://example.atlassian.net/wiki/spaces/DEV/pages/p1/test",
        "version": 1,
        "created_at": "2025-08-01T00:00:00Z",
        "updated_at": "2025-08-03T00:00:00Z",
        "source_system": "confluence",
        "body_repr": "storage",
        "body_storage": """
        <p>Visit <a href="https://external.com">External Link</a> and
        <a href="/spaces/DEV/pages/123/Other">Internal Page</a></p>
        """,
        "attachments": [
            {
                "id": "att1",
                "filename": "test.pdf",
                "media_type": "application/pdf",
                "file_size": 1024,
                "download_url": "https://example.atlassian.net/download/attachments/p1/test.pdf",
            }
        ],
    }

    nd = ingest / "confluence.ndjson"
    nd.write_text(json.dumps(rec) + "\n", encoding="utf-8")

    with patch("trailblazer.core.paths.ROOT", tmp_path):
        m = normalize_from_ingest(outdir=str(outdir), input_file=str(nd))
        assert m["pages"] == 1

        out = (outdir / "normalized.ndjson").read_text(encoding="utf-8").strip()
        normalized = json.loads(out)

        # Verify all traceability fields are preserved
        assert normalized["id"] == "p1"
        assert normalized["title"] == "Traceability Test Page"
        assert normalized["space_key"] == "DEV"
        assert normalized["space_id"] == "111"
        assert normalized["url"] == "https://example.atlassian.net/wiki/spaces/DEV/pages/p1/test"
        assert normalized["version"] == 1
        assert normalized["created_at"] == "2025-08-01T00:00:00Z"
        assert normalized["updated_at"] == "2025-08-03T00:00:00Z"
        assert normalized["source_system"] == "confluence"
        assert normalized["body_repr"] == "storage"

        # Verify links are preserved (URLs extracted from body)
        assert "links" in normalized
        links = normalized["links"]
        assert len(links) == EXPECTED_COUNT_2
        assert "https://external.com" in links
        assert "/spaces/DEV/pages/123/Other" in links

        # Verify attachments are preserved with references
        assert "attachments" in normalized
        attachments = normalized["attachments"]
        assert len(attachments) == 1

        attachment = attachments[0]
        assert attachment["filename"] == "test.pdf"
        assert attachment["url"] == "https://example.atlassian.net/download/attachments/p1/test.pdf"

        # Verify markdown content is generated
        assert "text_md" in normalized
        text_md = normalized["text_md"]
        assert "External Link" in text_md
        assert "Internal Page" in text_md


def test_normalize_preserves_adf_traceability(tmp_path):
    """Test that ADF format traceability is preserved in normalize."""
    rid = "2025-08-13_adf_trace"
    ingest = tmp_path / "var" / "runs" / rid / "ingest"
    outdir = tmp_path / "var" / "runs" / rid / "normalize"
    ingest.mkdir(parents=True, exist_ok=True)
    outdir.mkdir(parents=True, exist_ok=True)

    adf = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "Visit ",
                    },
                    {
                        "type": "text",
                        "text": "example",
                        "marks": [
                            {
                                "type": "link",
                                "attrs": {"href": "https://example.com"},
                            }
                        ],
                    },
                ],
            }
        ],
    }

    rec = {
        "id": "p2",
        "title": "ADF Traceability Test",
        "space_key": "PROD",
        "space_id": "222",
        "url": "https://example.atlassian.net/wiki/spaces/PROD/pages/p2/adf-test",
        "version": 2,
        "created_at": "2025-08-02T00:00:00Z",
        "updated_at": "2025-08-04T00:00:00Z",
        "source_system": "confluence",
        "body_repr": "adf",
        "body_adf": adf,
        "attachments": [],
    }

    nd = ingest / "confluence.ndjson"
    nd.write_text(json.dumps(rec) + "\n", encoding="utf-8")

    with patch("trailblazer.core.paths.ROOT", tmp_path):
        m = normalize_from_ingest(outdir=str(outdir), input_file=str(nd))
        assert m["pages"] == 1

        out = (outdir / "normalized.ndjson").read_text(encoding="utf-8").strip()
        normalized = json.loads(out)

        # Verify ADF traceability fields
        assert normalized["id"] == "p2"
        assert normalized["space_key"] == "PROD"
        assert normalized["url"] == "https://example.atlassian.net/wiki/spaces/PROD/pages/p2/adf-test"
        assert normalized["source_system"] == "confluence"
        assert normalized["body_repr"] == "adf"

        # Verify ADF links are extracted
        links = normalized["links"]
        assert len(links) == 1
        assert "https://example.com" in links

        # Verify markdown conversion from ADF
        text_md = normalized["text_md"]
        assert "Visit [example](https://example.com)" in text_md
