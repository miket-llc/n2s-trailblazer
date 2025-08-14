#!/usr/bin/env bash
set -euo pipefail
source .env
source .venv/bin/activate

SPACE_FLAG="${SPACE_FLAG:---space}"
BODY_FLAG="${BODY_FLAG:---body-format}"
ADF_VALUE="${ADF_VALUE:-atlas_doc_format}"
PROGRESS_FLAG="${PROGRESS_FLAG:-}"
PROGRESS_EVERY_FLAG="${PROGRESS_EVERY_FLAG:-}"
NOCOLOR_FLAG="${NOCOLOR_FLAG:-}"

while IFS= read -r SPACE; do
  [ -z "$SPACE" ] && continue
  RID="$(date -u +'%Y%m%dT%H%M%SZ')_${SPACE}_full_adf"
  echo "[START] space=$SPACE rid=$RID"
  # stdout: JSONL events; stderr: human progress
  trailblazer ingest confluence \
    "$SPACE_FLAG" "$SPACE" \
    "$BODY_FLAG" "$ADF_VALUE" \
    ${PROGRESS_FLAG:+$PROGRESS_FLAG} \
    ${PROGRESS_EVERY_FLAG:+$PROGRESS_EVERY_FLAG 5} \
    ${NOCOLOR_FLAG:+$NOCOLOR_FLAG} \
    1> "var/logs/ingest-$RID-$SPACE.jsonl" \
    2> >(tee -a "var/logs/ingest-$RID-$SPACE.out")
  echo "[DONE ] space=$SPACE rid=$RID exit=$?"
done < var/state/spaces_demo.txt
