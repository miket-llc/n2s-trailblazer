import json
from trailblazer.pipeline.steps.normalize.html_to_md import (
    normalize_from_ingest,
)
import trailblazer.core.artifacts as artifacts


def test_normalize_prefers_adf_over_storage(tmp_path):
    """Test that when both ADF and storage are present, ADF is preferred."""
    rid = "2025-08-13_pref"
    ingest = tmp_path / "runs" / rid / "ingest"
    outdir = tmp_path / "runs" / rid / "normalize"
    ingest.mkdir(parents=True, exist_ok=True)
    outdir.mkdir(parents=True, exist_ok=True)

    adf = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "ADF content"}],
            }
        ],
    }

    # Record with both storage and ADF - ADF should win
    rec = {
        "id": "p1",
        "title": "Test Page",
        "space_key": "DEV",
        "space_id": "111",
        "url": "https://x/wiki/spaces/DEV/pages/1/test",
        "version": 1,
        "created_at": "2025-08-01T00:00:00Z",
        "updated_at": "2025-08-03T00:00:00Z",
        "body_storage": "<p>Storage content</p>",  # This should be ignored
        "body_adf": adf,  # This should be used
        "attachments": [],
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
        line = json.loads(out)

        # Should prefer ADF
        assert line["body_repr"] == "adf"
        assert "ADF content" in line["text_md"]
        assert "Storage content" not in line["text_md"]
    finally:
        artifacts.ROOT = old


def test_normalize_falls_back_to_storage_when_no_adf(tmp_path):
    """Test that storage is still used when ADF is not present."""
    rid = "2025-08-13_fallback"
    ingest = tmp_path / "runs" / rid / "ingest"
    outdir = tmp_path / "runs" / rid / "normalize"
    ingest.mkdir(parents=True, exist_ok=True)
    outdir.mkdir(parents=True, exist_ok=True)

    # Record with only storage format
    rec = {
        "id": "p1",
        "title": "Test Page",
        "space_key": "DEV",
        "space_id": "111",
        "url": "https://x/wiki/spaces/DEV/pages/1/test",
        "version": 1,
        "created_at": "2025-08-01T00:00:00Z",
        "updated_at": "2025-08-03T00:00:00Z",
        "body_storage": "<p>Storage content</p>",
        "attachments": [],
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
        line = json.loads(out)

        # Should use storage since no ADF
        assert line["body_repr"] == "storage"
        assert "Storage content" in line["text_md"]
    finally:
        artifacts.ROOT = old
