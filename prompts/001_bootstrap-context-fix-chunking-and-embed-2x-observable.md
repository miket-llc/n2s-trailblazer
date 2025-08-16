PROMPT FOR CLAUDE — Bootstrap & Resume: Context Seed → Safe Prompts → Fix Chunking → Full Embed (2×) with Live Monitoring

Execute now. Don't "plan." Paste the guardrails verbatim first, then perform the numbered steps and paste proofs (commands + outputs).
No assumptions: discover schema/flags/tables from the repo & DB at run‑time and use those exact values.
Safety: when normalizing prompts, archive only—never delete.

000 — Paste guardrails (verbatim, unchanged)

Open prompts/000_shared_guardrails.md.

Paste its full contents at the very top of your reply, unchanged. (Mandatory.)

Context (read once, then execute)

Trailblazer builds a bespoke knowledge base from Confluence and Oxygen/DITA; pipeline is Normalize → Enrich → Chunk → Embed into Postgres + pgvector for retrieval.

Embeddings: OpenAI text-embedding-3-small (1536 dims) for production.

Past incident: vectors were mistakenly stored as JSON; a new schema was created; vectors were converted and missing rows patched.

SQLite is removed. Postgres‑only in runtime; fail fast otherwise.

Golden Path & Config‑First: There's one primary orchestrator (e.g., trailblazer run) and a single config file (.trailblazer.yaml|yml|toml) that drives defaults. Keep flags minimal.

Current blocker: Embedding hit token limits—likely from Confluence pages with giant tables, code blocks, or macro bloat. DITA is usually fine; Confluence needs token‑budgeted, type‑aware chunking (code/table policies), plus junk filtration that keeps legit small pages.

Observability: Pretty status → stderr; typed NDJSON events → stdout; heartbeats, worker‑aware ETA, assurance reports, and sampling during long runs.

Prompts safety: Never delete non‑conforming prompts; archive only.

✅ To‑Do Checklist (≤9)

1. Restore & normalize prompts safely (archive‑only), then save this prompt
   set -euo pipefail
   git rev-parse --abbrev-ref HEAD | grep -qx "main"

# Restore if anything was deleted; then archive-only normalize (NO deletions)

git status
git restore prompts/ || true
TS="$(date +%Y%m%d\_%H%M%S)"; mkdir -p "var/archive/prompts/${TS}"
echo ">> DRY RUN non-conforming prompts:"
find prompts -maxdepth 1 -type f ! -regex '.*/[0-9]{3}\_.+.md$' -print || true
echo ">> ARCHIVING to var/archive/prompts/${TS}/"
find prompts -maxdepth 1 -type f ! -regex '.*/[0-9]{3}*.+.md$' -print0 | xargs -0 -I{} git mv "{}" "var/archive/prompts/${TS}/" || true
{ echo "# Prompts Index"; echo; ls -1 prompts | grep -E '^[0-9]{3}*.+.md$' | sort | awk '{printf("- %s\\n",$0)}'; } > prompts/README.md

# Save THIS prompt as next numbered file

NEXT_NUM=$(printf "%03d" $(( $(ls -1 prompts | grep -E '^[0-9]{3}_.+.md$' | sed 's/_.*//' | sort -n | tail -n1 | sed 's/^0*//') + 1 )))
FILE="prompts/${NEXT_NUM}\_bootstrap-context-fix-chunking-and-embed-2x-observable.md"
echo ">> TARGET PROMPT FILE: $FILE"

# (Use your editor automation to save this exact prompt content into $FILE)

git add -A
git commit -m "Normalize prompts (archive-only) and add ${FILE} (bootstrap, chunking fix, full embed 2x, observability)"

Paste the archived list and the $FILE path.

2. Golden Path & config‑first: discover the real orchestrator & config, don't invent flags
   export PAGER=cat; export LESS='-RFX'
   if command -v rg >/dev/null 2>&1; then RG="rg -n --hidden --no-ignore"; else RG="grep -RIn"; fi

# Discover CLI entrypoints and orchestrator

$RG -i 'console_scripts|entry_points|if __name__ == .__main__.' -g '!__/var/__' -g '!__/node_modules/__' || true
trailblazer --help || true
trailblazer run --help || true # If absent, discover the actual orchestrator name/command and show its help.

