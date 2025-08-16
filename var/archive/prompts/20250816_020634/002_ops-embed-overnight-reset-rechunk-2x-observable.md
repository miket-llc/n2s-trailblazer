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

______________________________________________________________________

# PROMPT FOR CLAUDE — Overnight Full Reset → Rechunk → Re‑Embed (Golden Path, Config‑First, 2 Parallel Instances, Live Observability)

Execute now. Do not draft or "plan". Paste the guardrails verbatim first, then perform each numbered step and paste proof‑of‑work (commands + outputs).
No assumptions: discover schema/flags/paths from the repo and DB at run time and use those exact values.
Safe prompts handling: archive‑only, never delete. If any prompts were deleted earlier, restore first.

000 — Paste guardrails (verbatim, unchanged)

Open prompts/000_shared_guardrails.md.

Paste its full contents at the very top of your reply, unchanged. (Mandatory.)

✅ To‑Do Checklist (≤9 items)

1. Restore prompts (if needed) & normalize safely (archive‑only)
   set -euo pipefail
   git rev-parse --abbrev-ref HEAD | grep -qx "main"

# If prompts were deleted but not committed

git status
git restore prompts/ || true

# If prompts deletions were committed

# (Find the commit; revert or restore from the parent commit)

git log --oneline -- prompts | head -n 5

# Example recovery (edit SHA as needed)

# git revert \<commit_sha_that_deleted_prompts> || git restore --source=\<parent_sha> -- prompts/

# git commit -m "Restore prompts/ after accidental deletion"

# SAFE normalize (archive-only). NO deletions

TS="$(date +%Y%m%d\_%H%M%S)"; mkdir -p "var/archive/prompts/${TS}"
echo ">> DRY RUN — non-conforming prompts:"
find prompts -maxdepth 1 -type f ! -regex '.*/[0-9]{3}\_.+.md$' -print || true
echo ">> ARCHIVING non-conforming prompts to var/archive/prompts/${TS}/"
find prompts -maxdepth 1 -type f ! -regex '.*/[0-9]{3}\_.+.md$' -print0 | xargs -0 -I{} git mv "{}" "var/archive/prompts/${TS}/" || true

{ echo "# Prompts Index"; echo; \
ls -1 prompts | grep -E '^[0-9]{3}\_.+.md$' | sort | awk '{printf("- %s\\n",$0)}'; } > prompts/README.md

git add -A
git commit -m "Normalize prompts safely: archive non-conforming to var/archive/prompts/${TS}; refresh index"

Paste the archived list + the last 5 lines of the commit output.

2. Save this prompt properly & update Non‑Negotiables (Golden Path & Config‑First)

# Compute next number and save THIS prompt

NEXT_NUM=$(printf "%03d" $(( $(ls -1 prompts | grep -E '^[0-9]{3}_.+.md$' | sed 's/_.*//' | sort -n | tail -n1 | sed 's/^0*//') + 1 )))
FILE="prompts/${NEXT_NUM}\_ops-embed-overnight-reset-rechunk-2x-observable.md"
echo ">> TARGET PROMPT FILE: $FILE"

# (Use your editor automation to save the *exact* prompt content you're running—incl. guardrails pasted above—into $FILE)

git add "$FILE"
git commit -m "Add ${FILE}: Overnight full reset→rechunk→re-embed (Golden Path, Config-first, 2x parallel, observable)"

# Append Golden Path & Config-First section to guardrails (idempotent)

awk '1; /^\_\_+$/ && !x { print "\\n## Golden Path & Config-First (Runtime, Non-Negotiable)\\n\\

- **Config-first**: The pipeline runs primarily from a single config file (`.trailblazer.{yaml|yml|toml}`) auto-loaded from CWD. Flags are minimal and only for rare overrides.\\n\\
- **One Golden Path**: A single orchestrator command (e.g., `trailblazer run`) drives phases in order (ingest→normalize→enrich→chunk→classify→embed→compose→playbook). No multi-tenant abstractions.\\n\\
- **Idempotence + Reset**: `run` must resume safely if re-executed and support a scoped `--reset` that reinitializes artifacts and/or DB facets as defined in config.\\n\\
- **Postgres-only**: No SQLite in runtime. Fail fast if pgvector or DB connectivity is missing.\\n\\
- **Observability built-in**: pretty to stderr, typed NDJSON to stdout, heartbeats, worker-aware ETA, per-phase assurance/quality gates, immutable artifacts in `var/`.\\n\\
- **Review-before-build**: Before adding flags or commands, *discover the existing code & config* and adapt to it—do not invent switches that don't exist.\\n"; x=1 }' \
  prompts/000_shared_guardrails.md > /tmp/guardrails.tmp && mv /tmp/guardrails.tmp prompts/000_shared_guardrails.md

