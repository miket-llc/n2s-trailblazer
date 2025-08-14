#!/usr/bin/env bash
set -euo pipefail

SPACE_FLAG="${SPACE_FLAG:---space}"
BODY_FLAG="${BODY_FLAG:---body-format}"
ADF_VALUE="${ADF_VALUE:-atlas_doc_format}"
PROGRESS_FLAG="${PROGRESS_FLAG:-}"
PROGRESS_EVERY_FLAG="${PROGRESS_EVERY_FLAG:-}"
NOCOLOR_FLAG="${NOCOLOR_FLAG:-}"

TOTAL_SPACES=$(wc -l < var/state/spaces.txt)
CURRENT=0
SUCCESS=0
FAILED=0

echo "🚀 Starting full Confluence ingest for $TOTAL_SPACES spaces"

while IFS= read -r SPACE; do
  [ -z "$SPACE" ] && continue
  CURRENT=$((CURRENT + 1))
  
  RID="$(date -u +'%Y%m%dT%H%M%SZ')_${SPACE}_full_adf"
  echo ""
  echo "[$CURRENT/$TOTAL_SPACES] [START] space=$SPACE rid=$RID"
  
  # Run with error handling
  if trailblazer ingest confluence \
    "$SPACE_FLAG" "$SPACE" \
    "$BODY_FLAG" "$ADF_VALUE" \
    ${PROGRESS_FLAG:+$PROGRESS_FLAG} \
    ${PROGRESS_EVERY_FLAG:+$PROGRESS_EVERY_FLAG 5} \
    ${NOCOLOR_FLAG:+$NOCOLOR_FLAG} \
    1> "var/logs/ingest-$RID-$SPACE.jsonl" \
    2> >(tee -a "var/logs/ingest-$RID-$SPACE.out") 2>&1; then
    
    SUCCESS=$((SUCCESS + 1))
    echo "[$CURRENT/$TOTAL_SPACES] [SUCCESS] space=$SPACE rid=$RID"
  else
    FAILED=$((FAILED + 1))
    echo "[$CURRENT/$TOTAL_SPACES] [FAILED] space=$SPACE rid=$RID (exit=$?)"
    echo "FAILED: $SPACE" >> var/logs/failed_spaces.txt
  fi
  
  # Progress summary every 50 spaces
  if [ $((CURRENT % 50)) -eq 0 ]; then
    echo ""
    echo "🏁 PROGRESS: $CURRENT/$TOTAL_SPACES processed, $SUCCESS success, $FAILED failed"
    echo ""
  fi
  
done < var/state/spaces.txt

echo ""
echo "🎯 FINAL SUMMARY: $TOTAL_SPACES processed, $SUCCESS success, $FAILED failed"
echo "Failed spaces logged to: var/logs/failed_spaces.txt"
