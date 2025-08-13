# Trailblazer

**AI-powered knowledge base builder:** ingests Navigate-to-SaaS and Ellucian 
documentation (Confluence + official docs), organizes everything into a typed 
graph with embeddings, and makes it easy to query and generate the docs we need.

## Quick start

```bash
# 1) Setup (creates .venv, installs dev deps, installs pre-commit)
make setup

# 2) Validate everything works
make fmt && make lint && make test

# 3) Help
trailblazer --help
```

## Working agreements
- **Main branch only** - commit atomically to main, no feature branches for routine work
- **Toolchain required** - always run `make fmt && make lint && make test` before committing
- **Artifacts immutable** - runs write to `runs/<run_id>/<phase>/`, never mutate previous runs

📖 **See [mindfile](docs/2025-08-13-1308-trailblazer-mindfile.md) for comprehensive architecture, contracts, and development guidelines.**

## Usage

### 1. Ingest from Confluence

Create `.env` from `configs/dev.env.example` and set:
- `CONFLUENCE_EMAIL`, `CONFLUENCE_API_TOKEN`  
- `CONFLUENCE_BASE_URL` (defaults to `https://ellucian.atlassian.net/wiki`)

```bash
# Small test ingest
trailblazer ingest confluence --space DEV --since 2025-08-01T00:00:00Z --max-pages 10
# → outputs to runs/<run_id>/ingest/
```

### 2. Normalize to Markdown

Converts Confluence bodies (Storage XHTML + ADF JSON) to clean Markdown:

```bash
# Normalize from a previous ingest run
trailblazer normalize from-ingest --run-id <RUN_ID>
# → outputs to runs/<RUN_ID>/normalize/normalized.ndjson
```

### 3. Full pipeline

```bash
# Run multiple phases in sequence
trailblazer run --phases ingest normalize --dry-run
```

## Technical details

- **Pipeline:** ingest → normalize (Storage & ADF) → enrich/classify → embed → retrieve → compose/create → audit
- **API:** Confluence Cloud v2 (`/wiki/api/v2`) with Basic auth; v1 CQL for delta filtering
- **Data:** NDJSON artifacts with deterministic transforms; PostgreSQL + pgvector (planned)
- **Auth:** Store `CONFLUENCE_EMAIL` + `CONFLUENCE_API_TOKEN` in local `.env` only
