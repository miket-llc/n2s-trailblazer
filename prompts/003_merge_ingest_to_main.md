# PROMPT 003 — Bring Confluence ingest to main + add tests & docs

You are: lead engineer finalizing Confluence ingest on the main branch for miket-llc/n2s-trailblazer.
Start with the content of prompts/000_shared_guardrails.md above this line (paste it in as the preamble).

## Objectives

Implement real Confluence ingest (Cloud v2, Basic Auth).

Models: add Attachment, update Page to include timestamps, URL, attachments, metadata.

CLI: add trailblazer ingest confluence with options.

Runner: call the real ingest on the ingest phase.

Tests: add smoke + pagination unit tests (no network).

Docs: README section for ingest; ensure .gitignore ignores data/ and runs/.

Validation: run make fmt && make lint && make test and a small CLI smoke run.

## Changes to make

### 1) Models — src/trailblazer/core/models.py

Replace current Page and add Attachment:

```python
from pydantic import BaseModel
from datetime import datetime
from typing import List, Dict, Optional

class Attachment(BaseModel):
    id: str
    filename: Optional[str] = None
    media_type: Optional[str] = None
    file_size: Optional[int] = None
    download_url: Optional[str] = None  # absolute

class Page(BaseModel):
    id: str
    title: str
    space_key: Optional[str] = None
    space_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None  # version.createdAt
    version: Optional[int] = None
    body_html: Optional[str] = None       # storage/adf rendered html
    url: Optional[str] = None             # absolute
    attachments: List[Attachment] = []
    metadata: Dict = {}
```

### 2) Ingest step — src/trailblazer/pipeline/steps/ingest/confluence.py

Replace the stub with a real ingest_confluence(...):

- Resolve space keys → ids using v2 get_spaces(keys=...).
- If since provided: use v1 CQL to list candidate IDs (type=page AND lastModified > "ISO" AND space in (...)), then fetch each page by v2 (get_page_by_id(..., body-format=...)).
- If no since: iterate v2 get_pages(space-id=..., body-format=...).
- For each page: map to Page, fetch attachments via v2, build absolute URLs from \_links.webui and downloadLink.
- Write NDJSON (confluence.ndjson, one Page per line), plus metrics.json and manifest.json.

### 3) CLI — src/trailblazer/cli/main.py

Add an ingest sub-app and command:

```python
ingest_app = typer.Typer(help="Ingestion commands")
app.add_typer(ingest_app, name="ingest")

@ingest_app.command("confluence")
def ingest_confluence_cmd(
    space: List[str] = typer.Option([], "--space", help="Confluence space keys"),
    space_id: List[str] = typer.Option([], "--space-id", help="Confluence space ids"),
    since: Optional[str] = typer.Option(None, help='e.g. "2025-08-01T00:00:00Z"'),
    body_format: str = typer.Option("storage", help="storage or atlas_doc_format"),
    max_pages: Optional[int] = typer.Option(None, help="Stop after N pages (debug)"),
) -> None:
    from ..core.artifacts import new_run_id, phase_dir
    from ..pipeline.steps.ingest.confluence import ingest_confluence
    from datetime import datetime
    rid = new_run_id()
    out = str(phase_dir(rid, "ingest"))
    dt = datetime.fromisoformat(since.replace("Z","+00:00")) if since else None
    metrics = ingest_confluence(outdir=out, space_keys=space or None, space_ids=space_id or None,
                                since=dt, body_format=body_format, max_pages=max_pages)
    log.info("cli.ingest.confluence.done", run_id=rid, **metrics)
    typer.echo(rid)
```

### 4) Runner — src/trailblazer/pipeline/runner.py

Swap the stub for the real function:

```python
if phase == "ingest":
    from .steps.ingest.confluence import ingest_confluence
    ingest_confluence(outdir=out)
```

### 5) Tests

- tests/test_ingest_confluence_smoke.py: monkeypatch a fake ConfluenceClient (no network) → assert confluence.ndjson lines, attachments mapped, metrics.json counts.
- tests/test_confluence_pagination.py: unit test pagination helper / next-link parsing.

### 6) README

Add a section:

````md
### Ingest from Confluence (Cloud v2 + Basic)
Create `.env` from `configs/dev.env.example`:
- `CONFLUENCE_EMAIL`, `CONFLUENCE_API_TOKEN`
- `CONFLUENCE_BASE_URL` (default `https://ellucian.atlassian.net/wiki`)

Run:
```bash
trailblazer ingest confluence --space DEV --since 2025-08-01T00:00:00Z --max-pages 10
````

Artifacts appear under runs/\<run_id>/ingest/.

````

### 7) Pre-commit: add a pre-push test gate (optional but recommended)

Append to `.pre-commit-config.yaml`:

```yaml
- repo: local
  hooks:
    - id: pytest-on-push
      name: pytest on push
      entry: pytest -q
      language: system
      pass_filenames: false
      stages: [push]
````

## Validation (run locally, paste outputs)

```bash
make fmt
make lint
make test
trailblazer run --phases ingest --dry-run
# then a tiny live check (with creds set)
trailblazer ingest confluence --space DEV --max-pages 2 --since 2025-08-01T00:00:00Z
```

Only commit/push to main if all of the above succeed.
