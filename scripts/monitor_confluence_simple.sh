#!/usr/bin/env bash
# Simple live monitoring of Confluence ingest progress
set -euo pipefail

while true; do
    clear
    echo "🚀 Confluence Ingest Live Monitor"
    echo "================================"
    echo ""

    # Overall progress
    TOTAL_SPACES=$(wc -l < state/confluence/spaces.txt 2>/dev/null || echo "0")
    COMPLETED_RUNS=$(find runs/ -name "confluence.ndjson" 2>/dev/null | wc -l || echo "0")
    REMAINING=$((TOTAL_SPACES - COMPLETED_RUNS))
    PERCENT=$(( COMPLETED_RUNS * 100 / TOTAL_SPACES ))

    echo "📊 Progress: $COMPLETED_RUNS/$TOTAL_SPACES spaces completed ($PERCENT%)"
    echo "⏳ Remaining: $REMAINING spaces"
    echo ""

    # Current activity - show live progress from the most recent log
    echo "🔄 Live Activity:"
    echo "----------------"
    LATEST_LOG=$(ls -t logs/ingest-*full_adf*.out 2>/dev/null | head -1 || echo "")
    if [ -n "$LATEST_LOG" ]; then
        # Extract space name from log filename
        CURRENT_SPACE=$(echo "$LATEST_LOG" | sed 's/.*-\([A-Z][A-Z]*\)\.out$/\1/')
        echo "Current space: $CURRENT_SPACE"
        echo ""
        # Show recent progress lines
        tail -8 "$LATEST_LOG" | grep -E "(🚀|📋|\||✅|Total:|pages)" | tail -4
    fi
    echo ""

    # Recent completions from log files
    echo "✅ Last 5 Completed:"
    echo "-------------------"
    ls -t logs/ingest-*full_adf*.out 2>/dev/null | head -5 | while read logfile; do
        SPACE=$(echo "$logfile" | sed 's/.*-\([A-Z][A-Z]*\)\.out$/\1/')
        RID=$(echo "$logfile" | sed 's/.*ingest-\([^-]*\)-.*/\1/')

        # Try to get completion info
        if grep -q "✅ Completed" "$logfile" 2>/dev/null; then
            TOTAL_LINE=$(grep "Total:" "$logfile" | tail -1)
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
    echo "Press Ctrl+C to exit | Refreshing every 3 seconds..."
    echo "===================================================="

    sleep 3
done
