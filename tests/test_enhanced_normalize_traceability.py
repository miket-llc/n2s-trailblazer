"""Tests for enhanced traceability preservation in normalize step."""

import json
from trailblazer.pipeline.steps.normalize.html_to_md import (
    normalize_from_ingest,
)
import trailblazer.core.artifacts as artifacts


def test_normalize_preserves_enhanced_traceability(tmp_path):
    """Test that normalize preserves all enhanced traceability fields."""
    rid = "2025-08-13_enhanced_trace"
    ingest = tmp_path / "runs" / rid / "ingest"
    outdir = tmp_path / "runs" / rid / "normalize"
    ingest.mkdir(parents=True, exist_ok=True)
    outdir.mkdir(parents=True, exist_ok=True)

    # Create test data with complete enhanced traceability
    rec = {
        "id": "p1",
        "title": "Enhanced Traceability Test",
        "space_key": "DEV",
        "space_id": "111",
        "space_name": "Development Space",
        "space_type": "global",
        "url": "https://example.atlassian.net/wiki/spaces/DEV/pages/p1/test",
        "version": 2,
        "created_at": "2025-08-01T00:00:00Z",
        "updated_at": "2025-08-03T00:00:00Z",
        "source_system": "confluence",
        "body_repr": "adf",
        "body_adf": {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Visit "},
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
        },
        "created_by": {"account_id": "user123", "display_name": "John Doe"},
        "updated_by": {"account_id": "user456", "display_name": "Jane Smith"},
        "labels": ["important", "documentation", "api"],
        "ancestors": [
            {
                "id": "parent1",
                "title": "Parent Section",
                "url": "https://example.atlassian.net/wiki/spaces/DEV/pages/parent1/section",
            },
            {
                "id": "grandparent1",
                "title": "Root Page",
                "url": "https://example.atlassian.net/wiki/spaces/DEV/pages/grandparent1/root",
            },
        ],
        "content_sha256": "abc123def456",
        "label_count": 3,
        "ancestor_count": 2,
        "attachment_count": 1,
        "attachments": [
            {
                "id": "att1",
                "filename": "api-spec.json",
                "media_type": "application/json",
                "file_size": 2048,
                "download_url": "https://example.atlassian.net/download/attachments/p1/api-spec.json",
                "sha256": "file123hash456",
            }
        ],
        "metadata": {"space_status": "current"},
    }

    nd = ingest / "confluence.ndjson"
    nd.write_text(json.dumps(rec) + "\n", encoding="utf-8")

    old = artifacts.ROOT
    artifacts.ROOT = tmp_path
    try:
        m = normalize_from_ingest(outdir=str(outdir), input_file=str(nd))
        assert m["pages"] == 1

        out = (
            (outdir / "normalized.ndjson").read_text(encoding="utf-8").strip()
        )
        normalized = json.loads(out)

        # Verify core traceability fields preserved
        assert normalized["id"] == "p1"
        assert normalized["title"] == "Enhanced Traceability Test"
        assert normalized["space_key"] == "DEV"
        assert normalized["space_id"] == "111"
        assert (
            normalized["url"]
            == "https://example.atlassian.net/wiki/spaces/DEV/pages/p1/test"
        )
        assert normalized["version"] == 2
        assert normalized["created_at"] == "2025-08-01T00:00:00Z"
        assert normalized["updated_at"] == "2025-08-03T00:00:00Z"
        assert normalized["source_system"] == "confluence"
        assert normalized["body_repr"] == "adf"

        # Verify enhanced fields preserved
        assert normalized["labels"] == ["important", "documentation", "api"]
        assert normalized["content_sha256"] == "abc123def456"

        # Verify breadcrumbs generated from ancestors
        assert "breadcrumbs" in normalized
        breadcrumbs = normalized["breadcrumbs"]
        expected_breadcrumbs = [
            "Development Space",
            "Parent Section",
            "Root Page",
            "Enhanced Traceability Test",
        ]
        assert breadcrumbs == expected_breadcrumbs

        # Verify links preserved
        assert "links" in normalized
        links = normalized["links"]
        assert len(links) == 1
        assert "https://example.com" in links

        # Verify attachments preserved with references
        assert "attachments" in normalized
        attachments = normalized["attachments"]
        assert len(attachments) == 1
        attachment = attachments[0]
        assert attachment["filename"] == "api-spec.json"
        assert (
            attachment["url"]
            == "https://example.atlassian.net/download/attachments/p1/api-spec.json"
        )

        # Verify markdown content generated
        assert "text_md" in normalized
        text_md = normalized["text_md"]
        assert "Visit [example](https://example.com)" in text_md

    finally:
        artifacts.ROOT = old


