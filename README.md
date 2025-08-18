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
- **Artifacts immutable** - runs write to `var/runs/<run_id>/<phase>/`, never mutate
  previous runs
- **Workspace paths** - use `trailblazer paths show` to see current workspace layout

📖 **See [mindfile](docs/2025-08-13-1358-trailblazer-mindfile.md) for
comprehensive architecture, contracts, and development guidelines.**

## Workspace Layout

Trailblazer uses a structured workspace layout with configurable paths:

```bash
# View current workspace paths
trailblazer paths show

# Ensure all workspace directories exist
trailblazer paths ensure
```

**Default directory structure:**

```
repo/
├── data/          # Human-managed inputs (data files, configs)
├── var/           # Tool-managed artifacts (gitignored)
│   ├── runs/      # All ingest/normalize run artifacts
│   ├── state/     # Persistent state (auto-since tracking)
│   ├── logs/      # All operation logs (JSON + pretty)
│   ├── cache/     # Temporary cached data
│   └── tmp/       # Temporary working files
├── src/           # Source code
├── tests/         # Test files
└── scripts/       # Helper scripts
```

**Configuration:**

- `TRAILBLAZER_DATA_DIR` - Base directory for human inputs (default: `data`)
- `TRAILBLAZER_WORKDIR` - Base directory for tool artifacts (default: `var`)

## Golden Path (Quick Start)

The most common workflow to get from Confluence to searchable knowledge base:

```bash
# 1. Preview what would be ingested (no writes)
trailblazer plan

# 2. Ingest everything (ADF enforced automatically)
trailblazer ingest-all --from-scratch --progress

# 3. Normalize all ingested data
trailblazer normalize-all

# 4. Check status and results
trailblazer status

# 5. Set up database (required for embedding and retrieval)
make db.up && trailblazer db init && trailblazer db doctor

# 6. Load embeddings (requires PostgreSQL + pgvector)
trailblazer embed corpus --provider openai --model text-embedding-3-small --dimensions 1536

# 7. Query your knowledge base
trailblazer ask "How do I configure SSO?" --provider openai
```

**Key Points:**

- **New Wrapper Commands**: `plan`, `ingest-all`, `normalize-all`, `status` handle common workflows
- **Ingest & Normalize**: Work without database - just file I/O
- **Database**: Only required for embedding and retrieval phases
- **ADF Enforced**: `atlas_doc_format` enforced automatically in wrapper commands
- **Workspace Validation**: All outputs strictly under `var/` - legacy paths blocked
- **Observability**: Rich progress, NDJSON event logs, assurance reports, and session tracking

## Simple Workflow

For a full clean-slate ingest of all Confluence spaces and DITA content:

```bash
# 1. Preview what would be ingested (dry-run, no writes)
trailblazer plan

# 2. Ingest everything from scratch with full observability
trailblazer ingest-all --from-scratch --progress

# 3. Normalize all ingested data to unified format
trailblazer normalize-all

# 4. Check workspace status and disk usage
trailblazer status
```

**Wrapper Command Benefits:**

- **Automatic workspace validation** (blocks legacy paths, enforces `var/` only)
- **ADF enforcement** for Confluence (no manual `--body-format` needed)
- **Progress forwarding** to underlying commands
- **Session tracking** with INDEX files
- **Error handling** with actionable troubleshooting guidance

For advanced options and individual space ingests, see [`scripts/examples.md`](scripts/examples.md) or use the underlying `trailblazer ingest confluence` and `trailblazer normalize from-ingest` commands directly.

## Enrichment

The enrichment phase processes normalized documents to add metadata, quality signals, and optional LLM-generated insights before embedding:

```bash
# Rule-based enrichment only (fast, deterministic)
trailblazer enrich <RUN_ID>

# Include LLM-based enrichment (summaries, keywords, suggested edges)
trailblazer enrich <RUN_ID> --llm

# Limit processing for testing
trailblazer enrich <RUN_ID> --max-docs 100 --budget "1000 tokens"
```

**Enrichment adds:**

- **Rule-based fields** (fast, deterministic): collections, path_tags, readability metrics, quality flags
- **LLM-optional fields** (when `--llm` enabled): summaries (≤300 chars), keywords (≤8), taxonomy labels, suggested document relationships
- **Quality flags**: empty_body, too_short, too_long, image_only, no_structure, broken_links
- **Enrichment fingerprints** for selective re-embedding (only re-embed when enrichment changes)

