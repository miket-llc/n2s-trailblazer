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

# Observable ingest with progress and sidecars
trailblazer ingest confluence --space DEV --progress --progress-every 5
# → writes CSV exports, summary.json, and seen page IDs

# Auto-since using state files (delta ingest)
trailblazer ingest confluence --space DEV --auto-since
# → reads state/confluence/DEV_state.json for last highwater mark

# Allow empty results (useful for automated scripts)
trailblazer ingest confluence --space DEV --since 2025-08-01T00:00:00Z --allow-empty
# → exits 0 even if no pages found (default: exits 4 on empty)

# List all spaces with structured output
trailblazer confluence spaces
# → displays table and writes runs/<run_id>/ingest/spaces.json
```

**Ingest exit codes:**

- `0` - Success (pages >= 1 processed)
- `2` - Configuration/authentication failure
- `3` - Remote API/network failure
- `4` - Empty result when `--allow-empty` not set

**Examples:**

```bash
# Fail if no pages found (default behavior)
trailblazer ingest confluence --space NONEXISTENT
# → exits 4

# Success even with no pages
trailblazer ingest confluence --space NONEXISTENT --allow-empty  
# → exits 0 with warning log
```

**Space Key Resolution:**

The ingest process automatically resolves `space_key` for each page using a three-tier strategy:

1. **Memoized cache**: Previously resolved space_id → space_key mappings
1. **API lookup**: GET `/wiki/api/v2/spaces/{id}` to fetch the space key
1. **URL fallback**: Regex extraction from page URL pattern `/spaces/([A-Z0-9]+)/pages/`

If all methods fail, `space_key` is set to `"__unknown__"` and tracked in `summary.json`. The ingest warns if any pages could not be mapped and includes `space_key_unknown_count` in metrics.

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

### 4. Ask (dense retrieval)

Query your embedded knowledge base using dense vector similarity:

```bash
# DB initialized and embeddings loaded from step 3
trailblazer ask "How do I configure SSO in Navigate to SaaS?" --top-k 8 --max-chunks-per-doc 3 --provider dummy
# artifacts → runs/<RUN_ID>/ask/

# More options
trailblazer ask "SAML configuration steps" \
  --provider dummy \
  --top-k 10 \
  --max-chunks-per-doc 2 \
  --max-chars 8000 \
  --format json \
  --out ./my-results/
```

**Ask CLI options:**

- `--top-k N` - Number of top chunks to retrieve (default: 8)
- `--max-chunks-per-doc N` - Max chunks per document (default: 3)
- `--provider NAME` - Embedding provider: `dummy` (default), `openai`, `sentencetransformers`
- `--max-chars N` - Max characters in packed context (default: 6000)
- `--format FORMAT` - Output format: `text` (default) or `json`
- `--out DIR` - Output directory (default: `runs/<run_id>/ask/`)
- `--db-url URL` - Database URL override

**Output artifacts:**

- `hits.jsonl` - One retrieval hit per line with scores and metadata
- `summary.json` - Query metadata, counts, timing, and score statistics
- `context.txt` - Packed context with separators, ready for LLM consumption

**Note:** Default provider is `dummy` for offline safety. Configure `EMBED_PROVIDER` and `DB_URL` for production use.

### 5. Observability & Operations

**Diff-deletions:** Track page deletions between runs:

```bash
# Compare two runs to find deleted pages
trailblazer ingest diff-deletions --space DEV \
  --baseline-run run-2025-01-01_1200_a1b2 \
  --current-run run-2025-01-15_1400_c3d4
# → writes deleted_ids.json to current run's ingest dir
```

**Prune old artifacts:** Clean up old run directories safely:

```bash
# Dry-run: show what would be deleted (default mode)
trailblazer ops prune-runs --keep 10 --min-age-days 30

# Actually delete old runs (protects newest N + referenced in state)
trailblazer ops prune-runs --keep 10 --min-age-days 30 --no-dry-run
# → writes prune_report.json to logs/ directory
```

**Observable artifacts from enhanced ingest:**

- `pages.csv` - Page metadata with sort-stable columns
- `attachments.csv` - All attachments with download URLs
- `summary.json` - Per-space statistics (pages, attachments, empty bodies, avg chars)
- `<SPACE>_seen_page_ids.json` - Page IDs seen this run (for diff-deletions)
- Structured logs: `confluence.space`, `confluence.page`, `confluence.attachments` events

### 6. Full pipeline

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