# Confirm config file present and print top section

ls -1 .trailblazer.\* || true
head -n 50 .trailblazer.yaml 2>/dev/null || head -n 50 .trailblazer.yml 2>/dev/null || head -n 50 .trailblazer.toml 2>/dev/null || true

Paste the help snippet and which config file you'll use.

3. Environment & DB preflight (Postgres‑only + pgvector) and schema discovery
   for v in TRAILBLAZER_DB_URL OPENAI_API_KEY EMBED_PROVIDER; do
   if [ -n "${!v:-}" ]; then echo "$v=SET"; else echo "$v=MISSING"; fi
   done
   trailblazer db doctor --no-color 2> >(tee /dev/stderr) 1> >(cat)

# Discover the actual vector columns and chunk tables; DO NOT GUESS names

docker exec -it $(docker ps | grep postgres | awk '{print $1}') env PAGER=cat psql -U postgres -P pager=off -d trailblazer -c "
SELECT 'pgvector_installed' AS check, COUNT(\*)>0 AS ok FROM pg_extension WHERE extname='vector';
WITH vec_cols AS (
SELECT n.nspname AS schema, c.relname AS table, a.attname AS column,
pg_catalog.format_type(a.atttypid, a.atttypmod) AS type
FROM pg_attribute a
JOIN pg_class c ON c.oid=a.attrelid
JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE a.attnum>0 AND NOT a.attisdropped
AND pg_catalog.format_type(a.atttypid, a.atttypmod) LIKE 'vector%'
)
SELECT schema, table, column, type FROM vec_cols ORDER BY schema, table, column;

SELECT table_schema, table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema NOT IN ('pg_catalog','information_schema')
AND table_name ILIKE '%chunk%'
ORDER BY 1,2,3;
"

Paste the discovered schema/table/column names you'll operate on.

4. Fix chunking before embedding: token‑budgeted + type‑aware (code/table/macro) + junk‑safe

Objective: eliminate token overages from Confluence pages with giant tables, code blocks, and macro bloat while keeping legit small content. DITA generally OK.

Implement (or enable if already present) in the chunker (in app code, not shell):

Token budgeting: per‑chunk tokenizer, target ~600–800 tokens with 50–100 overlap; never exceed provider hard max. Persist token_count in DB + NDJSON.

Type‑aware: detect code, table, macro/boilerplate; set chunk_type in DB.

Code: if large → embed a digest (language + short summary of top symbols) and persist the raw as attachment/sidecar; if small → embed as code.

Tables: create schema summary + N sampled rows (configurable); optionally windowed slices with header retained; never exceed budget.

Macros/boilerplate (nav, page props, excerpt include): skip or down‑weight; template placeholders skipped only when they match known fingerprints or empty‑after‑clean. Legit small pages stay.

Observability: emit chunk.plan, chunk.emit (chunk_id, type, token_count), chunk.skip (reason), chunk.digest (source, token_savings). Update var/status/\<run_id>.json with EMA EPS & ETA.

Prove it on a small Confluence slice (50–200 pages with tables/code): show chunk_type counts and token histograms, then commit.

If your chunker already has these knobs, switch them on from config and prove the results.

5. Reset the embed layer, re‑chunk full corpus, pre‑index vectors (fast retrieval)

# Stop/clear any stale workers

tmux ls || true
pkill -f "trailblazer.\*(embed|chunk|enrich|classif|compose|playbook|ask|retrieve|monitor)" || true

# Delete ALL embeddings (use the actual discovered embeddings table)

# (Adapt schema/table names from step 3 exactly.)

docker exec -it $(docker ps | grep postgres | awk '{print $1}') env PAGER=cat psql -U postgres -P pager=off -d trailblazer -c "DELETE FROM graphdb.chunk_embeddings;"

# OPTIONAL: If your policy is full rechunk → do it now via orchestrator (config-first)

trailblazer run --help || true

# Example (adapt to your actual orchestrator/flags)

# trailblazer run --phases normalize,enrich,chunk 2> >(tee /dev/stderr) 1> >(cat)

# Ensure HNSW/IVFFLAT index exists for the embeddings table; then ANALYZE