**Generated artifacts under `var/runs/<RUN_ID>/enrich/`:**

- `enriched.jsonl` - Enhanced document metadata with all computed fields
- `fingerprints.jsonl` - SHA256 fingerprints for selective re-embedding
- `suggested_edges.jsonl` - LLM-suggested document relationships (when `--llm` enabled)
- `assurance.json` + `assurance.md` - Quality reports and processing statistics

**When to run enrichment:**

Run enrichment after normalize and before embed. The embedding loader will automatically use enrichment fingerprints to determine which documents need re-embedding when enrichment metadata changes.

**DB-free guarantee:** Enrichment runs entirely on local files with no database dependencies.

## Embedding & Indexing

The embedding system converts normalized documents into vector embeddings for similarity search using PostgreSQL + pgvector:

```bash
# Check database connectivity and pgvector availability
trailblazer db check

# Initialize database schema (safe if tables exist)
trailblazer db init

# Load normalized documents with embeddings (idempotent)
trailblazer embed corpus --provider openai --model text-embedding-3-small --dimensions 1536

# Query the embedded knowledge base
trailblazer ask "How do I configure SSO?"
```

**Key Features:**

- **Idempotent loading** via content SHA256 hashing - skips unchanged documents
- **Media-aware chunking** with ![media: filename] placeholders for attachments
- **Pluggable providers**: dummy (deterministic), OpenAI, SentenceTransformers
- **Postgres-first**: Required for production, SQLite only for tests
- **Selective re-embed** with `--changed-only` (via enrichment fingerprints)
- **Assurance reports**: JSON + Markdown with statistics and error summaries

### Selective Re-embed with --changed-only (via enrichment fingerprints)

When you run enrichment multiple times and only want to re-embed documents whose enrichment metadata has changed:

```bash
# First embedding run - embeds all documents
trailblazer embed corpus --provider openai --model text-embedding-3-small --dimensions 1536

# Re-run enrichment with changes
trailblazer enrich <RUN_ID> --llm

# Second embedding run - only embeds documents with changed enrichment fingerprints
trailblazer embed corpus --provider openai --model text-embedding-3-small --dimensions 1536 --changed-only
```

**How it works:**

1. **Fingerprint tracking**: Enrichment generates `fingerprints.jsonl` with SHA256 hashes of enrichment metadata per document
1. **Change detection**: `--changed-only` compares current vs previous fingerprints (`fingerprints.prev.jsonl`)
1. **Selective processing**: Only documents with changed/new fingerprints are re-embedded
1. **Atomic updates**: After successful embedding, current fingerprints become the new previous fingerprints
1. **Observability**: Progress shows `changed=N unchanged=M` and assurance reports include both counts

**When to use:**

- After re-running enrichment with different LLM settings
- When enrichment rules or taxonomy change
- To incrementally update embeddings without full re-processing
- When embedding is expensive and most documents are unchanged

**Rich observability**: Progress bars, heartbeats, NDJSON event logs

**Database Schema:**

- `documents`: Metadata with content_sha256 for change detection
- `chunks`: Semantic text chunks with character/token counts
- `chunk_embeddings`: Vector storage per provider with UNIQUE constraints

**Environment Variables:**

- `TRAILBLAZER_DB_URL`: PostgreSQL connection string (required)
- `EMBED_PROVIDER`: Provider selection (openai|sentencetransformers)
- `OPENAI_API_KEY`: For OpenAI embeddings
- `OPENAI_EMBED_MODEL`: Model selection (default: text-embedding-3-small)

### Corpus Embedding

For embedding the entire corpus with comprehensive observability and batching support:

```bash
# Embed entire corpus with default settings
trailblazer embed corpus

# Customize provider and model
trailblazer embed corpus --provider openai --model text-embedding-3-small --dimensions 1536

# Resume from specific run
trailblazer embed corpus --resume-from 2025-08-15_080633_c4f3

# Limit runs to process
trailblazer embed corpus --max-runs 10

# Force re-embed all documents
trailblazer embed corpus --reembed-all

# Only embed changed documents
trailblazer embed corpus --changed-only
```

**Corpus Embedding Features:**

- **Automatic batching** for large runs (>2000 chunks by default)
- **Progress tracking** with real-time status updates
- **Resume capability** from any run ID
- **Cost estimation** with --dry-run-cost
- **Selective re-embedding** with --changed-only
- **Comprehensive logging** under var/logs/embedding/
- **Progress persistence** under var/progress/embedding.json

