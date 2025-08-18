#!/bin/bash

# Simple embedding monitoring script that wraps CLI output
# ======================================================

set -euo pipefail

# Ensure no pagers trigger
export PAGER=cat
export LESS=-RFX

echo "🔍 EMBEDDING MONITOR - CLI Status"
echo "================================="

# Check if corpus embedding is running
PROGRESS_FILE="var/progress/embedding.json"
if [[ -f "$PROGRESS_FILE" ]]; then
    echo "📊 Current Progress:"
    python3 -c "
import json
import sys
from datetime import datetime

try:
    with open('$PROGRESS_FILE', 'r') as f:
        data = json.load(f)

    status = data.get('status', 'unknown')
    current_run = data.get('current_run', 'none')
    processed = data.get('processed_runs', 0)
    total = data.get('total_runs', 0)
    successful = data.get('successful_runs', 0)
    failed = data.get('failed_runs', 0)

    print(f'Status: {status.upper()}')
    if current_run and current_run != 'none':
        print(f'Current Run: {current_run}')
    print(f'Progress: {processed}/{total} runs')
    print(f'Successful: {successful}, Failed: {failed}')

    if status == 'running' and total > 0:
        percent = (processed / total) * 100
        print(f'Completion: {percent:.1f}%')

    if 'started_at' in data:
        started = datetime.fromisoformat(data['started_at'].replace('Z', '+00:00'))
        now = datetime.now(started.tzinfo)
        duration = now - started
        print(f'Duration: {duration}')

    if 'total_docs' in data:
        print(f'Documents: {data.get("total_docs", 0):,}')
        print(f'Chunks: {data.get("total_chunks", 0):,}')
        print(f'Cost: ${data.get("estimated_cost", 0):.4f}')

except Exception as e:
    print(f'Error reading progress: {e}')
    sys.exit(1)
"
else
    echo "❓ No embedding progress found"
    echo "Run 'trailblazer embed corpus' to start embedding"
fi

echo ""
echo "📊 Database Stats:"
python3 -c "
try:
    import trailblazer.db.engine
    from sqlalchemy import text
    engine = trailblazer.db.engine.get_engine()
    with engine.connect() as conn:
        docs = conn.execute(text('SELECT COUNT(*) FROM documents')).fetchone()[0]
        chunks = conn.execute(text('SELECT COUNT(*) FROM chunks')).fetchone()[0]
        embeddings = conn.execute(text('SELECT COUNT(*) FROM chunk_embeddings')).fetchone()[0]
        print(f'📄 Documents: {docs:,}')
        print(f'🧩 Chunks: {chunks:,}')
        print(f'🧠 Embeddings: {embeddings:,}')
        if chunks > 0:
            coverage = (embeddings/chunks*100)
            print(f'📈 Coverage: {coverage:.1f}%')
except Exception as e:
    print(f'Error getting stats: {e}')
"

echo ""
echo "🔍 Provider/Dimension Health:"
python3 -c "
try:
    import trailblazer.db.engine
    from sqlalchemy import text
    engine = trailblazer.db.engine.get_engine()
    with engine.connect() as conn:
        result = conn.execute(text('''
            SELECT provider, dimension, COUNT(*) AS n
            FROM public.chunk_embeddings
            GROUP BY 1,2
            ORDER BY 1,2
        ''')).fetchall()

        if not result:
            print('No embeddings found in database')
        else:
            print('Provider | Dimension | Count')
            print('---------|-----------|-------')
            for row in result:
                provider, dimension, count = row
                print(f'{provider:<8} | {dimension:>9} | {count:>5,}')

            # Check for dimension drift
            if len(result) > 1:
                print('')
                print('⚠️  dimension drift detected')
except Exception as e:
    print(f'Error getting provider/dimension stats: {e}')
"

echo ""
echo "📝 Recent Logs:"
LOG_DIR="var/logs/embedding"
if [[ -d "$LOG_DIR" ]]; then
    LATEST_LOG=$(ls -t "$LOG_DIR"/corpus_embedding_*.log 2>/dev/null | head -1)
    if [[ -n "$LATEST_LOG" ]]; then
        echo "Latest log: $(basename "$LATEST_LOG")"
        echo "Recent entries:"
        tail -5 "$LATEST_LOG" 2>/dev/null || echo "  (log file empty or unreadable)"
    else
        echo "No corpus embedding logs found"
    fi
else
    echo "Log directory not found: $LOG_DIR"
fi

# Check for active workers
echo ""
echo "👷 Active Workers:"
if pgrep -f "trailblazer embed" >/dev/null 2>&1; then
    echo "Active embed processes:"
    ps aux | grep "trailblazer embed" | grep -v grep | awk '{print "  PID " $2 ": " $11 " " $12 " " $13}' || echo "  (no processes found)"
else
    echo "No active embed processes"
fi

# Show dispatcher logs if available
if [[ -f "var/logs/dispatcher.out" ]]; then
    echo ""
    echo "🚚 Recent Dispatcher Activity:"
    tail -5 "var/logs/dispatcher.out" 2>/dev/null || echo "  (dispatcher log empty)"
fi

echo ""
echo "💡 Usage:"
echo "  trailblazer embed corpus --help                    # Show options"
echo "  trailblazer embed corpus                          # Start embedding"
echo "  trailblazer embed corpus --resume-from RUN_ID     # Resume from specific run"
echo "  trailblazer embed corpus --max-runs 10            # Limit runs to process"
