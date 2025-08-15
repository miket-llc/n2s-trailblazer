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

## Embedding & DB Non-Negotiables

**PostgreSQL only in ops**: Runtime paths (embed, retrieval, ask) MUST connect to `postgresql://…`. SQLite is allowed ONLY in unit tests guarded by `TB_TESTING=1`. Use `make db.up` + `trailblazer db init` + `trailblazer db doctor` for setup.

**pgvector required**: `trailblazer db doctor` must show `pgvector: available`. If not, fail hard with a clear fixup message pointing to manual extension creation.

**Dimensions discipline**: The provider's configured dimension (e.g., `OPENAI_EMBED_DIM=1536`) MUST match what's persisted in the database. If mismatch detected, ABORT with a remediation hint (or require an explicit `--reembed-all`).

**No pagers**: All scripts/commands must export `PAGER=cat`, `LESS=-RFX` to prevent interactive pagers that break automation.

**No regressions**: Before merge, run `make fmt && make lint && make check-md && make test` and ensure ZERO failures/warnings in IDE.

______________________________________________________________________

## Ops Non-Negotiables

**One DB only**: TRAILBLAZER_DB_URL must be PostgreSQL. No SQLite fallbacks in operations.

**No pagers in scripts**: Always export `PAGER=cat` and `LESS=-RFX` to prevent interactive pagers in automation.

**No regressions**: If CLI flags changed, update scripts immediately to prevent unknown option errors.

**Kill before run**: Always kill old sessions before new embeds to prevent conflicts and resource contention.

# PROMPT FOR CLAUDE — Final Embedding, Full Corpus (vector schema fixed, no SQLite)

Immediately do the following. Do not summarize or "draft" a plan. Paste the guardrails, then execute the numbered tasks below, step by step, and paste proof‑of‑work.

000 — Paste guardrails (verbatim, unchanged)

Open prompts/000_shared_guardrails.md.

Paste its full contents at the very top of your reply, unchanged. (This is mandatory.)

📁 Prompts Directory Conventions (enforce now, before ops)

Naming: prompts/NNN_slug.md (three‑digit number).

Splits: use A, B suffixes only if needed.

Index: keep prompts/README.md in ascending order.

Non‑conforming prompts: delete them (preferred) or move to var/archive/prompts/<timestamp>/.

🤖 Model Selection

Use Claude for this task. Rationale: you already rolled back and cleaned up with Claude; we need continuity and strict execution (no "mission accomplished" without proof). If you cannot run commands, stop and state exactly which command failed.

✅ To‑Do Checklist (≤9)

1. Save this prompt under numbered conventions (then commit)
   set -euo pipefail
   TS="$(date +%Y%m%d\_%H%M%S)"
   mkdir -p var/archive/prompts/"$TS"

# Enforce naming; delete non‑conforming

find prompts -maxdepth 1 -type f ! -regex '.\*/[0-9]{3}\_.+.md$' -print -exec git rm -f {} ;

# Compute next number and filename

NEXT_NUM=$(printf "%03d" $(( $(ls -1 prompts | grep -E '^[0-9]{3}_.+.md$' | sed 's/_.*//' | sort -n | tail -n1 | sed 's/^0*//') + 1 )))
FILE="prompts/${NEXT_NUM}\_embed-final-full-corpus.md"

# Save this exact prompt content (including guardrails you pasted above) to the file

# (Use your editor automation; if not available, echo a clear confirmation that you've saved it.)

echo ">> SAVED PROMPT TO: $FILE"

# Update index

{ echo "# Prompts Index"; echo; \
ls -1 prompts | grep -E '^[0-9]{3}\_.+.md$' | sort | \
awk '{printf("- %s\\n",$0)}'; } > prompts/README.md

git add prompts/README.md "$FILE"
git commit -m "Add ${FILE} (final embed full corpus)"

Paste the filename created ($FILE). If save failed, fix and repeat.

2. Pre‑flight (main only, no pagers, no secrets; kill stale workers)
   git rev-parse --abbrev-ref HEAD | grep -qx "main"

export PAGER=cat; export LESS='-RFX'
for v in EMBED_PROVIDER OPENAI_API_KEY TRAILBLAZER_DB_URL; do
if [ -n "${!v:-}" ]; then echo "$v=SET"; else echo "$v=MISSING"; fi
done

tmux ls || true
pkill -f "trailblazer.\*embed" || true

Paste the command outputs. If any var is MISSING, stop, set it, and re‑run.

3. Hard stop for SQLite in runtime (no exceptions)

# Fail if any runtime path still references sqlite outside tests

# Adjust paths if your repo layout differs

( rg -n --hidden --line-number --no-ignore -i 'sqlite' \
--glob '!**/tests/**' \
--glob '!**/test/**' \
|| true ) | tee /dev/stderr

# If any matches printed above are in runtime code (not tests/CI scripts), ABORT and fix them

Confirm zero runtime SQLite references remain (tests are allowed only if they explicitly guard with TB_TESTING=1).

4. DB preflight — Postgres only + pgvector present + vector column (not JSON)
   trailblazer db doctor --no-color 2> >(tee /dev/stderr) 1> >(cat)
   trailblazer db check --no-color 2> >(tee /dev/stderr) 1> >(cat)

# Verify pgvector extension and column type for embeddings

docker exec -it $(docker ps | grep postgres | awk '{print $1}') \
env PAGER=cat psql -U postgres -P pager=off -d trailblazer -c "
SELECT extname FROM pg_extension WHERE extname='vector';
SELECT n.nspname, c.relname, a.attname, a.atttypid::regtype AS type
FROM pg_attribute a
JOIN pg_class c ON c.oid=a.attrelid
JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='graphdb' AND c.relname='chunk_embeddings' AND a.attname='embedding' AND a.attisdropped IS FALSE;
"

