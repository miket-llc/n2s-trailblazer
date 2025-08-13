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

## Confluence Ingest

### Ingest from Confluence (Cloud v2 + Basic auth)

1. Create `.env` from `configs/dev.env.example` and set:
   - `CONFLUENCE_EMAIL`, `CONFLUENCE_API_TOKEN`
   - `CONFLUENCE_BASE_URL` (default is `https://ellucian.atlassian.net/wiki`)
2. Run:
```bash
trailblazer ingest confluence --space DEV --since 2025-08-01T00:00:00Z
# or enumerate a space id:
trailblazer ingest confluence --space-id 123456
```

Artifacts appear under `runs/<run_id>/ingest/`.

### Implementation Details
- API base: https://ellucian.atlassian.net/wiki/api/v2
- Auth: Basic (email + API token)
- Use v2 for spaces/pages/attachments; use v1 CQL for search until v2 adds it.
