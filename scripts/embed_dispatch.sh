#!/usr/bin/env bash
set -euo pipefail
export PAGER=cat
export LESS=-RFX

WORKERS="${WORKERS:-2}"           # start with 2; later 3–4 if stable
RUNS_FILE="${1:-var/temp_runs_to_embed.txt}"
[ -s "$RUNS_FILE" ] || { echo "[ERROR] $RUNS_FILE missing/empty"; exit 2; }

# Each job invokes reembed_corpus_openai.sh --single <run_id> <docs>
awk -F: '{print $1" "$2}' "$RUNS_FILE" \
| xargs -n 2 -P "$WORKERS" bash -lc '
  run_id="$0"; docs="${1:-0}";
  echo "[DISPATCH] $run_id ($docs docs)"
  EMBED_PROVIDER="${EMBED_PROVIDER:-openai}" \
  EMBED_MODEL="${EMBED_MODEL:-text-embedding-3-small}" \
  EMBED_DIMENSIONS="${EMBED_DIMENSIONS:-1536}" \
  BATCH_SIZE="${BATCH_SIZE:-128}" \
  bash scripts/reembed_corpus_openai.sh --single "$run_id" "$docs"
'
