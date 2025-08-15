# PROMPT OPS_REEMBED_OPENAI_002 — Patch Script → Pilot → Full Re-Embed with OpenAI (Serial, Observable)

# Shared Guardrails (VERBATIM - DO NOT MODIFY)
# Branching: No feature branches. Work directly on main.
# Linting: All code must pass make fmt && make lint && make test && make check-md
# Markdown hygiene: All .md files must pass make check-md
# Secrets: Never commit secrets. Use .env files and environment variables.
# Prompt size: Keep prompts focused and actionable.
# Proof-of-work: Always provide concrete evidence of completion.
# Console UX: Use clear, informative output with progress indicators.
# Database: Use Postgres + pgvector only. No SQLite in runtime/ops.

# Guardrails Addendum (append these lines to the shared guardrails before you begin)
# One DB only: Postgres + pgvector. NO SQLite anywhere in runtime/ops.
# No pagers: set PAGER=cat and LESS=-RFX in the session; pass pager-off flags in tools (psql -P pager=off). All output must stream; no interactive pagers.

# Context for a New Instance (read me first)
# Trailblazer pipeline is: ingest → normalize → enrich → (chunk inside) embed → retrieve.
# Ingest/normalize/enrich are DB-free and write under var/ only.
# We previously embedded with dummy vectors; now we will re-embed the corpus with OpenAI embeddings (e.g., text-embedding-3-small) serially and observably.
# We already have a script: scripts/reembed_corpus_openai.sh. We'll make two tiny fixes, enable an easy pilot, then run the full corpus.

# To-Dos (≤9)

# 1) Baseline (must be green) & workspace
# bash
# Copy
# Edit
# set -euo pipefail
# export PAGER=cat
# export LESS=-RFX
# 
# make setup
# make fmt && make lint && make test && make check-md
# trailblazer paths ensure && trailblazer paths doctor

# 2) Patch the script (two surgical fixes + small QoL)
# File: scripts/reembed_corpus_openai.sh
# 
# (a) Fix cost math — OpenAI current pricing:
# 
# text-embedding-3-small: $0.00002 / 1K tokens
# 
# text-embedding-3-large: $0.00013 / 1K tokens
# 
# Replace your estimate_run_cost() with:
# 
# bash
# Copy
# Edit
# estimate_run_cost() {
#   local run_id="$1"
#   # Total chars across all text_md in the run
#   local total_chars
#   total_chars=$(jq -r '.text_md' "var/runs/$run_id/normalize/normalized.ndjson" | wc -c | tr -d ' ')
#   # rough tokens ≈ chars/4
#   local tokens=$(( total_chars / 4 ))
# 
#   # pick price per 1k tokens by model (default small)
#   local price_per_1k="0.00002"
#   case "$EMBED_MODEL" in
#     *text-embedding-3-large*) price_per_1k="0.00013" ;;
#   esac
# 
#   # cost = tokens/1k * price_per_1k
#   echo "$(echo "scale=6; ($tokens / 1000) * $price_per_1k" | bc -l)"
# }
# 
# (b) Actually pass your batch size — add --batch "$BATCH_SIZE" inside embed_run():
# 
# bash
# Copy
# Edit
# trailblazer embed load \
#   --run-id "$run_id" \
#   --provider "$EMBED_PROVIDER" \
#   --model "$EMBED_MODEL" \
#   --dimensions "$EMBED_DIMENSIONS" \
#   --batch "$BATCH_SIZE" \
#   --reembed-all \
#   1> "$log_file" \
#   2> "$error_file"
# 
# (c) Map DB env once (if app expects DB_URL):
# 
# bash
# Copy
# Edit
# : "${TRAILBLAZER_DB_URL:?TRAILBLAZER_DB_URL is required}"
# export DB_URL="$TRAILBLAZER_DB_URL"
# 
# (d) (Optional, tiny QoL) Respect a prebuilt runs list for pilots:
# In get_runs_to_embed(), before scanning, short-circuit if var/temp_runs_to_embed.txt exists and is non-empty:
# 
# bash
# Copy
# Edit
# local runs_file="var/temp_runs_to_embed.txt"
# if [ -s "$runs_file" ]; then
#   echo "Using existing $runs_file"
#   # ensure sorted largest-first by the count column if present
#   sort -t: -k2 -nr "$runs_file" -o "$runs_file" || true
#   # update totals in progress file
#   local total_runs=$(wc -l < "$runs_file")
#   local total_docs=$(awk -F: '{sum += $2} END {print sum}' "$runs_file")
#   jq --argjson total_runs "$total_runs" --argjson total_docs "$total_docs" \
#      '.total_runs=$total_runs | .total_docs=$total_docs' \
#      "$PROGRESS_FILE" > "${PROGRESS_FILE}.tmp" && mv "${PROGRESS_FILE}.tmp" "$PROGRESS_FILE"
#   echo "$runs_file"
#   return 0
# fi
# 
# Keep everything else as-is (progress JSON, error/cost logs, interrupt trap, etc.).

