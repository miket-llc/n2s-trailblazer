#!/usr/bin/env bash
set -euo pipefail
export PAGER=cat
export LESS=-RFX

PROGRESS="var/reembed_progress.json"
LOGDIR="var/logs"
INTERVAL="${INTERVAL:-15}"

[ -f "$PROGRESS" ] || { echo "[ERROR] $PROGRESS not found"; exit 2; }

echo "[MONITOR] watching $PROGRESS and $LOGDIR (interval ${INTERVAL}s)"
while true; do
  clear || true
  date -u +"%Y-%m-%dT%H:%M:%SZ"
  # summary
  jq -C '{
    started_at, total_runs, completed_runs, failed_runs,
    total_docs, total_chunks, estimated_cost
  }' "$PROGRESS" || true

  # show last 8 run statuses
  echo "---- recent runs ----"
  jq -r '.runs | to_entries
    | sort_by(.value.completed_at) | reverse
    | .[0:8][] | "\(.key)  \(.value.status)  docs=\(.value.docs_embedded) chunks=\(.value.chunks_embedded) dur=\(.value.duration_seconds)s err=\(.value.error)"' "$PROGRESS" || true

  echo "---- tail of active logs ----"
  # tail the newest 2 .out logs to give live feel (no pager)
  ls -1t "$LOGDIR"/embed-*.out 2>/dev/null | head -n 2 | xargs -r -I{} sh -c 'echo ">>> {}"; tail -n 30 {}; echo;'

  sleep "$INTERVAL"
done