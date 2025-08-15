# Shared Guardrails

PREAMBLE — Shared Guardrails (paste at the top of every prompt)
Save once as prompts/000_shared_guardrails.md and also paste at the top when
you run this prompt.

**Trailblazer Prompt Guardrails (read first)**

**Main only.** Do all work on main. No feature branches/PRs for routine work.

**Zero IDE linter errors across all file types.** If an IDE warns and our tools don't, update tool configs so the warning disappears permanently (don't hand-tweak files ad-hoc).

**Automate fixes first.** Always use the toolchain; never hand-fix format/lint.

```bash
make setup     # venv + dev deps + pre-commit
make fmt       # ruff --fix, black, mdformat for .md
make lint      # ruff check, mypy, markdownlint
make test      # pytest -q
```

**Markdown hygiene:** all .md must pass mdformat and markdownlint (e.g., fixes MD032 blanks-around-lists via formatter).

**Secrets hygiene:** placeholders only in repo/prompts; real values only in .env/CI. Secret scanning (e.g., gitleaks) is required in pre-commit.

**Pre-push gate:** tests must pass before pushing to main. Add/keep a pre-push pytest hook.

**Prompt size rule:** keep checklists to ≤9 to-dos (Cursor limit). Split into 004A/004B, etc., when needed.

**Proof-of-work:** in every prompt response, paste the exact commands run and the last ~10 lines of output for make fmt, make lint, and make test.

**Non-regression:** Never relax guardrails or remove stricter lint rules without explicit approval. Future prompts must start by pasting this file unchanged.

Confluence: Cloud v2 + Basic auth. Use v1 CQL only to prefilter when --since is set. Bodies/attachments fetched via v2.

Artifacts immutable: write to var/runs/run-id/phase/…; never mutate previous runs.

## Console UX Policy

Default to pretty, human-readable progress when attached to a TTY; default to JSON only in CI or when stdout is redirected.

Never intermix pretty output and JSON on the same stream. JSON → stdout; pretty/status/progress → stderr.

Always print the run_id at start/end of every command and write a final one-line summary.

Throttle progress updates; no more than 1 line per --progress-every N pages.

Keep the structured event names stable: confluence.space, confluence.page, confluence.attachments.

## Database Non-Negotiables (Global)

- Ingest is DB-free: importing or running any ingest CLI/step MUST NOT connect to, import, or initialize the DB.
- Postgres-first for runtime: Any command that persists or queries embeddings (e.g., `embed load`, `ask`, future retrieval services) MUST require Postgres + pgvector in non-test environments. SQLite is allowed ONLY for unit tests/CI and must be explicitly opted-in.
- Single source of truth: DB_URL MUST be provided in `.env` and used by a single engine factory. No hardcoded defaults that silently fall back to SQLite in dev/prod.
- Preflight required: `trailblazer db check` MUST pass (connectivity + pgvector present) before `embed load` or `ask` run (unless tests explicitly opt-in to SQLite).
- Secrets hygiene: Never print DB credentials in logs; log the host/database name only.

## DB policy

PostgreSQL + pgvector is the required default for any embed/retrieve/ask.

SQLite is tests-only (unit/integration) and must be explicit in tests.

Ingest/normalize must not require a DB.

No silent fallback to SQLite in runtime code paths. Fail fast with an actionable message if Postgres isn't configured.

Provide a single place to diagnose: trailblazer db doctor.

## Additional Global Rules

**Tests:** No merges to main with any failing tests. If tests fail, fix tests or the code; do not comment out or delete tests unless replaced by better coverage in the same PR.

**DB policy:** Ingest & normalize must not require a DB. Postgres/pgvector is only for retrieval/indexing phases; CLI preflights for DB must not gate ingest/normalize.

**Body format:** Confluence default body_format is atlas_doc_format (ADF). Storage/XHTML handling stays for backward compatibility and normalization.

**Traceability:** Always persist id, url, space_id/key/name (if available), version, created_at, updated_at, labels, ancestors/breadcrumbs, attachments (with filenames + download URLs), links, and content_sha256 throughout ingest → normalize.

