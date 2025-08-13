import json
from trailblazer.pipeline.steps.normalize.html_to_md import (
    normalize_from_ingest,
)
import trailblazer.core.artifacts as artifacts


def test_normalize_storage(tmp_path):
    rid = "2025-08-13_abcd"
    ingest = tmp_path / "runs" / rid / "ingest"
    outdir = tmp_path / "runs" / rid / "normalize"
    ingest.mkdir(parents=True, exist_ok=True)
    outdir.mkdir(parents=True, exist_ok=True)

    rec = {
        "id": "p1",
        "title": "Hello",
        "space_key": "DEV",
        "space_id": "111",
        "url": "https://x/wiki/spaces/DEV/pages/1/Hello",
        "version": 1,
        "created_at": "2025-08-01T00:00:00Z",
        "updated_at": "2025-08-02T00:00:00Z",
        "body_repr": "storage",
        "body_storage": "<h1>Title</h1><p>A <a href='https://x.y/z'>link</a></p>",
        "attachments": [
            {"filename": "a.png", "download_url": "https://x/download/a.png"}
        ],
    }
    nd = ingest / "confluence.ndjson"
    nd.write_text(json.dumps(rec) + "\n", encoding="utf-8")

    old = artifacts.ROOT
    artifacts.ROOT = tmp_path
    try:
        m = normalize_from_ingest(outdir=str(outdir), input_file=str(nd))
        assert m["pages"] == 1 and m["empty_bodies"] == 0
        out = (
            (outdir / "normalized.ndjson").read_text(encoding="utf-8").strip()
        )
        line = json.loads(out)
        assert line["body_repr"] == "storage"
        assert "# Title" in line["text_md"]
        assert line["links"] == ["https://x.y/z"]
        assert line["attachments"][0]["filename"] == "a.png"
    finally:
        artifacts.ROOT = old
