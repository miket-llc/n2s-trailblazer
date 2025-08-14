import json
from unittest.mock import patch
from trailblazer.pipeline.steps.normalize.html_to_md import (
    normalize_from_ingest,
)


def test_normalize_adf(tmp_path):
    rid = "2025-08-13_efgh"
    ingest = tmp_path / "var" / "runs" / rid / "ingest"
    outdir = tmp_path / "var" / "runs" / rid / "normalize"
    ingest.mkdir(parents=True, exist_ok=True)
    outdir.mkdir(parents=True, exist_ok=True)

    adf = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 2},
                "content": [{"type": "text", "text": "Title"}],
            },
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "A "},
                    {
                        "type": "text",
                        "text": "link",
                        "marks": [
                            {
                                "type": "link",
                                "attrs": {"href": "https://x.y/z"},
                            }
                        ],
                    },
                    {"type": "text", "text": " here."},
                ],
            },
        ],
    }
    rec = {
        "id": "p2",
        "title": "Hello ADF",
        "space_key": "DEV",
        "space_id": "111",
        "url": "https://x/wiki/spaces/DEV/pages/2/HelloADF",
        "version": 1,
        "created_at": "2025-08-01T00:00:00Z",
        "updated_at": "2025-08-03T00:00:00Z",
        "body_repr": "adf",
        "body_adf": adf,
        "attachments": [],
    }
    nd = ingest / "confluence.ndjson"
    nd.write_text(json.dumps(rec) + "\n", encoding="utf-8")

    with patch("trailblazer.core.paths.ROOT", tmp_path):
        m = normalize_from_ingest(outdir=str(outdir), input_file=str(nd))
        assert m["pages"] == 1

        out = outdir / "normalized.ndjson"
        assert out.exists()

        lines = out.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1

        result = json.loads(lines[0])
        assert result["title"] == "Hello ADF"
        assert "## Title" in result["text_md"]
        assert "[link](https://x.y/z)" in result["text_md"]
