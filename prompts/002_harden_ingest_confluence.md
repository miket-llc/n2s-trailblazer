# PROMPT 002 — Harden & Complete Confluence Ingest (Cloud v2, Basic Auth) + CLI + Tests

**Save this prompt as:** `prompts/002_harden_ingest_confluence.md`

**You are:** the lead engineer on Trailblazer (Python). This prompt must **finish** Confluence ingest using **Cloud v2** with **Basic auth (email + API token)** and wire it into the CLI + pipeline so we can run real pulls. It must be **additive**: if 001 already exists, extend/refactor safely; if it doesn't, **implement the missing pieces now**.

**Repo:** `miket-llc/n2s-trailblazer`
**Branch:** create `feat/002-ingest-confluence-harden` (or reuse an open feature branch if 001 already created one).

---

## Objectives

1. **Adapters (v2 + Basic)**: Ensure the Confluence client is complete and defensive (cursor pagination, robust body parsing, attachments).
2. **Models**: Add `Attachment` and upgrade `Page` to include timestamps, url, attachments.
3. **Ingest step**: Implement `ingest_confluence(...)` that resolves spaces, supports `--since` (via v1 CQL prefilter), fetches v2 bodies + attachments, and writes **NDJSON** + `metrics.json` + `manifest.json`.
4. **CLI**: Add `trailblazer ingest confluence …` with options for spaces/ids/since/body-format/max-pages.
5. **Runner**: Keep phase execution working; if `ingest` runs via `runner`, it should call the same function.
6. **Tests**: Add smoke tests with fakes for pagination and mapping; no network required.
7. **Docs**: Update README; ensure `.gitignore` ignores `data/` and `runs/`.

---

## Changes to Make (exact)

### 0) Housekeeping

* Ensure `.gitignore` includes:

  ```
  data/
  runs/
  ```
* If `docs/trailblazer-mindfile.md` is missing, add it from our last message (keep it brief if needed).

---

### 1) Models — `src/trailblazer/core/models.py`

Add or replace with:

```python
from pydantic import BaseModel
from datetime import datetime
from typing import List, Dict, Optional

class Attachment(BaseModel):
    id: str
    filename: Optional[str] = None
    media_type: Optional[str] = None
    file_size: Optional[int] = None
    download_url: Optional[str] = None  # absolute url

class Page(BaseModel):
    id: str
    title: str
    space_key: Optional[str] = None
    space_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None   # version.createdAt
    version: Optional[int] = None
    body_html: Optional[str] = None         # storage/adf rendered html (v2 body-format)
    url: Optional[str] = None               # absolute web URL
    attachments: List[Attachment] = []
    metadata: Dict = {}
```

---

### 2) Confluence client — `src/trailblazer/adapters/confluence_api.py`

Harden or implement the following:

