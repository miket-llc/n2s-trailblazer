# PROMPT 004 (Rev A) — Normalize Confluence Storage (XHTML) and ADF JSON → Markdown

Save this prompt as: prompts/004_normalize_both_storage_and_adf.md

You are: lead engineer extending Trailblazer on main. Implement a robust Normalize step that supports both Confluence body formats. Also patch ingest to persist the body representation so downstream logic is unambiguous.

## Objectives

**Ingest patch (backward-compatible):**

When fetching pages:

- If body-format=storage: store body_repr="storage" and body_storage (string).

- If body-format=atlas_doc_format: store body_repr="adf" and body_adf (JSON object).

Keep existing fields (body_html) if you already write them, but prefer the new fields going forward.

**Normalize step (normalize_from_ingest):**

- Input: runs/\<run_id>/ingest/confluence.ndjson.

For each record:

- If body_repr=="storage" → convert Storage (XHTML) to Markdown.

- If body_repr=="adf" → convert ADF JSON to Markdown via a small in-repo converter.

- Preserve links (from HTML links or ADF link marks) and attachments (as {filename,url}).

- Output: runs/\<run_id>/normalize/normalized.ndjson (+ metrics.json, manifest.json).

**Runner & CLI:**

- Runner: add normalize phase calling the real normalize function.

- CLI: trailblazer normalize from-ingest --run-id <RID> (and --input override) with --limit.

**Tests:**

- One test for storage path.

- One test for ADF path.

- A small unit test for Markdown determinism (whitespace & heading style).

**Docs:**

- Update README: "Normalize supports Storage & ADF."

## Code Changes

**A) Ingest: persist body representation (light patch)**
File: src/trailblazer/pipeline/steps/ingest/confluence.py

Add helpers (near existing mappers):

```python
def _detect_body_repr(obj: dict) -> str:
    body = obj.get("body") or {}
    if "storage" in body:
        return "storage"
    if "atlas_doc_format" in body:
        return "adf"
    return "unknown"

def _extract_body_storage(obj: dict) -> str | None:
    body = obj.get("body") or {}
    storage = body.get("storage") or {}
    val = storage.get("value")
    return val if isinstance(val, str) else None

def _extract_body_adf(obj: dict) -> dict | None:
    body = obj.get("body") or {}
    adf = body.get("atlas_doc_format") or {}
    val = adf.get("value")
    # v2 may return already-parsed JSON or a stringified JSON; handle both
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            import json
            return json.loads(val)
        except Exception:
            return None
    return None
```

When mapping each page (where you currently set body_html), also set the new fields:

```python
repr_ = _detect_body_repr(obj)
page_dict = page.model_dump()  # if you use Page model, get dict then add fields
page_dict["body_repr"] = repr_
if repr_ == "storage":
    page_dict["body_storage"] = _extract_body_storage(obj)
elif repr_ == "adf":
    page_dict["body_adf"] = _extract_body_adf(obj)
# keep page.body_html if you already set it; no need to remove
# then write page_dict to NDJSON (instead of page.model_dump()).
```

(If you already write json.dumps(page.model_dump()), replace that with json.dumps(page_dict).)

**B) Normalize: handle Storage (XHTML) and ADF**
File (new/replace): src/trailblazer/pipeline/steps/normalize/html_to_md.py

````python
from __future__ import annotations
import json, re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, Iterable, List

from bs4 import BeautifulSoup
from markdownify import markdownify as md

from ....core.logging import log
from ....core.artifacts import ROOT

# ---------- Storage (XHTML) -> Markdown ----------

def _to_markdown_from_storage(xhtml: Optional[str]) -> str:
    if not xhtml:
        return ""
    soup = BeautifulSoup(xhtml, "html.parser")
    # Drop non-content tags/macros (keep simple approach; advanced macro handling later)
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    html2 = str(soup)
    text = md(html2, heading_style="ATX", strip=["script", "style", "noscript"])
    # normalize whitespace deterministically
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text

def _extract_links_from_storage(xhtml: Optional[str]) -> List[str]:
    if not xhtml:
        return []
    soup = BeautifulSoup(xhtml, "html.parser")
    links = [a["href"] for a in soup.find_all("a", href=True)]
    return sorted(dict.fromkeys(links))