git add prompts/000_shared_guardrails.md
git commit -m "Guardrails: add Golden Path & Config-First runtime non-negotiables"

Paste $FILE and show the diff hunk (or at least the new section heading) committed into 000_shared_guardrails.md.

3. Pre‑flight: env, DB doctor, schema discovery (no guesses)
   export PAGER=cat; export LESS='-RFX'
   for v in TRAILBLAZER_DB_URL OPENAI_API_KEY EMBED_PROVIDER; do
   if [ -n "${!v:-}" ]; then echo "$v=SET"; else echo "$v=MISSING"; fi
   done

# Discover CLI surface & the Golden Path command from the repo (don't assume names)

if command -v rg >/dev/null 2>&1; then RG="rg -n --hidden --no-ignore"; else RG="grep -RIn"; fi
$RG -i 'console_scripts|entry_points|if **name** == .**main**.' -g '!**/var/**' -g '!**/node_modules/**' || true
trailblazer --help || true
trailblazer run --help || true # if absent, discover the orchestrator name used in your code and use that

# DB doctor (must confirm Postgres + pgvector)

trailblazer db doctor --no-color 2> >(tee /dev/stderr) 1> >(cat)

# Schema discovery for embeddings & chunks (print actual tables/columns; no guesses)

docker exec -it $(docker ps | grep postgres | awk '{print $1}') env PAGER=cat psql -U postgres -P pager=off -d trailblazer -c "
SELECT 'pgvector_installed' AS check, COUNT(\*)>0 AS ok FROM pg_extension WHERE extname='vector';
WITH vec_cols AS (
SELECT n.nspname AS schema, c.relname AS table, a.attname AS column,
pg_catalog.format_type(a.atttypid, a.atttypmod) AS type
FROM pg_attribute a
JOIN pg_class c ON c.oid=a.attrelid
JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE a.attnum>0 AND NOT a.attisdropped AND pg_catalog.format_type(a.atttypid, a.atttypmod) LIKE 'vector%'
)
SELECT schema, table, column, type FROM vec_cols ORDER BY schema, table, column;
"

Paste CLI help snippets and the vector column discovery so we know the real schema/table/column to use.

4. Reset: delete all existing embeddings, then delete/rebuild chunks (full rechunk)

Important: This is a full reset by request. We'll drop embeddings first, then chunks (if your code expects a clean chunk pass). This must be config‑first; only use flags that actually exist.

# Kill any stale jobs before reset

tmux ls || true
pkill -f "trailblazer.\*(embed|chunk|enrich|classif|compose|playbook|ask|retrieve|monitor)" || true

# 4a) Delete embeddings (use actual table discovered above)

docker exec -it $(docker ps | grep postgres | awk '{print $1}') env PAGER=cat psql -U postgres -P pager=off -d trailblazer -c "DELETE FROM graphdb.chunk_embeddings;"

# 4b) Optional: delete chunks to force a fresh rechunk (confirm your real chunks table name first)

docker exec -it $(docker ps | grep postgres | awk '{print $1}') env PAGER=cat psql -U postgres -P pager=off -d trailblazer -c "DELETE FROM graphdb.chunks;"

# 4c) Rebuild chunks via Golden Path (config-first). If 'run' supports phased execution, use it

trailblazer run --help || true

# Example (ADAPT to your orchestrator flags): run phases normalize→enrich→chunk only

# trailblazer run --phases normalize,enrich,chunk 2> >(tee /dev/stderr) 1> >(cat)

Paste: row counts affected by the DELETEs and the command you actually used to recalc chunks (with its run_id banner).

5. Pre‑index: ensure HNSW/IVFFLAT index & ANALYZE (fast retrieval)

# Check existing indexes on the embeddings table

docker exec -it $(docker ps | grep postgres | awk '{print $1}') env PAGER=cat psql -U postgres -P pager=off -d trailblazer -c "
SELECT indexname, indexdef FROM pg_indexes WHERE schemaname='graphdb' AND tablename='chunk_embeddings';
"

# Create HNSW if missing (or IVFFLAT if your pgvector version requires it), then analyze

docker exec -it $(docker ps | grep postgres | awk '{print $1}') env PAGER=cat psql -U postgres -P pager=off -d trailblazer -c "
CREATE INDEX CONCURRENTLY IF NOT EXISTS chunk_embeddings_embedding_hnsw
ON graphdb.chunk_embeddings USING hnsw (embedding vector_cosine_ops);
ANALYZE graphdb.chunk_embeddings;
"

Paste the post‑create index list to confirm presence.

6. Launch TWO parallel embedding instances (config‑first) with safe rates

We will run two processes in parallel overnight. Keep workers modest per process to avoid org limits and rely on DB PK on chunk_id + "on conflict do nothing" semantics in your code to avoid duplicates. If your embed code doesn't use ON CONFLICT DO NOTHING, add it now and show the diff.

