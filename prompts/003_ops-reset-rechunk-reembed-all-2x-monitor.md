PROMPT FOR CLAUDE — OPS: Reset DB → Re‑Chunk → Re‑Embed ALL (~1,800), OpenAI‑only, 2× Parallel, Live Monitoring

Execute now. Do not draft a plan. Paste the guardrails first, then perform the numbered steps below and paste proof‑of‑work (commands + outputs).
Do not move/delete/archive any files in prompts/.
Config‑first Golden Path: discover and use the actual orchestrator and config; add flags only if required by the existing CLI.

✅ To‑Do Checklist (≤9)

1. Save THIS prompt (NO archiving) and show context you'll use
   set -euo pipefail
   git rev-parse --abbrev-ref HEAD | grep -qx "main"

# Save ONLY this prompt under the next number (do not touch other prompts)

NEXT_NUM=$(printf "%03d" $(( $(ls -1 prompts 2>/dev/null | grep -E '^[0-9]{3}_.+.md$' | sed 's/_.*//' | sort -n | tail -n1 | sed 's/^0*//' 2>/dev/null || echo 0) + 1 )))
FILE="prompts/${NEXT_NUM}\_ops-reset-rechunk-reembed-all-2x-monitor.md"
echo ">> TARGET PROMPT FILE: $FILE"

# (Use your editor automation to save THIS prompt content into $FILE)

git add "$FILE"; git commit -m "Add ${FILE}: reset → rechunk → re-embed ALL, OpenAI-only, 2x parallel, live monitoring"

# Show orchestrator & config (discover, don't guess)

if command -v rg >/dev/null 2>&1; then RG="rg -n --hidden --no-ignore"; else RG="grep -RIn"; fi
$RG -i 'console_scripts|entry_points|if __name__ == .__main__.' -g '!__/var/__' -g '!__/node_modules/__' || true
trailblazer --help || true
trailblazer run --help || true # If this fails, discover the actual orchestrator command and show its --help.

# Show which config file we'll use

ls -1 .trailblazer.\* 2>/dev/null || true
head -n 40 .trailblazer.yaml 2>/dev/null || head -n 40 .trailblazer.yml 2>/dev/null || head -n 40 .trailblazer.toml 2>/dev/null || true

Paste $FILE, the orchestrator help snippet, and which config you'll use.

2. Provider & environment safety (OpenAI only), macOS venv, DB preflight

# Streams / pagers

export PAGER=cat; export LESS='-RFX'

# Enforce OpenAI provider, forbid dummy

export EMBED_PROVIDER=openai
for v in TRAILBLAZER_DB_URL OPENAI_API_KEY EMBED_PROVIDER; do
if [ -n "${!v:-}" ]; then echo "$v=SET"; else echo "$v=MISSING"; fi
done
[ "${EMBED_PROVIDER}" = "openai" ] || (echo "EMBED_PROVIDER must be 'openai'."; exit 2)

# macOS venv enforcement (fail-fast unless explicitly bypassed by TB_ALLOW_SYSTEM_PYTHON=1)

python - \<<'PY'
import os, platform, sys
if platform.system() == 'Darwin' and not os.environ.get('TB_ALLOW_SYSTEM_PYTHON'):
in_venv = bool(os.environ.get('VIRTUAL_ENV')) or (getattr(sys, "base_prefix", "") != getattr(sys, "prefix", ""))
if not in_venv:
raise SystemExit("macOS: activate venv (e.g., `source .venv/bin/activate` or `make setup`) or set TB_ALLOW_SYSTEM_PYTHON=1 if CI.")
print("Venv check: OK")
PY

# DB doctor (Postgres + pgvector only)

trailblazer db doctor --no-color 2> >(tee /dev/stderr) 1> >(cat)

Paste the env check results and db doctor output (must show pgvector available).

3. Backlog discovery: insist on processing ALL normalized, unprocessed runs (~1,800)

Default behavior must be "all normalized but unprocessed." If a backlog table exists (e.g., graphdb.processed_runs), show counts; otherwise list normalized run_ids from artifacts. Use your actual schema—discover, don't guess.

# Try backlog table first

PSQL_DOCKER=$(docker ps --format '{{.ID}} {{.Image}}' 2>/dev/null | awk '/postgres/ {print $1; exit}')
if [ -n "${PSQL_DOCKER:-}" ]; then
docker exec -i "$PSQL_DOCKER" psql -U postgres -P pager=off -d trailblazer -c "
SELECT
SUM(CASE WHEN status IN ('normalized','reset') THEN 1 ELSE 0 END) AS backlog_for_chunk,
SUM(CASE WHEN status IN ('chunked','reset') THEN 1 ELSE 0 END) AS backlog_for_embed,
COUNT(*) AS total_rows
FROM graphdb.processed_runs;
" || true
else
psql "${TRAILBLAZER_DB_URL}" -v ON_ERROR_STOP=1 -c "
SELECT
SUM(CASE WHEN status IN ('normalized','reset') THEN 1 ELSE 0 END) AS backlog_for_chunk,
SUM(CASE WHEN status IN ('chunked','reset') THEN 1 ELSE 0 END) AS backlog_for_embed,
COUNT(*) AS total_rows
FROM graphdb.processed_runs;
" || true
fi

