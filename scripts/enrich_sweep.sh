#!/usr/bin/env bash
set -euo pipefail

# Enrich Sweep Script - Thin wrapper around trailblazer enrich sweep CLI
#
# This script provides a safe, resumable, tmux-friendly sweep that:
# - Enumerates all var/runs/<RID> folders
# - Validates each has normalize/normalized.ndjson with >0 lines
# - Runs enrich (overwriting/refreshing outputs) and verifies enrich/enriched.jsonl > 0 lines
# - Writes a per-run result record (PASS/BLOCKED/FAIL with reason)
# - Produces timestamped sweep report and ready/blocked lists

# Set environment variables for safe operation (no pagers)
export PAGER=cat
export LESS=-RFX
export GIT_PAGER=cat

# Execute the CLI command with environment guards
exec trailblazer enrich-sweep \
  --runs-glob 'var/runs/*' \
  --min-quality 0.60 \
  --max-below-threshold-pct 0.20 \
  --max-workers "${TB_ENRICH_WORKERS:-8}" \
  --force \
  --out-dir var/enrich_sweep/