### Plan Preflight

Before dispatching embedding jobs, you can validate all runs in your plan file and get cost/time estimates:

```bash
# Basic plan preflight check
trailblazer embed plan-preflight --plan-file var/temp_runs_to_embed.txt

# With cost and time estimation
trailblazer embed plan-preflight \
  --plan-file var/temp_runs_to_embed.txt \
  --provider openai --model text-embedding-3-small --dimension 1536 \
  --price-per-1k 0.00002 --tps-per-worker 1000 --workers 2

# Custom output directory
trailblazer embed plan-preflight \
  --plan-file my_plan.txt \
  --out-dir var/custom_preflight/
```

**Plan Preflight Features:**

- **Batch validation**: Runs `trailblazer embed preflight` for each run in your plan file
- **Ready/blocked classification**: Identifies which runs are ready for embedding vs blocked
- **Failure reason detection**: Categorizes common failure modes (MISSING_ENRICH, MISSING_CHUNKS, QUALITY_GATE, etc.)
- **Cost estimation**: Optional pricing calculations if `--price-per-1k` provided
- **Time estimation**: Optional duration estimates if `--tps-per-worker` and `--workers` provided
- **Multiple output formats**: JSON, CSV, Markdown reports plus ready.txt and blocked.txt lists

**Plan File Format:**

The plan file should contain one run per line in `run_id:chunk_count` format:

```text
# Example plan file
2025-08-18_1234_confluence_full:1500
2025-08-18_5678_dita_docs:800
2025-08-18_9999_user_guides:200
```

**Generated Artifacts:**

Plan preflight creates a timestamped directory under `var/plan_preflight/` with:

- `plan_preflight.json` - Complete report with per-run details and aggregated totals
- `plan_preflight.csv` - Tabular format for spreadsheet analysis
- `plan_preflight.md` - Human-readable report with ready/blocked tables and fix guidance
- `ready.txt` - List of run IDs ready for embedding (use with dispatcher)
- `blocked.txt` - List of blocked run IDs with reasons
- `log.out` - Processing log with per-run status

**Plan-preflight → Dispatch Workflow:**

The recommended workflow integrates plan-preflight with existing dispatcher scripts:

```bash
# 1. Run plan-preflight with cost/time estimates
trailblazer embed plan-preflight \
  --plan-file var/temp_runs_to_embed.txt \
  --provider openai --model text-embedding-3-small --dimension 1536 \
  --price-per-1k 0.00002 --tps-per-worker 1000 --workers 2

# 2. Dispatch using only validated runs
scripts/embed_dispatch.sh --plan-file var/plan_preflight/<TS>/ready.txt
```

This ensures only runs that pass preflight validation are dispatched, avoiding surprises and providing accurate cost/time estimates. See the [Trailblazer mindfile](docs/2025-08-18-0839_trailblazer-mindfile.md) for the complete reset/dispatch/monitor flow and operator proofs.

**Common Failure Reasons & Fixes:**

- **MISSING_ENRICH** → run `trailblazer enrich run --run <RID>`
- **MISSING_CHUNKS** → run `trailblazer chunk run --run <RID>`
- **QUALITY_GATE** → re-run enrich with `--min-quality` lowered (carefully) or fix source docs
- **TOKENIZER_MISSING** → install/ensure tokenizer in ops venv
- **CONFIG_INVALID** → ensure provider/model/dimension set in env or flags

**Monitoring:**

```bash
# Check embedding progress
./scripts/monitoring/monitor_embedding.sh

# View progress file
cat var/progress/embedding.json
```

## Ask - Semantic Search & Retrieval

Query your embedded knowledge base using natural language:

```bash
# Basic question answering
trailblazer ask "How do I configure SSO?"

# Custom retrieval parameters
trailblazer ask "authentication setup" \
  --top-k 10 \
  --max-chunks-per-doc 2 \
  --provider openai \
  --max-chars 4000

# JSON output for programmatic use
trailblazer ask "user management" --format json

# Custom output directory
trailblazer ask "deployment guide" --out ./my-search/
```

**Key Features:**

- **Deterministic ranking**: Score DESC, then doc_id ASC, chunk_id ASC for ties
- **Context packing**: Respects code block boundaries, includes media placeholders
- **Rich artifacts**: `hits.jsonl`, `summary.json`, `context.txt` with full traceability
- **Observable**: NDJSON events to stdout, human progress to stderr
- **Media awareness**: First `![media: filename]` per document included in context

