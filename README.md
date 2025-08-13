# N2S Trailblazer (Python)

CLI-first monorepo for Navigate to SaaS (N2S) RAG + document generation.

## Quick start
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

trailblazer --help
trailblazer run --phases ingest normalize --dry-run
```

## Principles
- CLI-first, explicit phases (no numeric module names).
- Idempotent steps; artifacts under `runs/<run_id>/<phase>/`.
- Config via env / `configs/pipeline.yaml`.

### Ingest from Confluence (Cloud v2 + Basic)

Create `.env` from `configs/dev.env.example` and set:
- `CONFLUENCE_EMAIL`, `CONFLUENCE_API_TOKEN`
- `CONFLUENCE_BASE_URL` (defaults to `https://ellucian.atlassian.net/wiki`)
Run:
```bash
trailblazer ingest confluence --space DEV --since 2025-08-01T00:00:00Z --max-pages 10
```

Artifacts: `runs/<run_id>/ingest/`.

### Normalize (Storage & ADF → Markdown)
Trailblazer converts Confluence bodies to Markdown, supporting both **Storage (XHTML)** and **ADF JSON**.

```bash
trailblazer normalize from-ingest --run-id <RUN_ID>    # uses runs/<RUN_ID>/ingest/confluence.ndjson
# or:
trailblazer normalize from-ingest --input runs/<RUN_ID>/ingest/confluence.ndjson
```

Outputs → runs/<RUN_ID>/normalize/:

- normalized.ndjson (one record per page, with body_repr, text_md, links, attachments)

- metrics.json, manifest.json

### Implementation Details
- API base: https://ellucian.atlassian.net/wiki/api/v2
- Auth: Basic (email + API token)
- Use v2 for spaces/pages/attachments; use v1 CQL for search until v2 adds it.
