#!/usr/bin/env bash
# Show current Confluence ingest status - one-shot view
set -euo pipefail

echo "🚀 Confluence Ingest Status"
echo "=========================="
echo ""

# Overall progress
TOTAL_SPACES=$(wc -l < var/state/confluence/spaces.txt 2>/dev/null || echo "0")
COMPLETED_RUNS=$(find var/runs/ -name "confluence.ndjson" 2>/dev/null | wc -l || echo "0")
REMAINING=$((TOTAL_SPACES - COMPLETED_RUNS))
PERCENT=$(( COMPLETED_RUNS * 100 / TOTAL_SPACES ))

echo "📊 Overall Progress: $COMPLETED_RUNS/$TOTAL_SPACES spaces ($PERCENT%)"
echo "⏳ Remaining: $REMAINING spaces"
echo ""

# Current activity
echo "🔄 Current Activity:"
echo "------------------"
LATEST_LOG=$(ls -t var/logs/ingest-*full_adf*.out 2>/dev/null | head -1 || echo "")
if [ -n "$LATEST_LOG" ]; then
    SPACE=$(echo "$LATEST_LOG" | sed 's/.*-\([^-]*\)\.out$/\1/')
    echo "Processing space: $SPACE"
    echo ""
    echo "Recent progress lines:"
    tail -8 "$LATEST_LOG" | grep -E "(\||🚀|📋|✅)" | tail -4
else
    echo "No active ingestion found."
fi
echo ""

# Recent completions
echo "✅ Last 5 Completed Spaces:"
echo "--------------------------"
ls -t var/logs/ingest-*full_adf*.out 2>/dev/null | head -5 | while read logfile; do
    SPACE=$(echo "$logfile" | sed 's/.*-\([^-]*\)\.out$/\1/')

    if grep -q "✅ Completed" "$logfile" 2>/dev/null; then
        TOTAL_LINE=$(grep "Total:" "$logfile" | tail -1 || echo "")
        if [ -n "$TOTAL_LINE" ]; then
            echo "  $SPACE: $TOTAL_LINE"
        else
            echo "  $SPACE: Completed"
        fi
    else
        echo "  $SPACE: In progress..."
    fi
done

echo ""
echo "💡 To monitor live: bash scripts/show_confluence_status.sh"
echo "💡 To see raw progress: tail -f var/logs/ingest-*full_adf*.out"