**Generated Artifacts:**

- `hits.jsonl`: One hit per line with chunk_id, doc_id, title, url, text_md, score
- `summary.json`: Query metadata, timing, statistics, score ranges
- `context.txt`: Packed context ready for LLM consumption

**Output Format:**

Text mode shows a brief summary and top results. JSON mode outputs the full summary object for integration with other tools.

## Running Retrieval QA

Test retrieval quality using curated domain queries with comprehensive health metrics:

```bash
# Run QA with default N2S domain queries
trailblazer qa retrieval \
  --queries-file prompts/qa/queries_n2s.yaml \
  --budgets 1500,4000,6000 \
  --provider openai --model text-embedding-3-small --dimension 1536

# Custom queries and thresholds
trailblazer qa retrieval \
  --queries-file my-custom-queries.yaml \
  --budgets 2000,5000 \
  --top-k 15 \
  --min-unique-docs 4 \
  --max-tie-rate 0.25 \
  --out-dir var/custom_qa/

# Skip traceability checks for testing
trailblazer qa retrieval --no-require-traceability
```

**Generated Artifacts (under `var/retrieval_qc/<timestamp>/`):**

- `ask_<slug>_<budget>.json` - Per-query results with hits, scores, and packed context
- `pack_stats.json` - Aggregate statistics across budgets (diversity, tie rates, coverage)
- `readiness.json` - Machine-readable health report with pass/fail status
- `overview.md` - Human-readable summary with READY/BLOCKED status and remediation tips

**Health Metrics:**

- **Doc Diversity**: Shannon entropy of document distribution (higher = more diverse)
- **Tie Rate**: Frequency of identical scores (lower = better ranking stability)
- **Duplication**: Repeated chunk/document pairs (lower = less redundancy)
- **Traceability**: Presence of title, URL, source_system metadata (required for production)

**Quality Gates (configurable):**

- Minimum unique documents per budget (default: 3)
- Maximum tie rate threshold (default: 35%)
- Required traceability fields (title, URL, source_system)
- Overall pass rate threshold (80% of queries must pass)

**Example Output:**

```
✅ QA completed: 15 queries
📊 Pass rate: 93.3%
📁 Results: var/retrieval_qc/20250120_143022/
```

The system is marked **READY** if ≥80% of queries pass all health checks, otherwise **BLOCKED** with specific remediation guidance.

## What You'll See

**Rich Progress Output:**

```
🚀 Starting ingest run: 2025-08-14_153540_be5f
   Spaces targeted: 5
   Mode: since 2025-08-01T00:00:00Z

💓 12:34:56 ingesting | processed: 150 | rate: 2.5/s | elapsed: 60s | API: 200 OK
ADN | p=380764162 | "Advancement Domain" | att=5 | 2020-06-25T23:14:26Z (2.5/s)

✅ Completed ingest run: 2025-08-14_153540_be5f
   Total: 188 pages, 505 attachments
   Rate: 2.8 pages/s

📋 Assurance Reports Generated:
  JSON: var/runs/2025-08-14_153540_be5f/ingest/assurance.json
  Markdown: var/runs/2025-08-14_153540_be5f/ingest/assurance.md
```

**Event Logging:** Structured NDJSON events in `var/logs/<run_id>.ndjson` for complete audit trails and debugging.

## Detailed Usage

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

# Body format options (ADF is default, Storage also supported)
trailblazer ingest confluence --space DEV --body-format atlas_doc_format  # ADF (default)
trailblazer ingest confluence --space DEV --body-format storage           # Legacy format
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

Converts Confluence bodies (ADF JSON + Storage XHTML) to clean Markdown. Uses ADF by default, falls back to Storage format:

```bash
# Normalize from a previous ingest run
trailblazer normalize from-ingest --run-id <RUN_ID>
# → outputs to runs/<RUN_ID>/normalize/normalized.ndjson
```

### 3. Database (Postgres required)

Trailblazer requires PostgreSQL + pgvector for production use. SQLite is only allowed for tests.

**Quick Setup with Docker:**

```bash
# Start PostgreSQL with pgvector (easiest option)
make db.up

# Wait for database to be ready
make db.wait

# Initialize database schema and verify health
trailblazer db init
trailblazer db doctor
```

**Manual PostgreSQL Setup:**

