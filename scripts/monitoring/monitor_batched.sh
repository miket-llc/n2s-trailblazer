#!/bin/bash

LOG_FILE="embedding_large_run_batched.log"

echo "=== Batched Retry Monitor ==="
echo "Time: $(date)"
echo

# Check if process is running
if pgrep -f retry_large_run_batched.sh > /dev/null; then
    echo "✅ Batched retry process is RUNNING"
else
    echo "❌ Batched retry process is NOT RUNNING"
fi

echo

# Get latest status
echo "📊 Latest Status:"
if [[ -f "$LOG_FILE" ]]; then
    grep -E "\[INFO\].*batch|SUCCESS|FAILED" "$LOG_FILE" | tail -5
fi

echo

# Check database for new embeddings
echo "📈 Database Stats:"
export DATABASE_URL="postgresql://trailblazer:trailblazer_dev_password@localhost:5432/trailblazer"
source .venv/bin/activate 2>/dev/null
python -c "
from sqlalchemy import create_engine, text
import os
engine = create_engine(os.environ['DATABASE_URL'])
with engine.connect() as conn:
    total = conn.execute(text('SELECT COUNT(*) FROM chunk_embeddings')).scalar()
    recent = conn.execute(text('SELECT COUNT(*) FROM chunk_embeddings WHERE created_at >= NOW() - INTERVAL \\'15 minutes\\')).scalar()
    print(f'  Total embeddings: {total:,}')
    print(f'  Added in last 15 min: {recent:,}')
" 2>/dev/null || echo "  DB query failed"