# ---------- ADF JSON -> Markdown (minimal converter) ----------

def _adf_text_with_marks(text: str, marks: Optional[List[dict]]) -> str:
    if not marks:
        return text
    # apply marks in a stable order: code, strong, em, strike, link
    out = text
    # links last so they wrap the final text
    order = {"code":0, "strong":1, "em":2, "strike":3, "link":4}
    for m in sorted(marks, key=lambda m: order.get(m.get("type",""), 99)):
        t = m.get("type")
        if t == "code":
            out = f"`{out}`"
        elif t == "strong":
            out = f"**{out}**"
        elif t == "em":
            out = f"*{out}*"
        elif t == "strike":
            out = f"~~{out}~~"
        elif t == "link":
            href = (m.get("attrs") or {}).get("href")
            if href:
                out = f"[{out}]({href})"
    return out

def _adf_inline(node: dict) -> str:
    t = node.get("type")
    if t == "text":
        return _adf_text_with_marks(node.get("text",""), node.get("marks"))
    if t == "hardBreak":
        return "\n"
    # inlineCode sometimes represented as text+code mark; we've covered in marks
    return ""

def _adf_block(node: dict, bullets: Optional[str]=None, number: Optional[int]=None) -> str:
    t = node.get("type")
    if t == "paragraph":
        parts = [ _adf_inline(c) for c in node.get("content", []) ]
        return "".join(parts).strip()
    if t == "heading":
        level = max(1, min(6, int((node.get("attrs") or {}).get("level", 1))))
        inner = "".join([_adf_inline(c) for c in node.get("content", [])]).strip()
        return f"{'#'*level} {inner}".strip()
    if t == "blockquote":
        inner = _adf_blocks(node.get("content", []))
        return "\n".join([f"> {line}".rstrip() for line in inner.splitlines()]) or "> "
    if t == "codeBlock":
        lang = (node.get("attrs") or {}).get("language") or ""
        code = "".join([c.get("text","") for c in node.get("content", []) if c.get("type")=="text"])
        return f"```{lang}\n{code}\n```"
    if t == "bulletList":
        lines = []
        for li in node.get("content", []):
            # listItem → content → paragraph/blocks
            inner = _adf_blocks(li.get("content", []))
            for line in inner.splitlines():
                if line.strip():
                    lines.append(f"- {line}")
        return "\n".join(lines)
    if t == "orderedList":
        lines = []
        n = int((node.get("attrs") or {}).get("order", 1))
        for li in node.get("content", []):
            inner = _adf_blocks(li.get("content", []))
            for line in inner.splitlines():
                if line.strip():
                    lines.append(f"{n}. {line}")
                    n += 1
        return "\n".join(lines)
    if t == "panel":
        # simple rendering: treat as blockquote
        inner = _adf_blocks(node.get("content", []))
        return "\n".join([f"> {line}".rstrip() for line in inner.splitlines()])
    # tables/media/mentions not handled yet; can be added incrementally
    # unknown blocks -> flatten children
    return _adf_blocks(node.get("content", []))

def _adf_blocks(nodes: List[dict]) -> str:
    lines: List[str] = []
    for n in nodes:
        s = _adf_block(n)
        if s is None:
            continue
        if s.strip():
            lines.append(s.strip())
    text = "\n\n".join(lines)
    # normalize whitespace
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text

def _to_markdown_from_adf(adf: Optional[dict]) -> str:
    if not adf or adf.get("type") != "doc":
        return ""
    return _adf_blocks(adf.get("content", []))

def _extract_links_from_adf(adf: Optional[dict]) -> List[str]:
    if not adf:
        return []
    links: List[str] = []
    def walk(n: dict):
        # collect from marks
        for c in n.get("content", []) or []:
            walk(c)
        if n.get("type") == "text":
            for m in n.get("marks", []) or []:
                if m.get("type") == "link":
                    href = (m.get("attrs") or {}).get("href")
                    if href:
                        links.append(href)
    walk(adf)
    # deterministic
    return sorted(dict.fromkeys(links))

# ---------- Orchestration ----------

def _derive_run_id(outdir: str) -> str:
    return Path(outdir).parent.name

