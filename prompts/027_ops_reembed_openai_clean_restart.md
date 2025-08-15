🧰 PROMPT: prompts/027_ops_reembed_openai_clean_restart.md
Preamble / Context (save this file verbatim in prompts/027_ops_reembed_openai_clean_restart.md):

Goal: kill any stray embedding jobs, re‑init DB (Postgres+pgvector), re‑embed the entire enriched corpus with OpenAI text-embedding-3-small (1536), and monitor progress end‑to‑end with accurate ETA. No pagers in terminal. Keep parallelism modest to avoid rate limits.

0. Update shared guardrails first
   Append to prompts/000_shared_guardrails.md under "Ops Non‑Negotiables":

One DB only: TRAILBLAZER_DB_URL must be PostgreSQL.

No pagers in scripts: Always export PAGER=cat and LESS=-RFX.

No regressions: If CLI flags changed, update scripts immediately.

Kill before run: Always kill old sessions before new embeds.

Commit:
docs(shared): ops guardrails — postgres-only, no pagers, kill-before-run

1. Kill any running jobs (idempotent)
   bash
   Copy
   export PAGER=cat; export LESS=-RFX
   bash scripts/kill_embedding.sh
   Expected:

Cleanly stops tmux session (if any) and any trailblazer embed load / reembed scripts.

2. DB sanity (Postgres + pgvector + tables + index)
   bash
   Copy

# Make sure .env has TRAILBLAZER_DB_URL=postgresql://

make db.up # if using local dockerized Postgres
trailblazer db init # creates tables, enables pgvector, creates vector index
trailblazer db doctor # must show pgvector: available
If doctor fails, stop and fix (no SQLite fallback in ops).

3. Environment for embeddings (OpenAI)
   bash
   Copy

# .env must contain

# OPENAI_API_KEY=

# TRAILBLAZER_DB_URL=postgresql://user:pass@host:5432/db

export EMBED_PROVIDER=openai
export EMBED_MODEL=text-embedding-3-small
export EMBED_DIMENSIONS=1536 # we stick with 1536
export OPENAI_EMBED_DIM=1536 # ensure provider sees 1536
export BATCH_SIZE=128 # safe default
export PAGER=cat; export LESS=-RFX
4\) Identify runs to embed (largest first) & prime progress
bash
Copy

# This script also initializes var/reembed_progress.json and

# fills var/temp_runs_to_embed.txt (largest runs first)

bash scripts/reembed_corpus_openai.sh --list-only
You should see: total runs, total docs, and a sorted runs file.

5. (If needed) wipe stale partial logs/progress only if you truly want a fresh start
   bash
   Copy
   rm -f var/reembed_progress.json var/reembed_errors.log var/reembed_cost.log

# Do NOT remove embeddings from DB unless you intentionally want a full purge

6. Re‑embedding: dispatch (modest parallelism) + monitor (ETA aware)
   Start dispatch in background tmux (so the monitor can tail):

bash
Copy
tmux new-session -d -s embed_workers \
"WORKERS=2 bash scripts/embed_dispatch.sh var/temp_runs_to_embed.txt"
Start the monitor (ETA accounts for active workers and recent throughput):

bash
Copy
INTERVAL=20 bash scripts/monitor_embedding.sh
What you should see:

Global totals: planned docs, embedded docs, chunks, elapsed time.

ETA that updates based on the last N minutes and current active_workers.

Recent runs with status and durations.

Tail of the most recent var/logs/embed-\*.out.

If you see "dimension mismatch" failures, stop here, decide whether to re‑embed all for that provider, and rerun with your chosen policy.

7. Resume / restart policy
   To resume after a crash: just re-run step 6; the script is idempotent.

To increase parallelism carefully:

bash
Copy
tmux kill-session -t embed_workers
tmux new-session -d -s embed_workers \
"WORKERS=3 bash scripts/embed_dispatch.sh var/temp_runs_to_embed.txt"
Watch the monitor—if you see rate‑limit retries or rising failures, drop back to 2.

8. Completion and summary
   When the monitor shows 100%:

Inspect var/reembed_progress.json for all status=completed.

Sum the cost log:

bash
Copy
awk -F, 'NR>1 {sum+=$5} END {printf "Total estimated cost: $%.2f\\n", sum}' var/reembed_cost.log
Sanity‑check DB:

bash
Copy
trailblazer ask "What is Navigate to SaaS?" --provider openai --top-k 5 --max-chunks-per-doc 3
9\) If anything fails
Use var/logs/embed-<RUN>.out to inspect the error tail.

If the error is dimensional mismatch for a provider: decide to re‑embed all for that provider or reconfigure to match.

If the error is DB‑related: rerun trailblazer db doctor and fix until it's green.

Commit this prompt as:

pgsql
Copy
ops(embeds): clean restart + monitor; postgres-only; no pagers; conservative parallelism
Why these are "must‑have" & minimal
Postgres‑only hardfail eliminates surprise SQLite fallbacks (I saw conditional JSON storage in db/engine.py; tests can keep it under TB_TESTING=1, but ops must never hit it).

Vector index creation is one function + one call in db init; it materially improves retrieval latency and is safe/no‑op if it already exists.

Dimensions sanity stops the worst class of "it ran, but all neighbors are garbage" issues.

Scripts alignment (no phantom CLI flags) prevents "unknown option" breaks that only show up after hours.

No pagers fixes unreadable terminals—your scripts already export PAGER/LESS; we keep that invariant.

If you want, I can also generate tiny follow‑ups for:

a trailblazer db optimize command that wraps ensure_vector_index() + ANALYZE, and

a --log-json flag to mirror human console output as NDJSON for machine pipelines.

But the two prompts above are sufficient to finish hardening the embed stage and run it cleanly now.