Paste the counts. If totals are \<< ~1,800, state what you found and continue—we still process ALL that remain.

4. Reset embedding layer and mark runs reset (no data loss beyond intended)

Delete embeddings and force full rechunk; reset backlog statuses. Use your real schema/table names—adapt if different.

# Kill any stale sessions

tmux ls || true
pkill -f "trailblazer.\*(embed|chunk|enrich|classif|compose|playbook|ask|retrieve|monitor)" || true

# Show pre-reset counts

if [ -n "${PSQL_DOCKER:-}" ]; then
docker exec -i "$PSQL_DOCKER" psql -U postgres -P pager=off -d trailblazer -c "
WITH ch AS (SELECT COUNT(*) n FROM graphdb.chunks),
em AS (SELECT COUNT(*) n FROM graphdb.chunk_embeddings)
SELECT (SELECT n FROM ch) AS chunks_total, (SELECT n FROM em) AS embeddings_total;
";
else
psql "${TRAILBLAZER_DB_URL}" -v ON_ERROR_STOP=1 -c "
WITH ch AS (SELECT COUNT(*) n FROM graphdb.chunks),
em AS (SELECT COUNT(*) n FROM graphdb.chunk_embeddings)
SELECT (SELECT n FROM ch) AS chunks_total, (SELECT n FROM em) AS embeddings_total;
";
fi

# Reset: delete embeddings, delete chunks, mark backlog reset

if [ -n "${PSQL_DOCKER:-}" ]; then
docker exec -i "$PSQL_DOCKER" psql -U postgres -P pager=off -d trailblazer -c "DELETE FROM graphdb.chunk_embeddings;";
docker exec -i "$PSQL_DOCKER" psql -U postgres -P pager=off -d trailblazer -c "DELETE FROM graphdb.chunks;";
docker exec -i "$PSQL_DOCKER" psql -U postgres -P pager=off -d trailblazer -c "
UPDATE graphdb.processed_runs
SET status='reset',
chunk_started_at=NULL, chunk_completed_at=NULL,
embed_started_at=NULL, embed_completed_at=NULL,
embedded_chunks=NULL, total_chunks=NULL,
updated_at=now();
" || true
else
psql "${TRAILBLAZER_DB_URL}" -v ON_ERROR_STOP=1 -c "DELETE FROM graphdb.chunk_embeddings;";
psql "${TRAILBLAZER_DB_URL}" -v ON_ERROR_STOP=1 -c "DELETE FROM graphdb.chunks;";
psql "${TRAILBLAZER_DB_URL}" -v ON_ERROR_STOP=1 -c "
UPDATE graphdb.processed_runs
SET status='reset',
chunk_started_at=NULL, chunk_completed_at=NULL,
embed_started_at=NULL, embed_completed_at=NULL,
embedded_chunks=NULL, total_chunks=NULL,
updated_at=now();
" || true
fi

# Recreate/ensure ANN index on embeddings

if [ -n "${PSQL_DOCKER:-}" ]; then
docker exec -i "$PSQL_DOCKER" psql -U postgres -P pager=off -d trailblazer -c "
CREATE INDEX CONCURRENTLY IF NOT EXISTS chunk_embeddings_embedding_hnsw
ON graphdb.chunk_embeddings USING hnsw (embedding vector_cosine_ops);
ANALYZE graphdb.chunk_embeddings;
";
else
psql "${TRAILBLAZER_DB_URL}" -v ON_ERROR_STOP=1 -c "
CREATE INDEX CONCURRENTLY IF NOT EXISTS chunk_embeddings_embedding_hnsw
ON graphdb.chunk_embeddings USING hnsw (embedding vector_cosine_ops);
ANALYZE graphdb.chunk_embeddings;
";
fi

Paste the before/after counts and index list.

5. Re‑chunk ALL (default selection = all normalized/reset) via Golden Path orchestration

Use the actual orchestrator (e.g., trailblazer run). Minimal flags; config‑first. If your run supports --phases, use it. Chunking generally doesn't need many workers; rely on your configured concurrency.

# Start chunking in its own tmux so we can monitor in other terminals

tmux new-session -d -s chunk "trailblazer run --phases chunk --progress-every 500 --verbose 2> var/logs/chunk.stderr.log 1> var/logs/chunk.ndjson"
tmux ls

Paste the tmux list showing chunk session running.

6. Embed ALL with two parallel instances (OpenAI provider, safe worker counts)

After chunking is underway (or completes), run two parallel embed sessions. Keep workers ≈ 3 per instance to avoid rate limits. OpenAI only.

export EMBED_PROVIDER=openai
: "${OPENAI_API_KEY:?OPENAI_API_KEY must be set}"
: "${TRAILBLAZER_DB_URL:?TRAILBLAZER_DB_URL must be set}"

tmux new-session -d -s embedA "trailblazer run --phases embed --workers 3 --progress-every 500 --verbose 2> var/logs/embedA.stderr.log 1> var/logs/embedA.ndjson"
tmux new-session -d -s embedB "trailblazer run --phases embed --workers 3 --progress-every 500 --verbose 2> var/logs/embedB.stderr.log 1> var/logs/embedB.ndjson"
tmux ls