def _default_ingest_path(run_id: str) -> Path:
    return ROOT / "runs" / run_id / "ingest" / "confluence.ndjson"

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def normalize_from_ingest(outdir: str, input_file: Optional[str] = None, limit: Optional[int] = None) -> Dict[str, Any]:
    out_dir = Path(outdir); out_dir.mkdir(parents=True, exist_ok=True)
    run_id = Path(outdir).parent.name
    inp = Path(input_file) if input_file else _default_ingest_path(run_id)
    if not inp.exists():
        raise FileNotFoundError(f"Ingest NDJSON not found: {inp}")

    nd_out = out_dir / "normalized.ndjson"
    metrics_path = out_dir / "metrics.json"
    manifest_path = out_dir / "manifest.json"

    total = empty = chars = atts_count = 0

    with inp.open("r", encoding="utf-8") as fin, nd_out.open("w", encoding="utf-8") as fout:
        for line in fin:
            if not line.strip():
                continue
            rec = json.loads(line)

            body_repr = rec.get("body_repr") or ("storage" if rec.get("body_storage") else ("adf" if rec.get("body_adf") else None))
            links: List[str] = []
            if body_repr == "storage":
                text_md = _to_markdown_from_storage(rec.get("body_storage") or rec.get("body_html"))
                links = _extract_links_from_storage(rec.get("body_storage") or rec.get("body_html"))
            elif body_repr == "adf":
                text_md = _to_markdown_from_adf(rec.get("body_adf"))
                links = _extract_links_from_adf(rec.get("body_adf"))
            else:
                text_md = ""

            attachments = [
                {"filename": a.get("filename"), "url": a.get("download_url")}
                for a in (rec.get("attachments") or [])
            ]

            out_rec = {
                "id": rec.get("id"),
                "title": rec.get("title"),
                "space_key": rec.get("space_key"),
                "space_id": rec.get("space_id"),
                "url": rec.get("url"),
                "version": rec.get("version"),
                "created_at": rec.get("created_at"),
                "updated_at": rec.get("updated_at"),
                "body_repr": body_repr,
                "text_md": text_md,
                "links": sorted(dict.fromkeys(links)),
                "attachments": attachments,
                "source": "confluence",
            }

            if not text_md:
                empty += 1
            atts_count += len(attachments)
            chars += len(text_md)
            total += 1
            fout.write(json.dumps(out_rec, ensure_ascii=False) + "\n")
            if limit and total >= limit:
                break

    metrics = {
        "run_id": run_id,
        "input": str(inp),
        "output": str(nd_out),
        "pages": total,
        "empty_bodies": empty,
        "attachments": atts_count,
        "avg_chars": (chars // total) if total else 0,
        "completed_at": _now_iso(),
    }
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    manifest = {"phase": "normalize", "artifact": "normalized.ndjson", "run_id": run_id, "completed_at": _now_iso()}
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log.info("normalize.done", **metrics)
    return metrics
````

**C) Runner & CLI**
If not already present, wire normalize in the runner (add the elif phase == "normalize" branch) and add the normalize from-ingest CLI command (as in your previous Prompt 004; no change needed beyond keeping it in sync with the new function signature).

**D) Tests**

1. Storage path test — tests/test_normalize_storage.py

```python
import json
from pathlib import Path
from trailblazer.pipeline.steps.normalize.html_to_md import normalize_from_ingest
import trailblazer.core.artifacts as artifacts

def test_normalize_storage(tmp_path):
    rid = "2025-08-13_abcd"
    ingest = tmp_path / "runs" / rid / "ingest"
    outdir = tmp_path / "runs" / rid / "normalize"
    ingest.mkdir(parents=True, exist_ok=True)
    outdir.mkdir(parents=True, exist_ok=True)

    rec = {
        "id":"p1","title":"Hello","space_key":"DEV","space_id":"111",
        "url":"https://x/wiki/spaces/DEV/pages/1/Hello","version":1,
        "created_at":"2025-08-01T00:00:00Z","updated_at":"2025-08-02T00:00:00Z",
        "body_repr":"storage",
        "body_storage":"<h1>Title</h1><p>A <a href='https://x.y/z'>link</a></p>",
        "attachments":[{"filename":"a.png","download_url":"https://x/download/a.png"}]
    }
    nd = ingest / "confluence.ndjson"
    nd.write_text(json.dumps(rec)+"\n", encoding="utf-8")

    old = artifacts.ROOT; artifacts.ROOT = tmp_path
    try:
        m = normalize_from_ingest(outdir=str(outdir))
        assert m["pages"] == 1 and m["empty_bodies"] == 0
        out = (outdir/"normalized.ndjson").read_text(encoding="utf-8").strip()
        line = json.loads(out)
        assert line["body_repr"] == "storage"
        assert "# Title" in line["text_md"]
        assert line["links"] == ["https://x.y/z"]
        assert line["attachments"][0]["filename"] == "a.png"
    finally:
        artifacts.ROOT = old
```