**Observability:** All long-running CLIs must stream clean, structured progress (banners, per-phase counters, ETA) and print the run_id at completion.

**Cursor limit:** Keep prompts ≤10 to-dos; chunk work if needed.

**No regression:** Before edits, read the module and associated tests; prefer minimal deltas. If complexity is high, refactor in tiny steps with passing tests after each step.

## Non-Negotiable: Observability & Assurance

**Rich Console Progress:** All ingest commands MUST provide Rich-formatted progress with overall/per-space bars, heartbeats every 30s, and colored status indicators. Use `--no-color` to disable.

**Structured Event Logging:** Every ingest run MUST emit structured NDJSON events to `var/logs/<run_id>.ndjson` including: space.begin/end, page.fetch/write, attachment.fetch/write, heartbeat, warning, error with full traceability keys (source, space_key, space_id, page_id, title, version, url, attachment_id, sha256, bytes).

**Assurance Reports:** Every ingest MUST generate `assurance.json` and `assurance.md` with totals, per-space stats, zero-body pages, non-ADF bodies, missing/failed attachments, top 10 largest items, retry stats, error summaries, and reproduction command.

**Attachment Verification:** For every page with attachments, verify count written == count reported; retry with exponential backoff on mismatch; surface red counter in progress panel.

**Resumability Evidence:** When using `--since` or `--auto-since`, display what will happen: pages_known, estimated_to_fetch, skipped_unchanged counts with reasons (updated, deleted, moved).

**Zero Test Failures:** All observability features MUST have offline smoke tests that verify progress/heartbeat output, NDJSON event structure, and assurance report generation without network calls.

**No DB in Ingest:** Event logging and assurance generation MUST NOT require database connectivity - all observability is file-based under var/.

______________________________________________________________________

## Guardrails Addendum (OPS-EMBED-NEXT)

Database Policy (Global, Non-Negotiable): There is ONE runtime database: Postgres with pgvector. No SQLite anywhere in non-test code or ops. Do not add SQLite fallbacks or light/"developer" DB modes.

No pagers in terminal: Set PAGER=cat and LESS=-RFX in every session. If a tool supports pager-off flags (e.g., psql -P pager=off), use them. All command output must stream cleanly (no interactive pagers like less).

______________________________________________________________________

## Guardrails Addendum (OPS-EMBED-ALL-FINAL)

DB Policy: There is ONE runtime DB: Postgres + pgvector. No SQLite anywhere in runtime or ops.

No Pagers: Set PAGER=cat and LESS=-RFX in the session; pass pager-off flags if tools support them. All output must stream; do not invoke interactive pagers.

______________________________________________________________________

# PROMPT OPS-REEMBED-001 — Re-embed Entire Corpus with OpenAI (Serial, Observable)

**Save as:** prompts/OPS_REEMBED_001_openai.md\
**Branch:** main

## Guardrails Addendum

**One DB only:** Postgres + pgvector. No SQLite in runtime/ops.

**No pagers:** export PAGER=cat, export LESS=-RFX; if using psql, add -P pager=off.

**Enrichment gate:** do not embed a run unless var/runs/<RID>/enrich/{enriched.jsonl,fingerprints.jsonl} exist.

## Context for a New Instance

Ingest + normalize + enrichment are completed across all runs.

We previously embedded with dummy; now we will re-embed everything with a real provider (OpenAI, e.g., text-embedding-3-small), serial & observable, with assurance proofs.

Everything under var/; Postgres only.

## To-Dos (≤9)

### 1. Baseline & workspace

```bash
set -euo pipefail
export PAGER=cat
export LESS=-RFX
make setup
make fmt && make lint && make test && make check-md
trailblazer paths ensure && trailblazer paths doctor
```

### 2. Postgres + pgvector up

```bash
docker compose -f docker-compose.db.yml up -d
export DB_URL='postgresql+psycopg2://trailblazer:trailblazer@localhost:5432/trailblazer'
trailblazer db check && trailblazer db init
```

