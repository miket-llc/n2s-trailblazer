# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project Overview

Trailblazer is an AI-powered knowledge base builder for Ellucian that ingests Navigate-to-SaaS and Ellucian documentation (Confluence + official docs), organizes everything into a typed graph with embeddings, and makes it easy to query and generate the docs we need.

**Pipeline Flow:** ingest → normalize → enrich → embed → retrieve → ask

## Quick Development Setup

```bash
# 1. Initial setup (creates .venv, installs dev deps, pre-commit)
make setup

# 2. Validate everything works
make fmt && make lint && make test

# 3. Start database
make db.up && trailblazer db init && trailblazer db doctor

# 4. Test the CLI
trailblazer --help
```

## Common Development Tasks

### Code Quality & Testing

```bash
# Format, lint, and test (run before every commit)
make ci

# Individual commands
make fmt      # Format code with ruff and markdown
make lint     # Check code with ruff, mypy, and markdownlint  
make test     # Run pytest
make check-md # Validate markdown files

# Database operations
make db.up    # Start PostgreSQL container
make db.down  # Stop PostgreSQL container
make db.wait  # Wait for database readiness
```

### Running the Pipeline

```bash
# Golden path workflow
trailblazer plan                              # Preview what would be ingested
trailblazer ingest-all --from-scratch         # Ingest everything 
trailblazer normalize-all                     # Normalize to unified format
trailblazer status                            # Check workspace status

# Embedding and retrieval (requires database)
trailblazer embed corpus --provider openai --model text-embedding-3-small --dimensions 1536
trailblazer ask "How do I configure SSO?"     # Query the knowledge base
```

### Running Individual Tests

```bash
# Run specific test file
pytest tests/test_confluence_client_pagination.py -v

# Run tests with specific markers
pytest -m integration

# Run tests with pattern matching
pytest -k "test_embed" -v
```

## Architecture Overview

### Core Components

- **CLI Layer** (`src/trailblazer/cli/`): Typer-based command interface with subcommands
- **Core** (`src/trailblazer/core/`): Configuration, logging, paths, models, events
- **Adapters** (`src/trailblazer/adapters/`): External system integrations (Confluence, DITA)
- **Pipeline** (`src/trailblazer/pipeline/`): Orchestration and processing steps
- **Database** (`src/trailblazer/db/`): PostgreSQL + pgvector integration
- **Retrieval** (`src/trailblazer/retrieval/`): Dense vector search and context packing
- **QA** (`src/trailblazer/qa/`): Quality assurance for retrieval

### Data Flow & Artifacts

All tool-managed artifacts are stored under `var/` (never modify manually):

```
var/
├── runs/{run_id}/          # Per-run artifacts
│   ├── ingest/            # Raw ingested data (confluence.ndjson, etc.)
│   ├── normalize/         # Normalized markdown (normalized.ndjson)
│   ├── enrich/           # Enriched metadata (enriched.jsonl)
│   ├── chunk/            # Chunked documents (chunks.ndjson)
│   └── embed/            # Embedding artifacts (embed_assurance.json)
├── logs/                  # Operation logs (NDJSON + pretty)
├── backups/              # Database backups (critical!)
├── state/                # Auto-since tracking
└── progress/             # Progress tracking files
```

### Configuration System

- **Config precedence:** config file < env vars < CLI flags
- **Auto-discovery:** `.trailblazer.{yaml,yml,toml}` in project root
- **Environment:** Use `.env` file for secrets (never commit)
- **Settings class:** `src/trailblazer/core/config.py` defines all options

## Development Conventions

### Working Agreements (Critical)

- **Main branch only** - commit atomically to main, no feature branches for routine work
- **Toolchain required** - always run `make fmt && make lint && make test` before committing
- **Artifacts immutable** - runs write to `var/runs/<run_id>/<phase>/`, never mutate previous runs
- **Postgres-only** - SQLite only allowed in tests with `TB_TESTING=1`

### Code Standards

- **Zero-errors policy:** IDE linter warnings must be eliminated
- **Type hints:** Use comprehensive type annotations (mypy strict mode)
- **Logging:** Use structured logging via structlog, NDJSON to stdout, pretty to stderr
- **Error handling:** Fail fast with clear error messages
- **Testing:** Use pytest with integration markers for database tests

### Environment Requirements

- **macOS virtualenv:** Commands must run in venv (enforced automatically)
- **PostgreSQL + pgvector:** Required for embedding/retrieval operations
- **Python 3.10+:** Minimum version requirement

## Database Operations

### Setup and Health

```bash
# Start database and verify health
make db.up && trailblazer db init && trailblazer db doctor

# Check connectivity and pgvector
trailblazer db check

# Verify embedding status
trailblazer embed status
```

### Backup Requirements (Critical)

```bash
# ALWAYS backup before destructive operations
scripts/backup_pg_embeddings.sh

# Check backup contents  
ls -la var/backups/$(date -u +%Y%m%dT*)/

# Emergency restore (manual process)
scripts/restore_pg_embeddings.sh var/backups/20250101T120000Z
```

## Operational Scripts

Key scripts for production operations:

- `scripts/reembed_corpus_openai.sh` - Plan + run orchestration for re-embedding
- `scripts/embed_dispatch.sh` - Multi-worker dispatcher for embedding jobs
- `scripts/monitor_embedding.sh` - Worker-aware progress monitoring with ETA
- `scripts/kill_embedding.sh` - Clean shutdown of embedding workers
- `scripts/backup_pg_embeddings.sh` - Database backup (required before destructive ops)

All scripts use `set -euo pipefail` and are zsh-safe.

## Debugging and Troubleshooting

### Common Issues

- **Database connection:** Check `TRAILBLAZER_DB_URL` and run `trailblazer db doctor`
- **Empty results:** Use `--allow-empty` flag or check source system connectivity
- **Token limits:** Embedding may hit token limits on large Confluence pages
- **Pager issues:** Export `PAGER=cat` and `LESS=-RFX` in scripts

### Observability

- **Progress tracking:** Real-time progress with heartbeats and ETAs
- **Event logs:** Structured NDJSON in `var/logs/<run_id>.ndjson`
- **Assurance reports:** Quality metrics in JSON and Markdown formats
- **Status commands:** `trailblazer status` for workspace overview

### Log Analysis

```bash
# View recent events
tail -f var/logs/latest.ndjson

# Check specific run logs
jq 'select(.level == "error")' var/logs/<run_id>.ndjson

# Monitor embedding progress
cat var/progress/embedding.json
```

## Testing Strategy

- **Unit tests:** Fast, isolated, mock external dependencies
- **Integration tests:** Marked with `@pytest.mark.integration`, use testcontainers
- **Database tests:** Automatic SQLite in test mode, PostgreSQL for integration
- **CLI tests:** Test command parsing and basic workflows
- **End-to-end:** Full pipeline tests with sample data

## Important Files

- `src/trailblazer/cli/main.py` - Main CLI entry point and command structure
- `src/trailblazer/core/config.py` - Configuration system and settings
- `prompts/000_shared_guardrails.md` - Non-negotiable development rules
- `docs/2025-08-18-0839_trailblazer-mindfile.md` - Latest architectural context
- `Makefile` - Standard development commands
- `pyproject.toml` - Project configuration and dependencies

## Security Notes

- **Secrets:** Store in `.env` only, never commit credentials
- **API tokens:** Use Confluence API tokens, not passwords
- **Database:** PostgreSQL with proper connection strings
- **Backups:** Critical for embedding data (expensive to regenerate)

Remember: This is a production system handling enterprise documentation. Always backup before destructive operations and follow the shared guardrails strictly.
