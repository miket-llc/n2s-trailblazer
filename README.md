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

- **Main branch only** - commit atomically to main, no feature branches for
  routine work
- **Toolchain required** - always run `make fmt && make lint && make test`
  before committing
- **Artifacts immutable** - runs write to `runs/<run_id>/<phase>/`, never mutate
  previous runs

📖 **See [mindfile](docs/2025-08-13-1358-trailblazer-mindfile.md) for
comprehensive architecture, contracts, and development guidelines.**

## Usage

### 1. Ingest from Confluence

Create `.env` from `configs/dev.env.example` and set:

- `CONFLUENCE_EMAIL`, `CONFLUENCE_API_TOKEN`
- `CONFLUENCE_BASE_URL` (defaults to `https://ellucian.atlassian.net/wiki`)

```bash
# Small test ingest
trailblazer ingest confluence --space DEV --since 2025-08-01T00:00:00Z \
  --max-pages 10
# → outputs to runs/<run_id>/ingest/
```

### 2. Normalize to Markdown

Converts Confluence bodies (Storage XHTML + ADF JSON) to clean Markdown:

```bash
# Normalize from a previous ingest run
trailblazer normalize from-ingest --run-id <RUN_ID>
# → outputs to runs/<RUN_ID>/normalize/normalized.ndjson
```

### 3. Embed & Graph v0

Chunk normalized documents and generate embeddings for retrieval:

```bash
# Initialize database schema
trailblazer db init

# Load documents with embeddings (default: dummy provider, offline)
trailblazer embed load --run-id <RUN_ID> --provider dummy --batch 128

# Or load from custom file
trailblazer embed load --input normalized.ndjson --provider dummy
```

**Environment variables for embed & graph:**

- `DB_URL` - Database URL (default: `sqlite:///./.trailblazer.db`)
- `EMBED_PROVIDER` - Embedding provider: `dummy` (default, offline), `openai`, `sentencetransformers`
- `OPENAI_API_KEY` - Required for OpenAI embeddings
- `SENTENCE_TRANSFORMER_MODEL` - Local model name for sentence-transformers

**Note:** Tests and default provider are offline. PostgreSQL + pgvector recommended for real retrieval scale.

### 4. Full pipeline

```bash
# Run multiple phases in sequence (includes embed phase)
trailblazer run --phases normalize embed --dry-run
```

## Technical details

- **Pipeline:** ingest → normalize (Storage & ADF) → enrich/classify → embed →
  retrieve → compose/create → audit
- **API:** Confluence Cloud v2 (`/wiki/api/v2`) with Basic auth; v1 CQL for
  delta filtering
- **Data:** NDJSON artifacts with deterministic transforms; PostgreSQL +
  pgvector for embeddings/retrieval
- **Auth:** Store `CONFLUENCE_EMAIL` + `CONFLUENCE_API_TOKEN` in local `.env`
  only

## Contributing & Non-Regression

- **Main-only workflow:** No feature branches for routine work; commit atomically to main
- **Make commands:** Always use `make setup`, `make fmt`, `make lint`, `make test`, `make check-md`
- **Markdown hygiene:** All `.md` files must pass `mdformat` and `markdownlint` (enforced in pre-commit)
- **Secrets policy:** Placeholders only in repo; real values in `.env`/CI secrets only
- **Zero-errors policy:** IDE linter warnings must be eliminated via tool configs, not per-file waivers
- **Do not weaken Shared Guardrails:** Never relax lint rules or remove stricter configs without explicit approval

📖 **Latest comprehensive guidelines:** [mindfile](docs/2025-08-13-1358-trailblazer-mindfile.md)