### 3. Set OpenAI provider & model

```bash
export OPENAI_API_KEY=***redacted***
export EMBED_PROVIDER=openai
export EMBED_MODEL=text-embedding-3-small     # great cost/quality; supports dimensions
export EMBED_DIMENSIONS=1024                  # try 512–1024 to save space
```

### 4. (Optional) purge dummy rows first (if schema uniqueness is only chunk_id)

(Skip if your schema is UNIQUE(chunk_id, provider). If not sure, run these DELETEs once with pager off.)

```bash
psql "$DB_URL" -P pager=off -c "DELETE FROM chunk_embeddings WHERE provider='dummy';"
```

### 5. Pilot re-embed (one recent Confluence run + latest DITA)

```bash
RID_C=$(ls -1t var/runs | grep '_full_adf$'  | head -n1 || true)
RID_D=$(ls -1t var/runs | grep '_dita_full$' | head -n1 || true)
for RID in $RID_C $RID_D; do
  echo "[PILOT] $RID model=$EMBED_MODEL dims=${EMBED_DIMENSIONS:-default}"
  trailblazer embed load \
    --run-id "$RID" \
    --provider openai \
    --model "$EMBED_MODEL" \
    ${EMBED_DIMENSIONS:+--dimensions $EMBED_DIMENSIONS} \
    --reembed-all \
    1> "var/logs/embed-$RID.jsonl" \
    2> "var/logs/embed-$RID.out"
done
```

### 6. Retrieval smoke on pilot

```bash
trailblazer ask "What is Navigate to SaaS?" \
  --top-k 8 --max-chunks-per-doc 3 --provider openai --format text \
  1> "var/logs/ask-openai-pilot.jsonl" \
  2> "var/logs/ask-openai-pilot.out"
tail -n 40 var/logs/ask-openai-pilot.out
```

If the context/hits obviously improve (they will vs dummy), proceed.

### 7. Re-embed ALL runs (serial, observable)

```bash
RUNS=$(ls -1 var/runs | grep -E '_full_adf$|_dita_full$' | sort) || true
for RID in $RUNS; do
  echo "[EMBED ALL] $RID model=$EMBED_MODEL dims=${EMBED_DIMENSIONS:-default}"
  trailblazer embed load \
    --run-id "$RID" \
    --provider openai \
    --model "$EMBED_MODEL" \
    ${EMBED_DIMENSIONS:+--dimensions $EMBED_DIMENSIONS} \
    --reembed-all \
    1> "var/logs/embed-$RID.jsonl" \
    2> "var/logs/embed-$RID.out"
done
```

### 8. Assurance proofs (one Confluence + DITA)

```bash
jq -C '{docs_total,docs_embedded,docs_skipped,chunks_total,chunks_embedded,chunks_skipped,provider,model,dim}' \
  "var/runs/$RID_C/embed_assurance.json" | sed -n '1,120p'
jq -C '{docs_total,docs_embedded,docs_skipped,chunks_total,chunks_embedded,chunks_skipped,provider,model,dim}' \
  "var/runs/$RID_D/embed_assurance.json" | sed -n '1,120p'
```

### 9. Proof-of-work to paste back

- Last 30 lines of one var/logs/embed-<RID>.out.
- The two embed_assurance.json summaries.
- Last 40 lines of var/logs/ask-openai-pilot.out.
- If you purged dummy first, paste the DELETE command you ran (no secrets).

## Notes & knobs

**Cost:** text-embedding-3-small is extremely cheap; you can pass --dimensions to trade a bit of recall for less storage and faster ANN.

**Storage sizing:** pgvector footprint ≈ dims × 4 bytes × chunks. 1024-dim ≈ ~4 KB/chunk; 1M chunks ≈ ~4 GB vectors.

**Throughput:** batch 128–256 usually saturates network without timeouts; handle 429s with backoff (loader should already do this).

**Incrementals later:** keep --changed-only for day-2 runs; use --reembed-all only when switching provider/model.
