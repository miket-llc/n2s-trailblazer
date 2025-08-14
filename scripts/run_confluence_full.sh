#!/usr/bin/env bash
set -euo pipefail
SPACES_FILE="var/state/confluence/spaces.txt"
[ -f "$SPACES_FILE" ] || { echo "Missing $SPACES_FILE"; exit 2; }
while IFS= read -r SPACE; do
  [ -z "$SPACE" ] && continue
  RID="$(date -u +'%Y%m%dT%H%M%SZ')_${SPACE}_full_adf"
  echo "[START] Confluence space=$SPACE run_id=$RID"
  # JSON logs (stdout) → file; Pretty progress (stderr) → terminal + file
  trailblazer ingest confluence \
    --space "$SPACE" \
    --body-format atlas_doc_format \
    --progress --progress-every 5 \
    1> "var/logs/ingest-$RID-$SPACE.jsonl" \
    2> >(tee -a "var/logs/ingest-$RID-$SPACE.out") || true
  echo "[DONE ] Confluence space=$SPACE run_id=$RID exit=$?"
  # quick roll-up
  test -f "var/runs/$RID/ingest/summary.json" && jq -c '{rid:"'"$RID"'",space:"'"$SPACE"'",pages,attachments,links_total,elapsed_seconds}' "var/runs/$RID/ingest/summary.json" || true
  sleep 2
done < "$SPACES_FILE"
