#!/bin/bash

echo "🔬 TRAILBLAZER EMBEDDING MONITOR"
echo "=================================="

while true; do
    clear
    echo "🔬 TRAILBLAZER EMBEDDING MONITOR - $(date)"
    echo "=================================="

    # Check if process is running
    if pgrep -f "embed_all_runs.sh" > /dev/null; then
        echo "✅ Status: RUNNING"
        echo "📊 PID: $(pgrep -f embed_all_runs.sh)"
    else
        echo "❌ Status: NOT RUNNING"
    fi

    echo ""
    echo "📈 DATABASE PROGRESS:"
    docker exec trailblazer-postgres psql -U trailblazer -d trailblazer -P pager=off -c "
    SELECT
        COUNT(*) AS total_chunks,
        (COUNT(*) * 100.0 / 163444) AS percent_complete
    FROM chunks;
    SELECT COUNT(*) AS total_embeddings FROM chunk_embeddings;
    " 2>/dev/null || echo "Database connection error"

    echo ""
    echo "📝 LATEST ACTIVITY (last 5 lines):"
    tail -5 var/logs/embed_all_runs.out | grep -E "(🔄|✅|❌|Progress|embedding)" | tail -3 || echo "No recent activity"

    echo ""
    echo "🎯 TARGET: 163,444 documents across 1,805 runs"
    echo "⏱️  Next update in 10 seconds... (Ctrl+C to exit)"

    sleep 10
done
