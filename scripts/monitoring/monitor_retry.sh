#!/bin/bash

# Monitor retry progress
LOG_FILE="embedding_retry_failed.log"

echo "=== Retry Progress Monitor ==="
echo "Time: $(date)"
echo

# Check if process is running
if pgrep -f retry_failed_runs.sh > /dev/null; then
    echo "✅ Retry process is RUNNING"
else
    echo "❌ Retry process is NOT RUNNING"
fi

echo

# Get latest status from log
echo "📊 Latest Status:"
if [[ -f "$LOG_FILE" ]]; then
    grep -E "\[INFO\].*Processing:|SUCCESS:|FAILED:" "$LOG_FILE" | tail -5
else
    echo "Log file not found"
fi

echo

# Count chunk writes to track progress  
echo "📈 Progress Stats:"
if [[ -f "$LOG_FILE" ]]; then
    chunk_writes=$(grep -c "chunk.write" "$LOG_FILE" 2>/dev/null || echo 0)
    echo "  Chunks processed: $chunk_writes"
    
    current_run=$(grep "chunk.write" "$LOG_FILE" | tail -1 | grep -o '"run_id": "[^"]*"' | cut -d'"' -f4 2>/dev/null || echo "Unknown")
    echo "  Current run: $current_run"
    
    # Check database for actual embeddings added
    export DATABASE_URL="postgresql://trailblazer:trailblazer_dev_password@localhost:5432/trailblazer"
    source .venv/bin/activate 2>/dev/null
    new_embeddings=$(python -c "
from sqlalchemy import create_engine, text
import os
engine = create_engine(os.environ['DATABASE_URL'])
with engine.connect() as conn:
    result = conn.execute(text('SELECT COUNT(*) FROM chunk_embeddings WHERE created_at >= CURRENT_DATE'))
    print(result.scalar())
" 2>/dev/null || echo "DB query failed")
    echo "  Total embeddings created today: $new_embeddings"
else
    echo "  No log file found"
fi