```python
from typing import Dict, Iterable, Optional, List
from datetime import datetime
import httpx
from httpx import BasicAuth
from tenacity import retry, wait_exponential, stop_after_attempt
from urllib.parse import urljoin
from ..core.config import SETTINGS
from ..core.logging import log

V2_PREFIX = "/api/v2"

class ConfluenceClient:
    def __init__(self, base_url: Optional[str] = None, email: Optional[str] = None, token: Optional[str] = None):
        base = (base_url or SETTINGS.CONFLUENCE_BASE_URL or "").rstrip("/")
        if not base.endswith("/wiki"):
            base = base + "/wiki"
        self.site_base = base                      # e.g. https://ellucian.atlassian.net/wiki
        self.api_base = self.site_base             # httpx base_url
        self._client = httpx.Client(
            base_url=self.api_base,
            timeout=30.0,
            auth=BasicAuth(email or SETTINGS.CONFLUENCE_EMAIL or "", token or SETTINGS.CONFLUENCE_API_TOKEN or ""),
            headers={"Accept": "application/json"},
        )

    # ---------- pagination helper ----------
    def _next_link(self, resp: httpx.Response, data: Dict) -> Optional[str]:
        nxt = (data.get("_links") or {}).get("next")
        if nxt:
            # v2 returns absolute or relative; normalize
            return nxt if nxt.startswith("http") else urljoin(self.api_base + "/", nxt.lstrip("/"))
        # fallback: Link header
        link = resp.headers.get("Link", "")
        # very simple parse
        for part in link.split(","):
            if 'rel="next"' in part:
                url = part.split(";")[0].strip().strip("<>")
                return url if url.startswith("http") else urljoin(self.api_base + "/", url.lstrip("/"))
        return None

    def _paginate(self, url: str, params: Optional[Dict] = None) -> Iterable[Dict]:
        first = True
        while True:
            r = self._client.get(url, params=params if first else None)
            r.raise_for_status()
            data = r.json()
            yield from data.get("results", [])
            nxt = self._next_link(r, data)
            if not nxt:
                break
            url, params, first = nxt, None, False

    # ---------- v2 ----------
    @retry(wait=wait_exponential(min=1, max=30), stop=stop_after_attempt(5))
    def get_spaces(self, keys: Optional[List[str]] = None, limit: int = 100) -> Iterable[Dict]:
        params = {"limit": limit}
        if keys:
            params["keys"] = ",".join(keys)
        yield from self._paginate(f"{V2_PREFIX}/spaces", params)

    @retry(wait=wait_exponential(min=1, max=30), stop=stop_after_attempt(5))
    def get_pages(self, space_id: Optional[str] = None, body_format: Optional[str] = None, limit: int = 100) -> Iterable[Dict]:
        params = {"limit": limit}
        if space_id:
            params["space-id"] = space_id
        if body_format:
            params["body-format"] = body_format
        yield from self._paginate(f"{V2_PREFIX}/pages", params)

    @retry(wait=wait_exponential(min=1, max=30), stop=stop_after_attempt(5))
    def get_page_by_id(self, page_id: str, body_format: Optional[str] = None) -> Dict:
        params = {}
        if body_format:
            params["body-format"] = body_format
        r = self._client.get(f"{V2_PREFIX}/pages/{page_id}", params=params)
        r.raise_for_status()
        return r.json()

    @retry(wait=wait_exponential(min=1, max=30), stop=stop_after_attempt(5))
    def get_attachments_for_page(self, page_id: str, limit: int = 100) -> Iterable[Dict]:
        params = {"limit": limit}
        yield from self._paginate(f"{V2_PREFIX}/pages/{page_id}/attachments", params)

    # ---------- v1 CQL (delta prefilter only) ----------
    @retry(wait=wait_exponential(min=1, max=30), stop=stop_after_attempt(5))
    def search_cql(self, cql: str, start: int = 0, limit: int = 50, expand: Optional[str] = None) -> Dict:
        params = {"cql": cql, "start": start, "limit": limit}
        if expand:
            params["expand"] = expand
        r = self._client.get("/rest/api/content/search", params=params)
        r.raise_for_status()
        return r.json()

    # helpers
    def absolute(self, rel_or_abs: Optional[str]) -> Optional[str]:
        if not rel_or_abs:
            return None
        return rel_or_abs if rel_or_abs.startswith("http") else urljoin(self.site_base + "/", rel_or_abs.lstrip("/"))
```

---

### 3) Ingest step — `src/trailblazer/pipeline/steps/ingest/confluence.py`

Implement the real ingest:

```python
from pathlib import Path
from datetime import datetime
import json
from typing import Dict, Iterable, List, Optional, Tuple
from ....adapters.confluence_api import ConfluenceClient
from ....core.models import Page, Attachment
from ....core.logging import log
from ....core.config import SETTINGS

def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat().replace("+00:00", "Z") if dt else None

def _body_html_from_v2(page_obj: Dict) -> Optional[str]:
    # Defensive parsing: v2 may nest body by requested format
    body = page_obj.get("body") or {}
    # Try storage first
    storage = body.get("storage") or {}
    if storage.get("value"):
        return storage["value"]
    # Fallback: atlas_doc_format may be under "atlas_doc_format" as rendered HTML or JSON; leave None if not rendered
    adf = body.get("atlas_doc_format") or {}
    if isinstance(adf.get("value"), str):
        return adf["value"]
    return None

def _page_url(site_base: str, page_obj: Dict) -> Optional[str]:
    webui = (page_obj.get("_links") or {}).get("webui")
    if not webui:
        return None
    from urllib.parse import urljoin
    return urljoin(site_base + "/", webui.lstrip("/"))

def _map_attachment(site_base: str, att: Dict) -> Attachment:
    dl = (att.get("_links") or {}).get("download") or att.get("downloadLink")
    from urllib.parse import urljoin
    return Attachment(
        id=str(att.get("id")),
        filename=att.get("title") or att.get("filename"),
        media_type=att.get("mediaType") or att.get("type"),
        file_size=att.get("fileSize") or att.get("size"),
        download_url=urljoin(site_base + "/", dl.lstrip("/")) if dl else None,
    )

def _map_page(site_base: str, space_key_by_id: Dict[str, str], obj: Dict) -> Page:
    version = obj.get("version") or {}
    page = Page(
        id=str(obj.get("id")),
        title=obj.get("title") or "",
        space_id=str(obj.get("spaceId")) if obj.get("spaceId") is not None else None,
        space_key=space_key_by_id.get(str(obj.get("spaceId"))) if obj.get("spaceId") else None,
        version=version.get("number"),
        updated_at=datetime.fromisoformat(version["createdAt"].replace("Z","+00:00")) if version.get("createdAt") else None,
        created_at=datetime.fromisoformat(obj["createdAt"].replace("Z","+00:00")) if obj.get("createdAt") else None,
        body_html=_body_html_from_v2(obj),
        url=_page_url(site_base, obj),
        attachments=[],
        metadata={"raw_links": obj.get("_links", {})},
    )
    return page

def _resolve_space_map(client: ConfluenceClient, space_keys: Optional[List[str]], space_ids: Optional[List[str]]) -> Tuple[List[str], Dict[str,str]]:
    space_id_list: List[str] = []
    space_key_by_id: Dict[str, str] = {}

    # Resolve keys -> ids via v2
    if space_keys:
        for s in client.get_spaces(keys=space_keys):
            sid = str(s.get("id"))
            skey = s.get("key")
            if sid:
                space_id_list.append(sid)
                if skey:
                    space_key_by_id[sid] = skey

    # Include any provided ids explicitly
    if space_ids:
        for sid in space_ids:
            if sid not in space_id_list:
                space_id_list.append(sid)

    return space_id_list, space_key_by_id

def _cql_for_since(space_keys: List[str], since: datetime) -> str:
    # lastModified uses Confluence time fields; ensure Z
    iso = _iso(since) or ""
    if space_keys:
        keys = " OR ".join([f'space="{k}"' for k in space_keys])
        return f'type=page AND lastModified > "{iso}" AND ({keys}) ORDER BY lastmodified ASC'
    return f'type=page AND lastModified > "{iso}" ORDER BY lastmodified ASC'

def ingest_confluence(
    outdir: str,
    space_keys: Optional[List[str]] = None,
    space_ids: Optional[List[str]] = None,
    since: Optional[datetime] = None,
    body_format: str = "storage",
    max_pages: Optional[int] = None,
) -> Dict:
    """
    Fetch pages via v2 (bodies + attachments). If since is provided, prefilter ids with v1 CQL.
    Write one Page per line to confluence.ndjson and emit metrics/manifest.
    """
    Path(outdir).mkdir(parents=True, exist_ok=True)
    ndjson_path = Path(outdir) / "confluence.ndjson"
    metrics_path = Path(outdir) / "metrics.json"
    manifest_path = Path(outdir) / "manifest.json"

    client = ConfluenceClient()
    site_base = client.site_base

    # Resolve spaces
    space_id_list, space_key_by_id = _resolve_space_map(client, space_keys, space_ids)
    num_spaces = len(space_id_list) if (space_id_list or space_keys) else 0

    # Determine candidate page IDs if since provided
    candidate_ids: Optional[List[str]] = None
    if since:
        cql = _cql_for_since(space_keys or list(space_key_by_id.values()), since)
        start, ids = 0, []
        while True:
            data = client.search_cql(cql=cql, start=start, limit=50)
            results = data.get("results", [])
            if not results:
                break
            ids.extend([str(r.get("id")) for r in results if r.get("id") is not None])
            if len(results) < 50:
                break
            start += 50
        candidate_ids = ids

    # Iterate pages
    written_pages = 0
    written_attachments = 0

    with ndjson_path.open("w", encoding="utf-8") as out:
        def write_page_obj(p: Page):
            nonlocal written_pages, written_attachments
            d = p.model_dump()
            out.write(json.dumps(d, ensure_ascii=False) + "\n")
            written_pages += 1
            written_attachments += len(p.attachments)

        if candidate_ids is not None:
            for pid in candidate_ids:
                obj = client.get_page_by_id(pid, body_format=body_format)
                page = _map_page(site_base, space_key_by_id, obj)
                # attachments
                for att in client.get_attachments_for_page(page.id):
                    page.attachments.append(_map_attachment(site_base, att))
                write_page_obj(page)
                if max_pages and written_pages >= max_pages:
                    break
        else:
            # full space scans
            target_spaces = space_id_list or [None]  # None => all pages
            for sid in target_spaces:
                for obj in client.get_pages(space_id=sid, body_format=body_format):
                    page = _map_page(site_base, space_key_by_id, obj)
                    for att in client.get_attachments_for_page(page.id):
                        page.attachments.append(_map_attachment(site_base, att))
                    write_page_obj(page)
                    if max_pages and written_pages >= max_pages:
                        break
                if max_pages and written_pages >= max_pages:
                    break

    # metrics + manifest
    metrics = {
        "spaces": num_spaces,
        "pages": written_pages,
        "attachments": written_attachments,
        "since": _iso(since),
        "body_format": body_format,
    }
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    manifest = {
        "phase": "ingest",
        "artifact": "confluence.ndjson",
        "completed_at": _iso(datetime.utcnow()),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    log.info("ingest.confluence.done", **metrics, out=str(ndjson_path))
    return metrics
```

