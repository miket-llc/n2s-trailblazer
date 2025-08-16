PROMPT FOR CLAUDE — Processed‑Runs Backlog: Default = "All Normalized, Unprocessed" + Reset + Orchestrator Integration (Config‑First, Postgres‑Only)

Execute now. Don't "plan." Paste the guardrails verbatim first, then perform each numbered step and paste proofs (commands + outputs).
No assumptions: discover CLI names, schema names, and run IDs from the repo/DB at run time and use those exact values.
Golden Path & Config‑First; Zero complex scripts; Archive‑only for prompts.

000 — Paste guardrails (verbatim, unchanged)

Open prompts/000_shared_guardrails.md.

Paste its full content at the very top of your reply, unchanged. (Mandatory.)

📁 Prompts safety & numbering (archive‑only)

Save this prompt to prompts/NNN\_\*.md (three‑digit NNN), update prompts/README.md, and archive (do not delete) any non‑conforming prompts under var/archive/prompts/<ts>/.

✅ To‑Do Checklist (≤9 items)

1. Save this prompt & normalize prompts safely (ARCHIVE‑ONLY), then commit
   set -euo pipefail
   git rev-parse --abbrev-ref HEAD | grep -qx "main"

# Restore if anything was deleted accidentally

git restore prompts/ || true

# Archive-only normalization (NO deletions)

TS="$(date +%Y%m%d\_%H%M%S)"; mkdir -p "var/archive/prompts/${TS}"
echo ">> DRY RUN non-conforming prompts:"; find prompts -maxdepth 1 -type f ! -regex '.*/[0-9]{3}\_.+.md$' -print || true
echo ">> ARCHIVING:"; find prompts -maxdepth 1 -type f ! -regex '.*/[0-9]{3}\_.+.md$' -print0 | xargs -0 -I{} git mv "{}" "var/archive/prompts/${TS}/" || true

{ echo "# Prompts Index"; echo; ls -1 prompts | grep -E '^[0-9]{3}\_.+.md$' | sort | awk '{printf("- %s\\n",$0)}'; } > prompts/README.md

# Save THIS prompt under the next number

NEXT_NUM=$(printf "%03d" $(( $(ls -1 prompts | grep -E '^[0-9]{3}_.+.md$' | sed 's/_.*//' | sort -n | tail -n1 | sed 's/^0*//') + 1 )))
FILE="prompts/${NEXT_NUM}\_dev-processed-runs-backlog-default-all-unprocessed.md"
echo ">> TARGET PROMPT FILE: $FILE"

# (Use your editor automation to save this exact prompt content into $FILE)

git add -A
git commit -m "Normalize prompts (archive-only) and add ${FILE}: processed-runs backlog + default selection + reset"

Paste the archived list and $FILE path.

2. Discover the real orchestrator & config (Golden Path), and current "run_id" usage
   export PAGER=cat; export LESS='-RFX'
   if command -v rg >/dev/null 2>&1; then RG="rg -n --hidden --no-ignore"; else RG="grep -RIn"; fi

# CLI entrypoints & orchestrator names (no guessing)

$RG -i 'console_scripts|entry_points|if __name__ == .__main__.' -g '!__/var/__' -g '!__/node_modules/__' || true
trailblazer --help || true
trailblazer run --help || true # If absent, discover the actual orchestrator command and show its help.

# Where run_id is created/used today (E2E): normalize/enrich/chunk/embed/logs

$RG -i 'run_id|var/runs|assurance|ask.start|embed.start|chunk.start|normalize.start' -g '!__/var/__' || true

# Which config file exists

ls -1 .trailblazer.\* || true
head -n 40 .trailblazer.yaml 2>/dev/null || head -n 40 .trailblazer.yml 2>/dev/null || head -n 40 .trailblazer.toml 2>/dev/null || true

Paste the discovered orchestrator help and where run_id is handled.

3. Discover DB shape & add a Processed Runs Backlog table (idempotent migration)

We will not guess schema names. Discover and adapt.

# Doctor must confirm Postgres + pgvector

trailblazer db doctor --no-color 2> >(tee /dev/stderr) 1> >(cat)

# Search existing tables for 'run' markers (maybe 'runs', 'run_id', etc.)

docker exec -it $(docker ps | grep postgres | awk '{print $1}') env PAGER=cat psql -U postgres -P pager=off -d trailblazer -c "
SELECT table_schema, table_name, column_name
FROM information_schema.columns
WHERE table_schema NOT IN ('pg_catalog','information_schema')
AND (column_name ILIKE '%run_id%' OR table_name ILIKE '%run%')
ORDER BY 1,2,3;
"

# If no suitable backlog table exists, create one via your migration system

# Discover migration mechanism (Alembic/sql files); if missing, add idempotent SQL executed by the CLI

Implement migration (idempotent DDL; adapt schema names discovered above). Example (ADAPT names, do not paste blindly):

-- Example: graphdb.processed_runs (ADAPT schema)
CREATE TABLE IF NOT EXISTS graphdb.processed_runs (
run_id text PRIMARY KEY,
source text NOT NULL, -- e.g., 'confluence'|'dita' or 'mixed' if orchestrator-level
normalized_at timestamptz, -- set by normalize phase
chunk_started_at timestamptz,
chunk_completed_at timestamptz,
embed_started_at timestamptz,
embed_completed_at timestamptz,
status text NOT NULL DEFAULT 'normalized', -- normalized|chunking|chunked|embedding|embedded|failed|reset
total_docs integer,
total_chunks integer,
embedded_chunks integer,
claimed_by text, -- hostname/pid for concurrency
claimed_at timestamptz,
code_version text,
updated_at timestamptz NOT NULL DEFAULT now()
);

