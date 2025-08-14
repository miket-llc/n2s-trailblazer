#!/usr/bin/env bash
# Live monitoring of Confluence ingest progress
set -euo pipefail

clear
echo "🔍 Confluence Ingest Progress Monitor"
echo "======================================"
echo ""

while true; do
    # Get current progress
    TOTAL_SPACES=$(wc -l < state/confluence/spaces.txt 2>/dev/null || echo "0")
    COMPLETED_RUNS=$(find runs/ -name "confluence.ndjson" 2>/dev/null | wc -l || echo "0")
    REMAINING=$((TOTAL_SPACES - COMPLETED_RUNS))

    # Calculate percentage
    if [ "$TOTAL_SPACES" -gt 0 ]; then
        PERCENT=$(( (COMPLETED_RUNS * 100) / TOTAL_SPACES ))
    else
        PERCENT=0
    fi

    # Clear previous status (move cursor up and clear)
    printf "\033[2K\r"

    echo "📊 Overall Progress: $COMPLETED_RUNS/$TOTAL_SPACES spaces ($PERCENT%) | Remaining: $REMAINING"
    echo ""

    # Show current activity from the most recent log
    LATEST_LOG=$(ls -t logs/ingest-*full_adf*.out 2>/dev/null | head -1 || echo "")
    if [ -n "$LATEST_LOG" ]; then
        echo "🔄 Current Activity (from $LATEST_LOG):"
        echo "----------------------------------------"
        tail -10 "$LATEST_LOG" | grep -E "(START|🚀|📋|\||✅|Total:)" | tail -5
        echo ""
    fi

    # Show recent completions
    echo "✅ Recent Completions:"
    echo "--------------------"
    find runs/ -name "confluence.ndjson" 2>/dev/null | \
        sed 's|/ingest/confluence.ndjson||' | \
        xargs -I {} basename {} | \
        sort -t_ -k3 | \
        tail -5 | \
        while read RID; do
            if [ -f "runs/$RID/ingest/summary.json" ]; then
                PAGES=$(jq -r '.pages // "N/A"' "runs/$RID/ingest/summary.json" 2>/dev/null || echo "N/A")
                ATTACHMENTS=$(jq -r '.attachments // "N/A"' "runs/$RID/ingest/summary.json" 2>/dev/null || echo "N/A")
                ELAPSED=$(jq -r '.duration_seconds // "N/A"' "runs/$RID/ingest/summary.json" 2>/dev/null || echo "N/A")
                # Extract space from run ID
                SPACE=$(echo "$RID" | grep -o "_[A-Z][A-Z]*_" | sed 's/_//g' || echo "?")
                echo "  $SPACE ($RID): $PAGES pages, $ATTACHMENTS attachments (${ELAPSED}s)"
            else
                # Fallback: show run without summary
                SPACE=$(echo "$RID" | grep -o "_[A-Z][A-Z]*_" | sed 's/_//g' || echo "?")
                echo "  $SPACE ($RID): processing..."
            fi
        done

    echo ""
    echo "Press Ctrl+C to exit monitoring..."
    echo "=================================="

    sleep 3

    # Clear screen for next update
    printf "\033[H\033[2J"
done
