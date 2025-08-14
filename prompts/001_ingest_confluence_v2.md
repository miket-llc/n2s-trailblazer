# PROMPT 001 — Implement Confluence Ingest (Cloud v2 + Basic Auth)

**Save this prompt as:** `prompts/001_ingest_confluence_v2.md`

**You are:** a senior platform engineer extending the Trailblazer Python monorepo. Implement the **ingest/confluence** step using **Confluence Cloud v2** endpoints with **Basic auth (email + API token)**. Default Confluence site: `https://ellucian.atlassian.net/wiki`.

**Repo target:** `miket-llc/n2s-trailblazer`.
If the repo/editor isn't connected, create files locally and **stop before pushing**. If connected, **create a feature branch and push**.

______________________________________________________________________

## Goals

1. **Adapters:** Finish `ConfluenceClient` for v2 pages/spaces/attachments + v1 CQL search helper.
1. **Ingest step:** Fetch pages from one or more spaces (by **space keys** or **space ids**), optional **delta** (`--since`), collect **attachments**, and write **NDJSON** artifacts.
1. **CLI:** Add `trailblazer ingest confluence ...` command to run the step directly.
1. **Runner:** Keep `pipeline.run` behavior (ingest phase calls the same function).
1. **Idempotent:** Re-running with the same args should not error; output goes under `var/runs/<run_id>/ingest/`.
1. **Tests & docs:** Minimal tests + README updates.

______________________________________________________________________

## Files to Create/Modify (exact)

**1) `src/trailblazer/adapters/confluence_api.py`** — implement real client

- Keep `ConfluenceClient` using `httpx.Client` with **BasicAuth(email, api_token)** and `base_url="https://.../wiki"`.

- Implement methods (cursor pagination via `_links.next` **or** `Link` header):

  - `get_spaces(keys: list[str] | None, limit=100) -> Iterable[dict]` (v2 `/api/v2/spaces?keys=...`)
  - `get_pages(space_id: str | None, body_format: str | None, limit=100) -> Iterable[dict]` (v2 `/api/v2/pages?space-id=...&body-format=...`)
  - `get_page_by_id(page_id: str, body_format: str | None) -> dict` (v2 `/api/v2/pages/{id}?body-format=...`)
  - `get_attachments_for_page(page_id: str, limit=100) -> Iterable[dict]` (v2 `/api/v2/pages/{id}/attachments`)
  - `search_cql(cql: str, start=0, limit=50, expand: str | None = None) -> dict` (v1 `/rest/api/content/search?cql=...`; use to prefilter by `lastModified > ...` when `--since` is set)

- Add a tiny `_paginate(url, params)` helper that:

  - GETs the url with params on first call,
  - yields `data["results"]`,
  - follows `data["_links"]["next"]` if present, otherwise parses `Link` header for `rel="next"`.

- Log with `structlog` at **start/end** and for each page batch.

- Do **tenacity** retries with `wait_exponential(min=1, max=30)` and `stop_after_attempt(5)`.

**2) `src/trailblazer/core/models.py`** — enrich Page & Attachment models

Add/adjust models to match what we write to NDJSON:

```python
class Attachment(BaseModel):
    id: str
    filename: str | None = None
    media_type: str | None = None
    file_size: int | None = None
    download_url: str | None = None  # absolute URL

class Page(BaseModel):
    id: str
    title: str
    space_key: str | None = None
    space_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None  # from version.createdAt
    version: int | None = None
    body_html: str | None = None       # from v2 body (storage|adf)
    url: str | None = None             # _links.webui full URL
    attachments: list[Attachment] = []
    metadata: dict = {}
```

**3) `src/trailblazer/pipeline/steps/ingest/confluence.py`** — implement ingest

Implement:

```python
from ....adapters.confluence_api import ConfluenceClient
from ....core.models import Page, Attachment
from ....core.logging import log
from ....core.artifacts import phase_dir
from ....core.config import SETTINGS
from datetime import datetime
from pathlib import Path
import json
```

- Public function:
  `def ingest_confluence(outdir: str, space_keys: list[str] | None, space_ids: list[str] | None, since: datetime | None, body_format: str = "storage", max_pages: int | None = None) -> dict:`

  - Resolve **space_ids**: if keys provided, call `get_spaces(keys=...)` (v2) and map key→id.

  - **Delta logic**:

    - If `since` is given: use **CQL** to find candidate page IDs (e.g., `type=page AND lastModified > "<ISO>" AND space in (...)`), then fetch each page by **v2** `get_page_by_id(..., body_format)` to get bodies reliably.
      (Avoid v1 `expand=body.*` 50-item cap; use v2 for bodies.)
    - If `since` is not given: iterate v2 `get_pages(space-id=...)` per space and post-filter by `version.createdAt` if caller supplied `--since` anyway.

  - For each page:

    - Build **absolute** page URL from `_links.webui` (`base_url + webui` if needed).
    - Fetch **attachments** via v2, build `download_url` as absolute (`base_url + downloadLink`).
    - Map to `Page` + `Attachment` models; `updated_at` from `version.createdAt`, `version` from `version.number`.
    - Write **one JSON per line** to `confluence.ndjson` (UTF-8). Keep a simple `count` accumulator.

  - Return metrics: `{"spaces": n, "pages": n, "attachments": n, "since": since_iso_or_null}` and write them to `metrics.json`.