-- For default selections
CREATE INDEX IF NOT EXISTS ix_processed_runs_status ON graphdb.processed_runs (status);
CREATE INDEX IF NOT EXISTS ix_processed_runs_norm_at ON graphdb.processed_runs (normalized_at);

Backfill rows for any existing normalized runs by scanning the artifacts (e.g., var/runs/\*/normalize/…) and inserting run_id, source, normalized_at, and counts.

Observability: emit runs.backfill.start/tick/complete NDJSON.

Paste: the final CREATE INDEX / table list showing the table really exists.

4. Wire normalize → backlog (write row) and chunk/embed → claim from backlog

Normalize phase: on successful completion, UPSERT a row in processed_runs with run_id, source, normalized_at, status='normalized', and discovery counts (total_docs).

Chunk phase (default selection): if no explicit scope is provided, select all runs where status IN ('normalized','reset') and claim them one at a time with SELECT ... FOR UPDATE SKIP LOCKED → set status='chunking', claimed_by, claimed_at. When the run finishes chunking, set chunk_completed_at, status='chunked', total_chunks.

Embed phase (default selection): similarly, default to all runs where status IN ('chunked','reset') and claim them; set embed\_\* timestamps and finally status='embedded', embedded_chunks=total_chunks.

Concurrency safety: two or more processes can call claim simultaneously; use a short transaction to avoid double‑claim. Add a stale claim TTL (e.g., 30–60 min) to recycle abandoned claims.

Observability: emit runs.scan.start/complete (found=N), runs.claim (run_id, phase), runs.progress (% complete per run), runs.complete.

Implement now inside the orchestrator and the chunk/embed runners (config‑first, minimal flags). Then commit.

Paste: the diff summary (files touched) and show one real NDJSON runs.claim line.

5. Default behavior = process all normalized, unprocessed runs (e.g., 1700)

In the orchestrator, when user runs with no explicit scope, compute the backlog:

For chunk: WHERE status IN ('normalized','reset').

For embed: WHERE status IN ('chunked','reset').

Print a human readable banner to stderr with:
backlog_total, first/last normalized_at, and a few sample run_ids.

Add a config key (defaults enabled):
backlog: mode: default_all_unprocessed, claim_ttl_minutes: 45.

Paste: a captured stderr banner line from a dry run that shows e.g., backlog_total=1700.

6. Implement reset semantics that target the backlog markers (not data by default)

Add trailblazer runs reset (or an option in run) with scopes:

processed → only clear chunk\_*, embed\_*, and set status='reset' for selected runs (default = all).

embeddings → additionally delete embeddings for selected runs (confirm with --yes).

all → both of the above plus (if configured) delete chunks.

Selection supports filters (date range, source, run_id glob).

Emit NDJSON runs.reset.start/complete with counts.

Paste: the help snippet for reset and a dry‑run output showing how many runs would be reset (do not reset for real in this step).

7. Tests: selection, claim, idempotence, and reset

Unit tests for:

"default selection with empty scope" returns all normalized/unprocessed runs,

FOR UPDATE SKIP LOCKED claim is exclusive across 2 workers,

status transitions (normalized→chunking→chunked→embedding→embedded),

reset transitions (embedded→reset),

claim TTL recovers abandoned runs.

Integration smoke: seed 3 fake run_ids; run chunk+embed with 2 workers; assert final statuses embedded.

Paste: the last 10 lines of make test and one line per assertion you added.

8. Dry‑run: list the first N backlogged run_ids and then process a small subset

Run the orchestrator without explicit scope just to list the backlog count and the first 10 run_ids.

Then actually run chunk+embed for a small subset (e.g., limit 20) to prove claim/mark works end‑to‑end; show runs.claim and final statuses.

trailblazer run --help || true

# Example (ADAPT to your orchestrator flags)

# trailblazer run --phases chunk,embed --limit 20 --progress-every 200 2> >(tee /dev/stderr) 1> >(cat)

# Verify status distribution

docker exec -it $(docker ps | grep postgres | awk '{print $1}') env PAGER=cat psql -U postgres -P pager=off -d trailblazer -c "
SELECT status, COUNT(\*) FROM graphdb.processed_runs GROUP BY 1 ORDER BY 2 DESC;
"

Paste: backlog count, sample run_ids, and the status counts after the subset run.

9. Proof‑of‑work & Definition of Done (commit)

Paste the exact commands you ran in steps 1–8 and the last ~10 lines of:

make fmt
make lint
make test

Definition of Done:

A processed runs table exists and is filled for normalized runs (backfilled where needed).

Default behavior (no scope): process all normalized, unprocessed runs (e.g., all 1700).

Chunk and Embed phases claim from the backlog (concurrency‑safe) and mark completion; resets flip runs back to reset.

Golden Path & config‑first preserved; Postgres‑only, zero complex scripts; observability events present (runs.scan/claim/progress/complete, etc.).

Tests pass.

Final commit:

git add -A
git commit -m "Processed-runs backlog: default-all-unprocessed selection, claim/mark transitions, reset semantics, tests"