---

### 4) Runner — `src/trailblazer/pipeline/runner.py`

Ensure ingest calls the real function:

```python
def _execute_phase(phase: str, out: str) -> None:
    if phase == "ingest":
        from .steps.ingest.confluence import ingest_confluence
        ingest_confluence(outdir=out)
```

*(If you already pass args via config, keep that; default to env/SETTINGS unless CLI is used.)*

---

### 5) CLI — `src/trailblazer/cli/main.py`

Add a nested subcommand:

```python
import typer
from typing import List, Optional
from datetime import datetime
from ..core.logging import setup_logging, log
from ..core.config import SETTINGS
from ..pipeline.runner import run as run_pipeline

app = typer.Typer(add_completion=False, help="Trailblazer CLI")
ingest_app = typer.Typer(help="Ingestion commands")
app.add_typer(ingest_app, name="ingest")

@app.callback()
def _init() -> None:
    setup_logging()

@app.command()
def version() -> None:
    from .. import __version__
    typer.echo(__version__)

@app.command()
def run(
    phases: Optional[List[str]] = typer.Option(None, help="Subset of phases to run, in order"),
    dry_run: bool = typer.Option(False, help="Do not execute; just scaffold outputs"),
) -> None:
    rid = run_pipeline(phases=phases, dry_run=dry_run)
    log.info("cli.run.done", run_id=rid)

@ingest_app.command("confluence")
def ingest_confluence_cmd(
    space: List[str] = typer.Option([], "--space", help="Confluence space keys"),
    space_id: List[str] = typer.Option([], "--space-id", help="Confluence space ids"),
    since: Optional[str] = typer.Option(None, help='ISO timestamp, e.g. "2025-08-01T00:00:00Z"'),
    body_format: str = typer.Option("storage", help="storage or atlas_doc_format"),
    max_pages: Optional[int] = typer.Option(None, help="Stop after N pages (debug)"),
) -> None:
    from ..core.artifacts import new_run_id, phase_dir
    from ..pipeline.steps.ingest.confluence import ingest_confluence
    rid = new_run_id()
    out = str(phase_dir(rid, "ingest"))
    dt = datetime.fromisoformat(since.replace("Z","+00:00")) if since else None
    metrics = ingest_confluence(outdir=out, space_keys=space or None, space_ids=space_id or None, since=dt, body_format=body_format, max_pages=max_pages)
    log.info("cli.ingest.confluence.done", run_id=rid, **metrics)
    typer.echo(rid)
```

---

### 6) Tests

**`tests/test_ingest_confluence_smoke.py`**