# Export minimal required env (no secrets to logs)

export EMBED_PROVIDER=openai
: "${OPENAI_API_KEY:?OPENAI_API_KEY must be set}"
: "${TRAILBLAZER_DB_URL:?TRAILBLAZER_DB_URL must be set}"

# Start two tmux sessions; each uses config-first defaults; minimal flags only if your CLI requires them

tmux new-session -d -s embedA "trailblazer run --phases embed --workers 3 --progress-every 500 --verbose 2> var/logs/embedA.stderr.log 1> var/logs/embedA.ndjson"
tmux new-session -d -s embedB "trailblazer run --phases embed --workers 3 --progress-every 500 --verbose 2> var/logs/embedB.stderr.log 1> var/logs/embedB.ndjson"

tmux ls

Paste the tmux session list so we see both are running. If your orchestrator doesn't support --phases, discover the actual flag and adapt.

7. Live observability & diligence (no laziness on long runs)

Every 30 minutes until completion, do all of the following and paste a short status in this chat (not just "still running"):

Status JSON (worker‑aware ETA) — show var/status/latest.json if your SDK writes one.

NDJSON tail — last 20 lines from both embed runs.

DB counters — counts of total chunks, embedded rows, missing remaining:

docker exec -it $(docker ps | grep postgres | awk '{print $1}') env PAGER=cat psql -U postgres -P pager=off -d trailblazer -c "
WITH ch AS (SELECT COUNT(*) n FROM graphdb.chunks),
em AS (SELECT COUNT(*) n FROM graphdb.chunk_embeddings),
miss AS (SELECT COUNT(\*) n FROM graphdb.chunks c LEFT JOIN graphdb.chunk_embeddings e USING (chunk_id) WHERE e.chunk_id IS NULL)
SELECT (SELECT n FROM ch) AS chunks_total, (SELECT n FROM em) AS embeddings_total, (SELECT n FROM miss) AS chunks_missing_embeddings;
"

Sampling — run two realistic ask queries and paste the top‑hit titles + scores (prove relevance), e.g.:

trailblazer ask "What is Banner student academic history?" --top-k 5 --max-chunks-per-doc 2 2> >(tee /dev/stderr) 1> >(head -n 50)
trailblazer ask "Where do I find Banner Student transcript pages?" --top-k 5 --max-chunks-per-doc 2 2> >(tee /dev/stderr) 1> >(head -n 50)

Heartbeat summary — show EPS (1m/5m), backoff/429 counters, ETA.

Do not stop reporting until chunks_missing_embeddings = 0. If a run crashes, restart it and note the failure cause from NDJSON.

8. Finalization: full PASS checks

When both runs complete:

# Coverage must be complete

docker exec -it $(docker ps | grep postgres | awk '{print $1}') env PAGER=cat psql -U postgres -P pager=off -d trailblazer -c "
WITH ch AS (SELECT COUNT(*) n FROM graphdb.chunks),
miss AS (SELECT COUNT(*) n FROM graphdb.chunks c LEFT JOIN graphdb.chunk_embeddings e USING (chunk_id) WHERE e.chunk_id IS NULL)
SELECT (SELECT n FROM ch) AS chunks_total, (SELECT n FROM miss) AS chunks_missing_embeddings;
"

# Vectors must be correct type & dims (discover; check vector_dims=1536 if using text-embedding-3-small)

docker exec -it $(docker ps | grep postgres | awk '{print $1}') env PAGER=cat psql -U postgres -P pager=off -d trailblazer -c "
SELECT vector_dims(embedding) AS dims, COUNT(\*) FROM graphdb.chunk_embeddings GROUP BY 1;
"

# Rebuild assurance reports and show failures (should be none for embed coverage/type)

trailblazer assure --all 2> >(tee /dev/stderr) 1> >(cat)

Paste the final counts (missing must be 0) and dims summary.

9. Proof‑of‑work (required)

Paste the exact commands you ran across steps 1–8 and the last ~10 lines of each:

make fmt
make lint
make test

Include the run_id banners from both embed processes and a one‑line final summary:
DONE: chunks_total=…, embeddings_total=…, missing=0, elapsed=…

Notes & guardrails (do not skip)

Golden Path & Config‑First: Before adding flags or inventing switches, discover the actual orchestrator and config and use it. This is not a generic tool.

Two instances safely: keep workers=3 each (adjust only if 429s/backoffs remain low). Rely on DB PK + conflict‑safe insert; if not present, add ON CONFLICT DO NOTHING in code now and show the diff.

No prompts deletion: use archive‑only normalize flow; never git rm in prompts/ without an explicit, opt‑in safety gate.

Live diligence: check in every 30 minutes with status JSON, NDJSON tails, DB counters, and sampling proof. No "mission accomplished" until missing=0 and assurance passes.