Expected: vector extension present; graphdb.chunk_embeddings.embedding type is vector, not json/jsonb. If not, stop and fix schema before proceeding.

5. Coverage & dimensions sanity (must end at 0 missing, 1536 dims)

# Totals & missing

docker exec -it $(docker ps | grep postgres | awk '{print $1}') env PAGER=cat psql -U postgres -P pager=off -d trailblazer -c "
WITH ch AS (SELECT COUNT(*) n FROM graphdb.chunks),
em AS (SELECT COUNT(*) n FROM graphdb.chunk_embeddings),
miss AS (
SELECT COUNT(\*) n
FROM graphdb.chunks c
LEFT JOIN graphdb.chunk_embeddings e USING (chunk_id)
WHERE e.chunk_id IS NULL
)
SELECT (SELECT n FROM ch) AS chunks_total,
(SELECT n FROM em) AS embeddings_total,
(SELECT n FROM miss) AS chunks_missing_embeddings;
"

# Provider/model/dims

docker exec -it $(docker ps | grep postgres | awk '{print $1}') env PAGER=cat psql -U postgres -P pager=off -d trailblazer -c "
SELECT provider, model, COUNT(*) n, MIN(created_at) first, MAX(created_at) last
FROM graphdb.chunk_embeddings GROUP BY 1,2 ORDER BY n DESC;
"
docker exec -it $(docker ps | grep postgres | awk '{print $1}') env PAGER=cat psql -U postgres -P pager=off -d trailblazer -c "
SELECT vector_dims(embedding) AS dims, COUNT(*) FROM graphdb.chunk_embeddings GROUP BY 1;
"

Target: dims=1536 only; provider=openai; model contains text-embedding-3-small. We will bring chunks_missing_embeddings → 0 in step 7.

6. Index health (ensure fast retrieval)
   docker exec -it $(docker ps | grep postgres | awk '{print $1}') env PAGER=cat psql -U postgres -P pager=off -d trailblazer -c "
   SELECT indexname, indexdef
   FROM pg_indexes
   WHERE schemaname='graphdb' AND tablename='chunk_embeddings';
   "

# Create HNSW if missing; ANALYZE for planner stats

docker exec -it $(docker ps | grep postgres | awk '{print $1}') env PAGER=cat psql -U postgres -P pager=off -d trailblazer -c "
CREATE INDEX CONCURRENTLY IF NOT EXISTS chunk_embeddings_embedding_hnsw
ON graphdb.chunk_embeddings USING hnsw (embedding vector_cosine_ops);
ANALYZE graphdb.chunk_embeddings;
"

Paste index list so we see the final state.

7. Execute final full‑corpus embedding (embed missing; skip existing)

# Enforce provider/model and rate safety

export EMBED_PROVIDER=openai
: "${OPENAI_API_KEY:?OPENAI_API_KEY must be set}"
: "${TRAILBLAZER_DB_URL:?TRAILBLAZER_DB_URL must be set}"

# Kill any stray workers; then run final embed NOW

pkill -f "trailblazer.\*embed" || true

# Run: this scans the entire corpus and embeds ONLY missing items; existing vectors are skipped

# Do NOT pass --reembed-all. We WANT to finish coverage without redoing good data

trailblazer embed \
--provider openai \
--model text-embedding-3-small \
--workers 4 \
--progress-every 500 \
--verbose \
2> >(tee /dev/stderr) 1> >(cat)

This step must run now. Do not declare success until step 8 shows 0 missing.

8. Post‑run verification (coverage=100%, dims consistent), smoke‑test retrieval

# Coverage must be 0 missing

docker exec -it $(docker ps | grep postgres | awk '{print $1}') env PAGER=cat psql -U postgres -P pager=off -d trailblazer -c "
WITH ch AS (SELECT COUNT(*) n FROM graphdb.chunks),
miss AS (
SELECT COUNT(*) n
FROM graphdb.chunks c
LEFT JOIN graphdb.chunk_embeddings e USING (chunk_id)
WHERE e.chunk_id IS NULL
)
SELECT (SELECT n FROM ch) AS chunks_total,
(SELECT n FROM miss) AS chunks_missing_embeddings;
"

# Confirm dims still uniform

docker exec -it $(docker ps | grep postgres | awk '{print $1}') env PAGER=cat psql -U postgres -P pager=off -d trailblazer -c "
SELECT vector_dims(embedding) AS dims, COUNT(\*) FROM graphdb.chunk_embeddings GROUP BY 1;
"

# Quick retrieval smoke tests (pretty→stderr, JSON→stdout)

trailblazer ask "What is Banner student academic history?" --provider openai --top-k 5 --max-chunks-per-doc 2 2> >(tee /dev/stderr) 1> >(cat)
trailblazer ask "Where do I find Banner Student transcript pages?" --provider openai --top-k 5 --max-chunks-per-doc 2 2> >(tee /dev/stderr) 1> >(cat)

Expected: chunks_missing_embeddings=0, dims=1536, and sensible ask results.

9. Proof‑of‑work: paste outputs & commit artifacts

Paste the exact commands you ran in steps 1–8.

Paste the last ~10 lines of each:

make fmt
make lint
make test

Print the run_id(s) from the embed step and a one‑line final summary with processed totals and elapsed time.

git add any updated scripts/log configurations; git commit -m "Finalize full-corpus embedding; coverage=100%".

Stop conditions / failure handling

If any preflight check fails (provider/env, Postgres connectivity, pgvector/column type not vector), STOP, print the failure, and fix before continuing.

If CLI flags differ, adapt and show the exact help output (trailblazer embed --help) before proceeding.

Do not claim completion until step 8 shows 0 missing embeddings and the smoke tests pass.