```python
import json
from pathlib import Path
from datetime import datetime
import types

def test_ingest_writes_ndjson(tmp_path, monkeypatch):
    # fake client methods
    from trailblazer.pipeline.steps.ingest import confluence as step

    class FakeClient:
        site_base = "https://example.atlassian.net/wiki"
        def get_spaces(self, keys=None, limit=100):
            yield {"id": "111", "key": "DEV"}
        def get_pages(self, space_id=None, body_format=None, limit=100):
            yield {"id": "p1", "title": "T1", "spaceId": "111", "version": {"number": 1, "createdAt": "2025-08-10T12:00:00Z"}, "_links":{"webui":"/spaces/DEV/pages/p1/T1"}, "createdAt":"2025-08-01T00:00:00Z", "body":{"storage":{"value":"<p>hi</p>"}}}
            yield {"id": "p2", "title": "T2", "spaceId": "111", "version": {"number": 2, "createdAt": "2025-08-11T12:00:00Z"}, "_links":{"webui":"/spaces/DEV/pages/p2/T2"}, "createdAt":"2025-08-02T00:00:00Z", "body":{"storage":{"value":"<p>bye</p>"}}}
        def get_page_by_id(self, page_id, body_format=None):
            return {}
        def get_attachments_for_page(self, page_id, limit=100):
            if page_id == "p1":
                yield {"id":"a1","title":"file.png","_links":{"download":"/download/attachments/p1/file.png"}}
            else:
                return
        def search_cql(self, cql, start=0, limit=50, expand=None):
            return {"results":[]}

    monkeypatch.setattr(step, "ConfluenceClient", lambda: FakeClient())
    out = tmp_path / "out"
    metrics = step.ingest_confluence(str(out), space_keys=["DEV"], since=None, body_format="storage", max_pages=None)

    nd = out / "confluence.ndjson"
    assert nd.exists()
    lines = nd.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    rec = json.loads(lines[0])
    assert rec["id"] == "p1"
    assert rec["attachments"][0]["filename"] == "file.png"
    m = json.loads((out / "metrics.json").read_text())
    assert m["pages"] == 2
```

**`tests/test_confluence_pagination.py`**

```python
from trailblazer.adapters.confluence_api import ConfluenceClient
import httpx
import pytest

def test_next_link_parsing(monkeypatch):
    c = ConfluenceClient(base_url="https://example.atlassian.net/wiki", email="e", token="t")
    # simulate response with _links.next
    class FakeResp:
        headers = {}
        def json(self):
            return {"results":[{"id":"1"}], "_links":{"next":"https://example.atlassian.net/wiki/api/v2/pages?cursor=abc"}}
    nxt = c._next_link(FakeResp(), FakeResp().json())
    assert "cursor=abc" in nxt
```

---

### 7) README update

Add:

````md
### Ingest from Confluence (Cloud v2 + Basic)

Create `.env` from `configs/dev.env.example` and set:
- `CONFLUENCE_EMAIL`, `CONFLUENCE_API_TOKEN`
- `CONFLUENCE_BASE_URL` (defaults to `https://ellucian.atlassian.net/wiki`)
Run:
```bash
trailblazer ingest confluence --space DEV --since 2025-08-01T00:00:00Z --max-pages 10
````

Artifacts: `runs/<run_id>/ingest/`.

````

---

## Commit sequence

```bash
git checkout -b feat/002-ingest-confluence-harden
git add -A
git commit -m "feat(ingest): complete v2 Confluence ingest + CLI + NDJSON + tests"
# if repo is connected:
git push -u origin feat/002-ingest-confluence-harden
````

---

## Acceptance Criteria

* `trailblazer ingest confluence --space <KEY> --since <ISO>` writes:

  * `runs/<run_id>/ingest/confluence.ndjson` (≥1 line when pages exist)
  * `runs/<run_id>/ingest/metrics.json` with counts
  * `runs/<run_id>/ingest/manifest.json`
* `trailblazer run --phases ingest` works (uses same function).
* Tests pass locally: `pytest -q`.
* Linters pass: `ruff`, `black --check`, `mypy` (non-strict OK).
* Prompt saved to `prompts/002_harden_ingest_confluence.md`.

---

## Notes & guardrails

* **Delta strategy:** use **v1 CQL** only to enumerate candidate IDs when `--since` is provided; always fetch bodies via **v2**.
* **Body parsing:** be defensive; `body.storage.value` is preferred; ADF may differ — leave `body_html=None` if not rendered by API.
* **Absolute URLs:** normalize via `urljoin` against the `/wiki` base.
* **Idempotent:** each run creates a new `run_id`; do not mutate previous artifacts.
* **No network in tests:** rely on monkeypatch fakes.