```bash
# Install PostgreSQL and pgvector extension
# Ubuntu/Debian:
sudo apt-get install postgresql postgresql-contrib
sudo -u postgres psql -c "CREATE EXTENSION vector;"

# macOS (with Homebrew):
brew install postgresql pgvector
createdb trailblazer
psql trailblazer -c "CREATE EXTENSION vector;"
```

**Configuration:**

Set `TRAILBLAZER_DB_URL` in your `.env` file:

```bash
# PostgreSQL (required for production)
TRAILBLAZER_DB_URL=postgresql+psycopg2://trailblazer:trailblazer_dev_password@localhost:5432/trailblazer

# SQLite is automatically enabled in test environment (TB_TESTING=1)
```

**Database Commands:**

```bash
# Comprehensive database health check (recommended)
trailblazer db doctor

# Basic connectivity check
trailblazer db check

# Initialize database schema (creates tables and pgvector extension if possible)
trailblazer db init

# Docker database management
make db.up    # Start PostgreSQL container
make db.down  # Stop PostgreSQL container
make db.wait  # Wait for database readiness
```

### 3.5. Backup & Daily Operations

**⚠️ CRITICAL: Always backup before destructive operations!**

```bash
# Create daily backup (REQUIRED before any destructive ops)
scripts/backup_pg_embeddings.sh

# Check backup contents
ls -la var/backups/$(date -u +%Y%m%dT*)/

# Emergency restore (documentation only - manual execution required)
scripts/restore_pg_embeddings.sh var/backups/20250101T120000Z
```

**Daily Operations Checklist:**

1. **Backup First** → `scripts/backup_pg_embeddings.sh`
1. **Status Check** → `trailblazer db doctor` / `trailblazer embed status`
1. **Monitor Workers** → `bash scripts/monitor_embedding.sh` (if embedding)
1. **Stop Workers** → `bash scripts/kill_embedding.sh` (if needed)

**Backup Contents:**

- `schema.sql` - Database schema (tables, indexes, extensions)
- `embeddings.dump` - Embeddings data in PostgreSQL custom format
- `manifest.json` - Backup metadata and restore instructions

**⚠️ IMPORTANT:**

- **Do not** run any destructive cleanup without a same-day backup
- Embeddings are expensive to regenerate - protect them!
- Use `trailblazer embed status` to monitor current counts
- Archive logs instead of deleting: `var/logs/_archive/`

### 4. Embed & Graph v0

Chunk normalized documents and generate embeddings for retrieval:

```bash
# Ensure PostgreSQL is ready first
make db.up && trailblazer db init && trailblazer db doctor

# Load documents with embeddings (requires PostgreSQL + pgvector)
trailblazer embed corpus --provider openai --model text-embedding-3-small --dimensions 1536

# Or load from custom file
trailblazer embed load --input normalized.ndjson --provider openai --model text-embedding-3-small --dimensions 1536
```

**Environment variables for embeddings:**

- `EMBED_PROVIDER` - Embedding provider: `openai` (default), `sentencetransformers`
- `OPENAI_API_KEY` - Required for OpenAI embeddings
- `SENTENCE_TRANSFORMER_MODEL` - Local model name for sentence-transformers

**Note:** PostgreSQL + pgvector is required for production. Commands like `embed load` and `ask` will fail fast if PostgreSQL is not configured (SQLite is only allowed for tests with TB_TESTING=1).

### 5. Ask (dense retrieval)

Query your embedded knowledge base using dense vector similarity:

```bash
# DB initialized and embeddings loaded from step 4
trailblazer ask "How do I configure SSO in Navigate to SaaS?" --top-k 8 --max-chunks-per-doc 3 --provider openai
# artifacts → runs/<RUN_ID>/ask/

# More options
trailblazer ask "SAML configuration steps" \
  --provider openai \
  --top-k 10 \
  --max-chunks-per-doc 2 \
  --max-chars 8000 \
  --format json \
  --out ./my-results/
```

**Ask CLI options:**

- `--top-k N` - Number of top chunks to retrieve (default: 8)
- `--max-chunks-per-doc N` - Max chunks per document (default: 3)
- `--provider NAME` - Embedding provider: `openai` (default), `sentencetransformers`
- `--max-chars N` - Max characters in packed context (default: 6000)
- `--format FORMAT` - Output format: `text` (default) or `json`
- `--out DIR` - Output directory (default: `runs/<run_id>/ask/`)
- `--db-url URL` - Database URL override