- Create files in `outdir`:

  - `confluence.ndjson` (pages with embedded attachments array)
  - `metrics.json` (counts, duration, args)
  - `manifest.json` (simple descriptor: run_id, phase, started_at, completed_at)

- If `max_pages` provided, stop after writing that many (useful for smoke tests).

**4) `src/trailblazer/pipeline/runner.py`** — call the new function

Replace the current placeholder:

```python
if phase == "ingest":
    from .steps.ingest.confluence import ingest_confluence
    ingest_confluence(out, space_keys=None, space_ids=None, since=None, body_format=SETTINGS.CONFLUENCE_BODY_FORMAT)
```

**5) `src/trailblazer/cli/main.py`** — add a nested command

- Add a Typer sub-app:

```python
ingest_app = typer.Typer(help="Ingestion commands")
app.add_typer(ingest_app, name="ingest")

@ingest_app.command("confluence")
def ingest_confluence_cmd(
    spaces: list[str] = typer.Option([], "--space", help="Space keys (e.g., DEV, DOCS)"),
    space_ids: list[str] = typer.Option([], "--space-id", help="Space IDs"),
    since: str | None = typer.Option(None, help="ISO timestamp (e.g., 2025-08-01T00:00:00Z)"),
    body_format: str = typer.Option("storage", help="storage or atlas_doc_format"),
    max_pages: int | None = typer.Option(None, help="Stop after N pages (debug)"),
):
    from ..core.artifacts import new_run_id, phase_dir
    from ..pipeline.steps.ingest.confluence import ingest_confluence
    rid = new_run_id()
    outdir = str(phase_dir(rid, "ingest"))
    dt = datetime.fromisoformat(since.replace("Z","+00:00")) if since else None
    metrics = ingest_confluence(outdir, spaces or None, space_ids or None, dt, body_format, max_pages)
    log.info("cli.ingest.confluence.done", run_id=rid, **metrics)
    typer.echo(rid)
```

**6) Tests**

- `tests/test_ingest_confluence_smoke.py`:

  - Monkeypatch `ConfluenceClient` methods to return **tiny fixtures** (1 space, 2 pages, 1 attachment) and assert:

    - `confluence.ndjson` exists with **2 lines**.
    - Each line parses to JSON and has `id`, `title`, `attachments` list (possibly empty).
    - `metrics.json` contains `pages=2`.

- `tests/test_confluence_client_pagination.py`:

  - Unit test a fake paginated response that includes `_links.next` and ensure the helper follows it.

**7) README**

Add a short section:

````md
### Ingest from Confluence (Cloud v2 + Basic auth)

1. Create `.env` from `configs/dev.env.example` and set:
   - `CONFLUENCE_EMAIL`, `CONFLUENCE_API_TOKEN`
   - `CONFLUENCE_BASE_URL` (default is `https://ellucian.atlassian.net/wiki`)
2. Run:
```bash
trailblazer ingest confluence --space DEV --since 2025-08-01T00:00:00Z
# or enumerate a space id:
trailblazer ingest confluence --space-id 123456
````

Artifacts appear under `var/runs/<run_id>/ingest/`.

````

**8) Git**

If connected:

```bash
git checkout -b feat/001-ingest-confluence-v2
git add -A
git commit -m "feat(ingest): Confluence Cloud v2 ingest + CLI + NDJSON artifacts"
git push -u origin feat/001-ingest-confluence-v2
````

______________________________________________________________________

## Design Notes & Constraints

- **Why v2 for bodies + attachments?** v2 `GET /pages` and `GET /pages/{id}` expose `body.storage` / `body.atlas_doc_format` via `body-format` and page objects include `_links.webui`; attachments expose `downloadLink`. v2 uses **cursor pagination** via `_links.next` / `Link` header. ([Atlassian Developer][1])
- **Why keep v1 CQL?** Use it only to pre-filter IDs for **delta** (e.g., `lastModified > ... AND type=page AND space = KEY`). Fetch page bodies via v2 afterward. ([Atlassian Developer][2])
- **Basic auth** is email + API token. (Fine for scripts; note Atlassian docs recommend OAuth for apps.) ([Atlassian Developer][3])
- **Spaces by keys**: v2 supports `GET /api/v2/spaces?keys=KEY1,KEY2` and returns `id` and `key`, plus `_links.next` for pagination. ([Atlassian Developer][4])
- **Pages by space**: v2 supports `GET /api/v2/pages?space-id=<id>&body-format=...&limit=...` and returns page `version` (with `createdAt`) and `body`. ([Atlassian Developer][1])