docker exec -it $(docker ps | grep postgres | awk '{print $1}') env PAGER=cat psql -U postgres -P pager=off -d trailblazer -c "
CREATE INDEX CONCURRENTLY IF NOT EXISTS chunk_embeddings_embedding_hnsw
ON graphdb.chunk_embeddings USING hnsw (embedding vector_cosine_ops);
ANALYZE graphdb.chunk_embeddings;
"

Paste the DELETE rowcount and index list after creation.

6. Launch TWO parallel embed instances (config‑first), workers ~3 each; rely on ON CONFLICT DO NOTHING
   export EMBED_PROVIDER=openai
   : "${OPENAI_API_KEY:?OPENAI_API_KEY must be set}"
   : "${TRAILBLAZER_DB_URL:?TRAILBLAZER_DB_URL must be set}"

# If needed, confirm your embed insert uses PK(chunk_id) + ON CONFLICT DO NOTHING. If missing, add it now and show the diff

# Start 2 sessions (minimal flags; use orchestrator phases if supported)

tmux new-session -d -s embedA "trailblazer run --phases embed --workers 3 --progress-every 500 --verbose 2> var/logs/embedA.stderr.log 1> var/logs/embedA.ndjson"
tmux new-session -d -s embedB "trailblazer run --phases embed --workers 3 --progress-every 500 --verbose 2> var/logs/embedB.stderr.log 1> var/logs/embedB.ndjson"
tmux ls

Paste the tmux list showing both sessions live.

7. Live monitoring every 30 minutes until coverage is 100% (no laziness)

For each check‑in, paste 5 things:

var/status/latest.json (EMA EPS, ETA, workers).

Tail both NDJSON logs (last 20 lines).

DB counters: total chunks, embedded, missing remaining:

docker exec -it $(docker ps | grep postgres | awk '{print $1}') env PAGER=cat psql -U postgres -P pager=off -d trailblazer -c "
WITH ch AS (SELECT COUNT(*) n FROM graphdb.chunks),
em AS (SELECT COUNT(*) n FROM graphdb.chunk_embeddings),
miss AS (SELECT COUNT(\*) n FROM graphdb.chunks c LEFT JOIN graphdb.chunk_embeddings e USING (chunk_id) WHERE e.chunk_id IS NULL)
SELECT (SELECT n FROM ch) AS chunks_total, (SELECT n FROM em) AS embeddings_total, (SELECT n FROM miss) AS chunks_missing_embeddings;
"

Two ask samples (top‑hit titles + scores) proving relevance.

Heartbeat summary: EPS(1m/5m), 429/backoff counters, ETA.

Do not stop until chunks_missing_embeddings = 0. If a session dies, restart and paste failure cause.

8. Final assurance: coverage=100%, dims uniform (=1536), no junk loss

# Coverage must be complete

docker exec -it $(docker ps | grep postgres | awk '{print $1}') env PAGER=cat psql -U postgres -P pager=off -d trailblazer -c "
WITH ch AS (SELECT COUNT(*) n FROM graphdb.chunks),
miss AS (SELECT COUNT(*) n FROM graphdb.chunks c LEFT JOIN graphdb.chunk_embeddings e USING (chunk_id) WHERE e.chunk_id IS NULL)
SELECT (SELECT n FROM ch) AS chunks_total, (SELECT n FROM miss) AS chunks_missing_embeddings;
"

# Vector dims/type — expect 1536 for text-embedding-3-small

docker exec -it $(docker ps | grep postgres | awk '{print $1}') env PAGER=cat psql -U postgres -P pager=off -d trailblazer -c "
SELECT vector_dims(embedding) AS dims, COUNT(\*) FROM graphdb.chunk_embeddings GROUP BY 1;
"

# Rebuild assurance and show failures (should be none for embed coverage/type)

trailblazer assure --all 2> >(tee /dev/stderr) 1> >(cat)

Paste: missing must be 0; dims=1536 only; show 20 lines from assurance.md demonstrating quality.

9. Proof‑of‑work (required)

Paste the exact commands you ran across steps 1–8 and the last ~10 lines of:

make fmt
make lint
make test

Include run_id banners from both embed sessions and a single‑line final summary:
DONE: chunks_total=…, embeddings_total=…, missing=0, dims=1536, elapsed=…
