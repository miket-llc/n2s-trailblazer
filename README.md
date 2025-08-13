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

## Confluence
- API base: https://ellucian.atlassian.net/wiki/api/v2
- Auth: Basic (email + API token)
- Use v2 for spaces/pages/attachments; use v1 CQL endpoint for search until v2 adds it.