2. ADF path test — tests/test_normalize_adf.py

```python
import json
from pathlib import Path
from trailblazer.pipeline.steps.normalize.html_to_md import normalize_from_ingest
import trailblazer.core.artifacts as artifacts

def test_normalize_adf(tmp_path):
    rid = "2025-08-13_efgh"
    ingest = tmp_path / "runs" / rid / "ingest"
    outdir = tmp_path / "runs" / rid / "normalize"
    ingest.mkdir(parents=True, exist_ok=True)
    outdir.mkdir(parents=True, exist_ok=True)

    adf = {
      "type": "doc",
      "version": 1,
      "content": [
        {"type":"heading","attrs":{"level":2},"content":[{"type":"text","text":"Title"}]},
        {"type":"paragraph","content":[
           {"type":"text","text":"A "},
           {"type":"text","text":"link","marks":[{"type":"link","attrs":{"href":"https://x.y/z"}}]},
           {"type":"text","text":" here."}
        ]}
      ]
    }
    rec = {
        "id":"p2","title":"Hello ADF","space_key":"DEV","space_id":"111",
        "url":"https://x/wiki/spaces/DEV/pages/2/HelloADF","version":1,
        "created_at":"2025-08-01T00:00:00Z","updated_at":"2025-08-03T00:00:00Z",
        "body_repr":"adf",
        "body_adf": adf,
        "attachments":[]
    }
    nd = ingest / "confluence.ndjson"
    nd.write_text(json.dumps(rec)+"\n", encoding="utf-8")

    old = artifacts.ROOT; artifacts.ROOT = tmp_path
    try:
        m = normalize_from_ingest(outdir=str(outdir))
        assert m["pages"] == 1 and m["empty_bodies"] == 0
        out = (outdir/"normalized.ndjson").read_text(encoding="utf-8").strip()
        line = json.loads(out)
        assert line["body_repr"] == "adf"
        assert line["links"] == ["https://x.y/z"]
        assert "## Title" in line["text_md"]
        assert "[link](https://x.y/z)" in line["text_md"]
    finally:
        artifacts.ROOT = old
```

3. Markdown consistency — keep the whitespace/heading unit test from your earlier Prompt 004.

**E) README**
Add/adjust:

````md
### Normalize (Storage & ADF → Markdown)
Trailblazer converts Confluence bodies to Markdown, supporting both **Storage (XHTML)** and **ADF JSON**.

```bash
trailblazer normalize from-ingest --run-id <RUN_ID>    # uses runs/<RUN_ID>/ingest/confluence.ndjson
# or:
trailblazer normalize from-ingest --input runs/<RUN_ID>/ingest/confluence.ndjson
````

Outputs → runs/\<RUN_ID>/normalize/:

- normalized.ndjson (one record per page, with body_repr, text_md, links, attachments)

- metrics.json, manifest.json

______________________________________________________________________

## Validation (run locally, then commit to main)

```bash
make setup
make fmt
make lint
make test

# sanity run (no network): create a run id and normalize
trailblazer run --phases normalize --dry-run
```

Commit to main only if all are green:

```bash
git add -A
git commit -m "feat(normalize): support Confluence Storage (XHTML) and ADF JSON → Markdown; tests; docs"
git push origin main
```

## Acceptance Criteria

- Ingest writes body_repr and body_storage or body_adf accordingly (and keeps old fields if present).

- trailblazer normalize from-ingest --run-id <RID> produces normalized.ndjson with text_md for both Storage and ADF records, plus metrics.json & manifest.json.

- Tests pass (pytest -q), and make fmt && make lint are clean.

- README updated to state Storage & ADF support.

- Prompt saved to prompts/004_normalize_both_storage_and_adf.md.