def test_normalize_handles_minimal_traceability(tmp_path):
    """Test normalize handles records with minimal traceability fields."""
    rid = "2025-08-13_minimal_trace"
    ingest = tmp_path / "runs" / rid / "ingest"
    outdir = tmp_path / "runs" / rid / "normalize"
    ingest.mkdir(parents=True, exist_ok=True)
    outdir.mkdir(parents=True, exist_ok=True)

    # Create minimal record
    rec = {
        "id": "p2",
        "title": "Minimal Page",
        "space_key": "SIMPLE",
        "space_id": "222",
        "url": "https://example.atlassian.net/wiki/spaces/SIMPLE/pages/p2/minimal",
        "body_repr": "storage",
        "body_storage": "<p>Simple content with no links</p>",
        "source_system": "confluence",
        "labels": [],  # Empty labels
        "ancestors": [],  # No ancestors
        "attachments": [],  # No attachments
    }

    nd = ingest / "confluence.ndjson"
    nd.write_text(json.dumps(rec) + "\n", encoding="utf-8")

    old = artifacts.ROOT
    artifacts.ROOT = tmp_path
    try:
        m = normalize_from_ingest(outdir=str(outdir), input_file=str(nd))
        assert m["pages"] == 1

        out = (
            (outdir / "normalized.ndjson").read_text(encoding="utf-8").strip()
        )
        normalized = json.loads(out)

        # Verify minimal fields preserved
        assert normalized["id"] == "p2"
        assert normalized["space_key"] == "SIMPLE"
        assert normalized["source_system"] == "confluence"
        assert normalized["labels"] == []
        assert normalized["content_sha256"] is None

        # Verify no breadcrumbs generated when no ancestors
        assert "breadcrumbs" not in normalized

        # Verify empty collections handled correctly
        assert normalized["links"] == []
        assert normalized["attachments"] == []

    finally:
        artifacts.ROOT = old


def test_normalize_backward_compatibility(tmp_path):
    """Test normalize maintains backward compatibility with old record format."""
    rid = "2025-08-13_compat"
    ingest = tmp_path / "runs" / rid / "ingest"
    outdir = tmp_path / "runs" / rid / "normalize"
    ingest.mkdir(parents=True, exist_ok=True)
    outdir.mkdir(parents=True, exist_ok=True)

    # Create old-style record without new fields
    rec = {
        "id": "p3",
        "title": "Legacy Page",
        "space_key": "LEGACY",
        "space_id": "333",
        "url": "https://example.atlassian.net/wiki/spaces/LEGACY/pages/p3/legacy",
        "body_repr": "storage",
        "body_storage": "<p>Legacy content</p>",
        # Missing: labels, ancestors, content_sha256, etc.
    }

    nd = ingest / "confluence.ndjson"
    nd.write_text(json.dumps(rec) + "\n", encoding="utf-8")

    old = artifacts.ROOT
    artifacts.ROOT = tmp_path
    try:
        m = normalize_from_ingest(outdir=str(outdir), input_file=str(nd))
        assert m["pages"] == 1

        out = (
            (outdir / "normalized.ndjson").read_text(encoding="utf-8").strip()
        )
        normalized = json.loads(out)

        # Verify core fields preserved
        assert normalized["id"] == "p3"
        assert normalized["space_key"] == "LEGACY"

        # Verify missing fields handled gracefully with defaults
        assert normalized["source_system"] == "confluence"  # Default fallback
        assert normalized["labels"] == []  # Empty default
        assert normalized["content_sha256"] is None  # Missing field

        # Verify no breadcrumbs when ancestors missing
        assert "breadcrumbs" not in normalized

    finally:
        artifacts.ROOT = old