# 3) Postgres + pgvector ONLY (no pagers)
# bash
# Copy
# Edit
# docker compose -f docker-compose.db.yml up -d
# export DB_URL="${DB_URL:-postgresql+psycopg2://trailblazer:trailblazer@localhost:5432/trailblazer}"
# trailblazer db check && trailblazer db init

# 4) Configure OpenAI provider & model (env)
# bash
# Copy
# Edit
# : "${OPENAI_API_KEY:?OPENAI_API_KEY is required}"
# export EMBED_PROVIDER=openai
# export EMBED_MODEL=text-embedding-3-small
# export EMBED_DIMENSIONS=1024     # 512–1024 good balance; dims don't change API cost
# export BATCH_SIZE=128

# 5) Pilot (2 runs) — build a small runs file and launch
# bash
# Copy
# Edit
# # Build a largest-first candidate list from enriched runs
# ls -1t var/runs | grep -E '_full_adf$|_dita_full$' | while read -r rid; do
#   if [ -f "var/runs/$rid/enrich/enriched.jsonl" ]; then
#     echo "$rid:$(wc -l < var/runs/$rid/enrich/enriched.jsonl)"
#     done | sort -t: -k2 -nr > var/temp_runs_to_embed.txt
# 
# # Keep only top 2 for the pilot
# sed -n '1,2p' var/temp_runs_to_embed.txt > var/temp_runs_to_embed.txt.tmp && mv var/temp_runs_to_embed.txt.tmp var/temp_runs_to_embed.txt
# 
# # Run the script (pilot)
# bash scripts/reembed_corpus_openai.sh

# 6) Pilot QA — assurance & retrieval
# bash
# Copy
# Edit
# # pick recent runs used in pilot
# head -n 2 var/temp_runs_to_embed.txt
# 
# # assurance (expect non-zero chunks_embedded)
# RID_C=$(ls -1t var/runs | grep '_full_adf$'  | head -n1 || true)
# RID_D=$(ls -1t var/runs | grep '_dita_full$' | head -n1 || true)
# jq -C '{docs_total,docs_embedded,docs_skipped,chunks_total,chunks_embedded,chunks_skipped,provider,model,dim}' var/runs/$RID_C/embed_assurance.json | sed -n '1,120p'
# jq -C '{docs_total,docs_embedded,docs_skipped,chunks_total,chunks_embedde,chunks_skipped,provider,model,dim}' var/runs/$RID_D/embed_assurance.json | sed -n '1,120p'
# 
# # retrieval smoke (expect obviously better results than dummy)
# trailblazer ask "What is Navigate to SaaS?" \
#   --top-k 8 --max-chunks-per-doc 3 --provider openai --format text \
#   1> var/logs/ask-openai-pilot.jsonl \
#   2> var/logs/ask-openai-pilot.out
# tail -n 40 var/logs/ask-openai-pilot.out
# 
# If OK: proceed to full corpus. If not OK: STOP, fix, rerun pilot.

# 7) Full re-embed (serial, observable)
# bash
# Copy
# Edit
# # remove pilot limiter so script scans all runs
# rm -f var/temp_runs_to_embed.txt
# 
# # run full re-embed (resumable, idempotent)
# bash scripts/reembed_corpus_openai.sh

# 8) Proof-of-work (paste back)
# Last 30 lines of one var/logs/embed-<RID>.out from the pilot and one from the full run.
# 
# The assurance JSON summaries for one Confluence and one DITA run (docs_*, chunks_*, provider, model, dim).
# 
# Last 40 lines of var/logs/ask-openai-pilot.out.
# 
# The total estimated cost line from your script's final summary.

# Notes
# Cost: text-embedding-3-small ≈ $0.02 per 1M tokens. Even tens of millions of tokens cost only a few dollars; dimensions don't change API cost.
# 
# Storage sizing: vectors ≈ dims × 4 bytes × chunks. 1024-dim ≈ ~4KB per chunk.
# 
# Incrementals later: re-use the script as-is; just point it at the new runs and keep --reembed-all only when switching model/dims.