**Output artifacts:**

- `hits.jsonl` - One retrieval hit per line with scores and metadata
- `summary.json` - Query metadata, counts, timing, and score statistics
- `context.txt` - Packed context with separators, ready for LLM consumption

**Note:** Default provider is `openai` for production use. Configure `OPENAI_API_KEY` and `DB_URL` for production use.

### 5. Observability & Operations

**Console UX & Progress Tracking:**

Trailblazer automatically detects TTY vs CI/redirect environments and separates JSON logs from pretty output:

```bash
# Interactive TTY: pretty progress to stderr, JSON logs to stdout
trailblazer ingest confluence --space DEV --progress --progress-every 10

# CI/redirected: JSON-only mode automatically
trailblazer ingest confluence --space DEV > ingest.log 2> progress.log

# Force specific log format
trailblazer ingest confluence --space DEV --log-format json   # Always JSON
trailblazer ingest confluence --space DEV --log-format plain  # Always pretty

# Quiet mode for long runs (suppress banners, keep progress)
trailblazer ingest confluence --space DEV --progress --quiet-pretty
```

**Progress & Resume Features:**

```bash
# Progress checkpoints saved every N pages 
trailblazer ingest confluence --space DEV --progress --progress-every 50
# → writes progress.json with last page, counts, timestamps

# Auto-resume from checkpoints
trailblazer ingest confluence --space DEV --auto-since
# → shows "Resuming from page 12345" if previous progress.json exists

# Separate stdout/stderr for automation
trailblazer ingest confluence --space DEV 2>/dev/null  # Only run_id to stdout
trailblazer ingest confluence --space DEV 1>/dev/null  # Only progress to stderr
```

**Start/Finish Banners & Summaries:**

```
🚀 Starting ingest run: 2025-01-15_1400_c3d4
   Spaces targeted: 2
   Mode: auto-since
   Max pages: 1000

📋 Spaces to ingest:
   ID       | KEY      | NAME
   ---------|----------|----------------------------------
   12345678 | DEV      | Development Space
   87654321 | PROD     | Production Space

DEV | p=98765 | "Setting up SSO Configuration" | att=3 | 2025-01-15T14:25:30Z (12.5/s)
PROD | p=43210 | "User Management Guide" | att=1 | 2025-01-15T14:25:35Z (12.3/s)

✅ Completed ingest run: 2025-01-15_1400_c3d4
   Elapsed: 45.2s
   Total: 150 pages, 75 attachments
   Per space:
     DEV: 100 pages, 50 attachments
     PROD: 50 pages, 25 attachments
```

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

**Enhanced artifacts from observable ingest:**

- `pages.csv` - Page metadata with sort-stable columns
- `attachments.csv` - All attachments with download URLs
- `summary.json` - Per-space statistics with elapsed time and progress checkpoints
- `progress.json` - Rolling checkpoint file with last processed page and counts
- `final_summary.txt` - One-line human summary for reports
- `<SPACE>_seen_page_ids.json` - Page IDs seen this run (for diff-deletions)
- Structured logs: `confluence.space`, `confluence.page`, `confluence.attachments` events

### 6. Full pipeline

```bash
# Run multiple phases in sequence (includes embed phase)
trailblazer run --phases normalize embed --dry-run
```

## Traceability

Trailblazer preserves end-to-end traceability for all content, links, and attachments through structured artifacts.

### Ingest Artifacts

Each ingest run produces:

- **`confluence.ndjson`** - Complete canonical page records:

  ```json
  {
    "source_system": "confluence",
    "space_id": "111", "space_key": "DEV", "space_name": "Development", "space_type": "global",
    "id": "123456", "title": "Page Title",
    "url": "https://example.atlassian.net/wiki/spaces/DEV/pages/123456/Page-Title",
    "version": 1, "created_at": "2025-08-01T00:00:00Z", "updated_at": "2025-08-03T00:00:00Z",
    "created_by": {"account_id": "user123", "display_name": "John Doe"},
    "updated_by": {"account_id": "user456", "display_name": "Jane Smith"},
    "body_repr": "adf", "body_adf": {...}, "content_sha256": "abc123...",
    "labels": ["important", "api"], "ancestors": [{"id": "parent1", "title": "Parent"}],
    "attachments": [{"id": "att1", "filename": "doc.pdf", "sha256": "file123..."}],
    "attachment_count": 1, "label_count": 2, "ancestor_count": 1
  }
  ```