Paste the tmux list showing both embedA and embedB live.

7. Real‑time monitoring from other terminals (no guessing; multiple options)

Open as many terminals as you like and run any/all of:

# Live status snapshot every 30s (ETA, workers, EPS) — if your SDK writes it

watch -n 30 'test -f var/status/latest.json && jq -C . var/status/latest.json | head -n 60'

# TUI/CLI monitor (if present)

trailblazer monitor --run latest 2> >(tee /dev/stderr) 1> >(head -n 80) || true

# Tail NDJSON logs for each session

tail -n 50 -f var/logs/chunk.ndjson
tail -n 50 -f var/logs/embedA.ndjson
tail -n 50 -f var/logs/embedB.ndjson

# Or tail stderr logs (human-readable)

tail -n 50 -f var/logs/chunk.stderr.log
tail -n 50 -f var/logs/embedA.stderr.log
tail -n 50 -f var/logs/embedB.stderr.log

# DB counters (watch remaining = 0)

watch -n 60 '
if docker ps | grep -q postgres; then
docker exec -i $(docker ps | awk "/postgres/{print $1; exit}") psql -U postgres -P pager=off -d trailblazer -c "
WITH ch AS (SELECT COUNT(*) n FROM graphdb.chunks),
em AS (SELECT COUNT(*) n FROM graphdb.chunk_embeddings),
miss AS (SELECT COUNT(*) n FROM graphdb.chunks c LEFT JOIN graphdb.chunk_embeddings e USING (chunk_id) WHERE e.chunk_id IS NULL)
SELECT (SELECT n FROM ch) AS chunks_total, (SELECT n FROM em) AS embeddings_total, (SELECT n FROM miss) AS chunks_missing_embeddings;
"
else
psql "${TRAILBLAZER_DB_URL}" -v ON_ERROR_STOP=1 -c "
WITH ch AS (SELECT COUNT(*) n FROM graphdb.chunks),
em AS (SELECT COUNT(*) n FROM graphdb.chunk_embeddings),
miss AS (SELECT COUNT(*) n FROM graphdb.chunks c LEFT JOIN graphdb.chunk_embeddings e USING (chunk_id) WHERE e.chunk_id IS NULL)
SELECT (SELECT n FROM ch) AS chunks_total, (SELECT n FROM em) AS embeddings_total, (SELECT n FROM miss) AS chunks_missing_embeddings;
"
fi'

8. Completion criteria & final checks (coverage=100%, dims=1536, provider=OpenAI)

# Coverage must be complete (missing = 0)

if [ -n "${PSQL_DOCKER:-}" ]; then
docker exec -i "$PSQL_DOCKER" psql -U postgres -P pager=off -d trailblazer -c "
WITH ch AS (SELECT COUNT(*) n FROM graphdb.chunks),
miss AS (SELECT COUNT(*) n FROM graphdb.chunks c LEFT JOIN graphdb.chunk_embeddings e USING (chunk_id) WHERE e.chunk_id IS NULL)
SELECT (SELECT n FROM ch) AS chunks_total, (SELECT n FROM miss) AS chunks_missing_embeddings;
";
else
psql "${TRAILBLAZER_DB_URL}" -v ON_ERROR_STOP=1 -c "
WITH ch AS (SELECT COUNT(*) n FROM graphdb.chunks),
miss AS (SELECT COUNT(*) n FROM graphdb.chunks c LEFT JOIN graphdb.chunk_embeddings e USING (chunk_id) WHERE e.chunk_id IS NULL)
SELECT (SELECT n FROM ch) AS chunks_total, (SELECT n FROM miss) AS chunks_missing_embeddings;
";
fi

# Vector dims/type (expect 1536 for text-embedding-3-small)

if [ -n "${PSQL_DOCKER:-}" ]; then
docker exec -i "$PSQL_DOCKER" psql -U postgres -P pager=off -d trailblazer -c "
SELECT vector_dims(embedding) AS dims, COUNT(*) FROM graphdb.chunk_embeddings GROUP BY 1;
";
else
psql "${TRAILBLAZER_DB_URL}" -v ON_ERROR_STOP=1 -c "
SELECT vector_dims(embedding) AS dims, COUNT(*) FROM graphdb.chunk_embeddings GROUP BY 1;
";
fi

# Quick recall smoke test (prove relevance)

trailblazer ask "What is Banner student academic history?" --top-k 5 --max-chunks-per-doc 2 2> >(tee /dev/stderr) 1> >(head -n 50)

Paste the coverage counts (missing must be 0), dims summary (must show 1536), and a snippet of the ask output.

9. Proof‑of‑work (required)

Paste the exact commands you ran across steps 1–8 and the last ~10 lines of:

make fmt
make lint
make test

Also paste the tmux session list at the end and a one‑line final summary:
DONE: processed ~<N> runs (target ~1800), chunks_total=…, embeddings_total=…, missing=0, dims=1536, provider=openai.
