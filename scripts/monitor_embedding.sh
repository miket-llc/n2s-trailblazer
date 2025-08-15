#!/usr/bin/env bash
set -euo pipefail
export PAGER=cat
export LESS=-RFX

PROGRESS="var/logs/reembed_progress.json"
RUNS_FILE="var/logs/temp_runs_to_embed.txt"   # may or may not exist
LOGDIR="var/logs"
INTERVAL="${INTERVAL:-15}"

# Small helper: ISO8601 → epoch (portable: prefer python if `date -d` fails)
iso_to_epoch() {
  local iso="$1"
  python3 - <<PY 2>/dev/null || date -u -j -f "%Y-%m-%dT%H:%M:%SZ" "$iso" "+%s" 2>/dev/null || date -u -d "$iso" "+%s"
import sys, datetime
s = sys.argv[1]
dt = datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
print(int(dt.replace(tzinfo=datetime.timezone.utc).timestamp()))
PY
}

# EWMA to smooth doc rate
ewma() {
  # args: alpha current_value prev_value
  python3 - <<PY "$@"
import sys
alpha=float(sys.argv[1]); cur=float(sys.argv[2]); prev=float(sys.argv[3])
print((alpha*cur)+((1-alpha)*prev))
PY
}

[ -f "$PROGRESS" ] || { echo "[ERROR] $PROGRESS not found"; exit 2; }

DOCS_RATE_EWMA=0.0
ALPHA=${ALPHA:-0.25}   # smoothing factor
STARTED_AT=$(jq -r '.started_at // empty' "$PROGRESS")
START_TS=$(iso_to_epoch "$STARTED_AT")
[ -n "$START_TS" ] || START_TS=$(date -u +%s)

while true; do
  clear || true
  NOW=$(date -u +%s)
  echo "[MONITOR] $(date -u +"%Y-%m-%dT%H:%M:%SZ")  interval=${INTERVAL}s"
  jq -C '{started_at, total_runs, completed_runs, failed_runs, total_docs, total_chunks, estimated_cost}' "$PROGRESS" || true

  # Aggregate docs_planned and docs_embedded
  DOCS_PLANNED=$(jq -r '[.runs[]?.docs_planned // 0] | add // 0' "$PROGRESS")
  [ "$DOCS_PLANNED" -eq 0 ] && DOCS_PLANNED=$(awk -F: '{s+=$2} END{print s+0}' "$RUNS_FILE" 2>/dev/null || echo 0)
  DOCS_EMBEDDED=$(jq -r '[.runs[]?.docs_embedded // 0] | add // 0' "$PROGRESS")

  ELAPSED=$(( NOW - START_TS ))
  ELAPSED=${ELAPSED#-} # safety

  # docs/sec overall (avoid div by zero)
  if [ "${ELAPSED:-0}" -gt 0 ]; then
    DOCS_RATE=$(python3 - <<PY "$DOCS_EMBEDDED" "$ELAPSED"
import sys; print(float(sys.argv[1]) / max(1.0, float(sys.argv[2])))
PY
)
  else
    DOCS_RATE=0.0
  fi

  # Smooth rate
  DOCS_RATE_EWMA=$(ewma "$ALPHA" "$DOCS_RATE" "${DOCS_RATE_EWMA:-0.0}" 2>/dev/null || echo "$DOCS_RATE")

  # Workers currently running: prefer real processes
  ACTIVE_WORKERS=$(pgrep -fc "trailblazer embed load" || echo 0)
  [ "$ACTIVE_WORKERS" -lt 1 ] && ACTIVE_WORKERS=1

  # If multiple workers are running, distribute ETA across them
  REMAIN=$(( DOCS_PLANNED - DOCS_EMBEDDED ))
  if python3 - <<PYCHECK "$REMAIN" "$DOCS_RATE_EWMA" "$ACTIVE_WORKERS" >/dev/null 2>&1; then
import sys
remain=float(sys.argv[1]); rate=float(sys.argv[2]); workers=float(sys.argv[3])
effective_rate = max(1e-6, rate)
eta = remain / effective_rate
print(int(eta))
PYCHECK
    ETA_SEC=$(python3 - <<PY "$REMAIN" "$DOCS_RATE_EWMA" "$ACTIVE_WORKERS"
import sys
remain=float(sys.argv[1]); rate=float(sys.argv[2]); workers=float(sys.argv[3])
effective_rate = max(1e-6, rate)            # overall rate (already includes workers); if you prefer per-worker, divide rate by workers and then multiply back.
eta = remain / effective_rate
print(int(eta))
PY
)
  else
    ETA_SEC=0
  fi

  # Pretty ETA
  ETA_STR=$(python3 - <<PY "$ETA_SEC"
import sys,datetime
s=int(sys.argv[1]);
print(str(datetime.timedelta(seconds=s)))
PY
)

  echo "---- progress ----"
  echo "docs: $DOCS_EMBEDDED / $DOCS_PLANNED   elapsed: ${ELAPSED}s   rate(ewma): $(printf '%.2f' "$DOCS_RATE_EWMA") docs/s   active_workers: $ACTIVE_WORKERS   ETA: ${ETA_STR}"

  echo "---- recent runs ----"
  jq -r '.runs | to_entries | sort_by(.value.completed_at) | reverse | .[0:8][]
    | "\(.key)  \(.value.status // "unknown")  docs=\(.value.docs_embedded // 0) chunks=\(.value.chunks_embedded // 0) dur=\(.value.duration_seconds // 0)s err=\(.value.error // "")"' "$PROGRESS" || true

  echo "---- tail of active logs ----"
  ls -1t "$LOGDIR"/embed-*.out 2>/dev/null | head -n 2 | while read -r f; do
    echo ">>> $f"; tail -n 30 "$f"; echo;
  done

  sleep "${INTERVAL}"
done