- **`links.jsonl`** - Link graph for reconstructing page relationships:

  ```json
  {
    "from_page_id": "123456",
    "from_url": "https://example.atlassian.net/wiki/spaces/DEV/pages/123456/Page-Title",
    "target_type": "confluence",
    "target_page_id": "789012",
    "target_url": "/spaces/PROD/pages/789012/Other-Page",
    "anchor": "section1",
    "rel": "links_to"
  }
  ```

- **`attachments_manifest.jsonl`** - Attachment references:

  ```json
  {
    "page_id": "123456",
    "filename": "document.pdf",
    "media_type": "application/pdf",
    "file_size": 1024,
    "download_url": "https://example.atlassian.net/download/attachments/123456/document.pdf"
  }
  ```

- **`ingest_media.jsonl`** - Position-aware media references:

  ```json
  {
    "page_id": "123456",
    "order": 0,
    "type": "image",
    "filename": "screenshot.png",
    "attachment_id": "att1",
    "download_url": "/download/attachments/123456/screenshot.png",
    "context": {"adf_path": "0", "alt": "Screenshot", "width": 400, "height": 300}
  }
  ```

- **`edges.jsonl`** - Hierarchy and label relationships:

  ```json
  {"type": "PARENT_OF", "src": "parent1", "dst": "123456"}
  {"type": "CONTAINS", "src": "space:DEV", "dst": "123456"}
  {"type": "LABELED_AS", "src": "123456", "dst": "label:important"}
  ```

- **`labels.jsonl`** - Page labels:

  ```json
  {"page_id": "123456", "label": "important"}
  ```

- **`breadcrumbs.jsonl`** - Navigation breadcrumbs:

  ```json
  {"page_id": "123456", "breadcrumbs": ["Development Space", "Parent Section", "Page Title"]}
  ```

- **`summary.json`** - Enhanced statistics with traceability counters:

  ```json
  {
    "links_total": 150, "links_internal": 120, "links_external": 25, "links_unresolved": 3,
    "media_refs_total": 75, "labels_total": 200, "ancestors_total": 180,
    "content_hash_collisions": 0, "attachment_refs": 2
  }
  ```

### Normalize Artifacts

The `normalized.ndjson` preserves all traceability fields plus processed content:

```json
{
  "id": "123456",
  "space_key": "DEV",
  "url": "https://example.atlassian.net/wiki/spaces/DEV/pages/123456/Page-Title",
  "source_system": "confluence",
  "links": ["https://external.com", "/spaces/PROD/pages/789012/Other"],
  "attachments": [{"filename": "doc.pdf", "url": "https://..."}],
  "text_md": "# Page Title\n\nMarkdown content..."
}
```

### Reconstructing Link Graphs

Extract page relationships:

```bash
# Find all pages linking to a specific page
jq -r 'select(.target_page_id == "123456") | .from_page_id' runs/*/ingest/links.jsonl

# Build adjacency list for internal links
jq -r 'select(.target_type == "confluence") | "\(.from_page_id) -> \(.target_page_id)"' runs/*/ingest/links.jsonl
```

### External References

Find external dependencies:

```bash
# List all external domains referenced
jq -r 'select(.target_type == "external") | .target_url' runs/*/ingest/links.jsonl | cut -d'/' -f3 | sort -u

# Count links by type
jq -r '.target_type' runs/*/ingest/links.jsonl | sort | uniq -c
```

### Media and Hierarchy Analysis

Analyze media usage and page hierarchy:

```bash
# Find pages with most media references
jq -r '.page_id' runs/*/ingest/ingest_media.jsonl | sort | uniq -c | sort -nr | head -10

# Build page hierarchy tree
jq -r 'select(.type == "PARENT_OF") | "\(.src) -> \(.dst)"' runs/*/ingest/edges.jsonl

# Find top-level pages (no parents)
comm -23 <(jq -r '.dst' runs/*/ingest/edges.jsonl | grep -v '^space:' | sort -u) \
         <(jq -r 'select(.type == "PARENT_OF") | .dst' runs/*/ingest/edges.jsonl | sort -u)

# Most commonly used labels
jq -r '.label' runs/*/ingest/labels.jsonl | sort | uniq -c | sort -nr | head -20
```

## Technical details

- **Pipeline:** ingest → normalize (ADF & Storage) → enrich/classify → embed →
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
