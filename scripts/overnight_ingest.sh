#!/usr/bin/env bash
set -euo pipefail
SPACES_FILE="state/confluence/spaces.txt"
[ -f "$SPACES_FILE" ] || { echo "Missing $SPACES_FILE"; exit 2; }

echo "🚀 OVERNIGHT INGEST STARTING $(date)"
TOTAL_SPACES=$(wc -l < "$SPACES_FILE")
echo "📊 Processing $TOTAL_SPACES spaces from $SPACES_FILE"
echo "=============================================="

SPACE_NUM=0
while IFS= read -r SPACE; do
  [ -z "$SPACE" ] && continue
  SPACE_NUM=$((SPACE_NUM + 1))
  RID="$(date -u +'%Y%m%dT%H%M%SZ')_${SPACE}_backfill"

  echo "[$SPACE_NUM/$TOTAL_SPACES] 🔄 STARTING: $SPACE (run_id=$RID)"

  # JSON → stdout log; Human-readable progress → stderr log
  EXIT_CODE=0
  trailblazer ingest confluence \
    --space "$SPACE" \
    --progress --progress-every 5 \
    --log-format auto \
    1> "logs/ingest-$RID-$SPACE.jsonl" \
    2> >(tee "logs/ingest-$RID-$SPACE.out" | sed "s/^/[$SPACE] /") || EXIT_CODE=$?
  if [ $EXIT_CODE -eq 0 ]; then
    echo "[$SPACE_NUM/$TOTAL_SPACES] ✅ COMPLETED: $SPACE (exit=$EXIT_CODE)"
    # Show summary if available
    if test -f "runs/$RID/ingest/progress.json"; then
      PAGES=$(jq -r '.pages_processed // 0' "runs/$RID/ingest/progress.json")
      ATTACHMENTS=$(jq -r '.attachments_processed // 0' "runs/$RID/ingest/progress.json")
      echo "[$SPACE_NUM/$TOTAL_SPACES] 📈 SUMMARY: $SPACE → $PAGES pages, $ATTACHMENTS attachments"
    fi
  else
    echo "[$SPACE_NUM/$TOTAL_SPACES] ❌ FAILED: $SPACE (exit=$EXIT_CODE)"
  fi

  # Progress indicator
  PERCENT=$((SPACE_NUM * 100 / TOTAL_SPACES))
  echo "[$SPACE_NUM/$TOTAL_SPACES] 📊 OVERALL PROGRESS: $PERCENT% complete"
  echo "=============================================="

  # be polite to the API between spaces
  sleep 3
done < "$SPACES_FILE"

echo "🎉 OVERNIGHT INGEST COMPLETED $(date)"