______________________________________________________________________

## Acceptance Criteria

- `trailblazer ingest confluence --space SOMEKEY --since 2025-08-01T00:00:00Z` runs and creates:

  - `var/runs/<run_id>/ingest/confluence.ndjson` (≥1 line if any pages match)
  - `var/runs/<run_id>/ingest/metrics.json` and `manifest.json`

- `trailblazer run --phases ingest --dry-run` still works (no network).

- Unit tests pass: `pytest -q`

- Linters pass: `ruff`, `black --check`, `mypy` (non-strict OK).

- Prompt saved to `prompts/001_ingest_confluence_v2.md`.

______________________________________________________________________

## Smoke Commands (once credentials are set)

```bash
# List help
trailblazer ingest confluence --help

# Pull a single space by key (storage body)
trailblazer ingest confluence --space DEV --since 2025-08-01T00:00:00Z

# Pull by space id (atlas_doc_format body)
trailblazer ingest confluence --space-id 123456 --since 2025-08-01T00:00:00Z --body-format atlas_doc_format

# Debug: cap to 10 pages
trailblazer ingest confluence --space DEV --since 2025-08-01T00:00:00Z --max-pages 10
```

______________________________________________________________________

## Implementation Tips

- **Absolute URLs:** Build with the client `base_url` (which already ends in `/wiki`). For a relative `_links.webui` or `downloadLink`, do `base_url.rstrip("/wiki") + <relative>` or use `urllib.parse.urljoin(base_url, rel)`.
- **Date parsing:** Confluence returns ISO strings. Use `datetime.fromisoformat(...replace("Z","+00:00"))` or `dateutil.parser` if installed.
- **Throughput:** Start sequential; we can add bounded async later.
- **Error handling:** If a page fails, log and continue (unless we add `--fail-fast` later).
- **Idempotency:** Don't overwrite an existing `confluence.ndjson` unless `--force` (not required now). Creating a new `run_id` each time is usually fine.

______________________________________________________________________

## After this lands

- We'll do **Prompt 002 — Normalize HTML→Markdown** (deterministic normalization, link preservation, attachment mapping).
- We'll also add a tiny **var/state/hwm** file in a later prompt to remember per-space cursors.

______________________________________________________________________

## References

- Confluence **REST API v2** index and **Page** endpoints (supports `space-id`, `body-format`, and cursor via `_links.next`). ([Atlassian Developer][5])
- Confluence **REST API v2** **Space** endpoints (supports `keys=` and cursor pagination). ([Atlassian Developer][4])
- Confluence **REST API v2** **Attachment** endpoints (`/pages/{id}/attachments`, `downloadLink`). ([Atlassian Developer][6])
- **CQL** guide and example of calling `/wiki/rest/api/content/search?cql=...` (use for delta filtering). ([Atlassian Developer][2])
- **Basic auth** with Atlassian account email + API token (Confluence Cloud). ([Atlassian Developer][3])

______________________________________________________________________

note that the confluence API key is

ATATT3xFfGF0Rfm7lSu2cEMAttKeQ_rsa4DmF2M3z1tB5azP_B4TOx92jev1xh9YUgR55dVNfHCps2zPvTgVb-H_4EkL8B29SzZwSjBnG-7Wc5saFFTjmhwF_bxkuDQI0tIuoeR_rYU1IyV1xlIASmt_NgFIrgl2IiJsDjheyt5aJ1pPDz9LVUE=F9653BC4

and the email address to use is michael.thompson@ellucian.com

you'll need to save both of course. if and only if you need it, the cloud id for the ellucian.atlassian.net/wiki site is

89daa32b-93ca-43e5-a9ce-feeefab105c1

[1]: https://developer.atlassian.com/cloud/confluence/rest/v2/api-group-page/ "The Confluence Cloud REST API"
[2]: https://developer.atlassian.com/cloud/confluence/advanced-searching-using-cql/ "Advanced searching using CQL"
[3]: https://developer.atlassian.com/cloud/confluence/basic-auth-for-rest-apis/ "Basic auth for REST APIs"
[4]: https://developer.atlassian.com/cloud/confluence/rest/v2/api-group-space/ "The Confluence Cloud REST API"
[5]: https://developer.atlassian.com/cloud/confluence/rest/ "The Confluence Cloud REST API"
[6]: https://developer.atlassian.com/cloud/confluence/rest/v2/api-group-attachment/ "The Confluence Cloud REST API"
