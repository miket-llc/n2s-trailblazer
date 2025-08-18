#!/usr/bin/env bash
set -euo pipefail

# Chunk Sweep Script - Thin wrapper around trailblazer chunk sweep CLI
#
# This script provides a safe, resumable, tmux-friendly sweep that:
# - Reads run IDs from ready_for_chunk.txt file
# - Validates each has enrich/enriched.jsonl with >0 lines
# - Runs chunk (overwriting/refreshing outputs) and verifies chunks.ndjson > 0 lines
# - Writes a per-run result record (PASS/BLOCKED/FAIL with reason)
# - Produces timestamped sweep report and ready-for-preflight list

# Set environment variables for safe operation (no pagers)
export PAGER=cat
export LESS=-RFX
export GIT_PAGER=cat

# Execute the CLI command with environment guards
exec trailblazer chunk-sweep \
  --input-file "var/enrich_sweep/20250818_184044/ready_for_chunk.txt" \
  --max-tokens "${TB_CHUNK_MAX_TOKENS:-800}" \
  --min-tokens "${TB_CHUNK_MIN_TOKENS:-120}" \
  --max-workers "${TB_CHUNK_WORKERS:-8}" \
  --force \
  --out-dir var/chunk_sweep/
