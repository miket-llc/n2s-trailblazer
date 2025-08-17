#!/bin/bash

# Get all run IDs
RUN_IDS=$(find var/runs -name "normalized.ndjson" | sed 's|var/runs/||' | sed 's|/normalize/normalized.ndjson||' | sort)
TOTAL_RUNS=$(echo "$RUN_IDS" | wc -l)
CURRENT=0

echo "🚀 Starting FINAL bulk embedding for $TOTAL_RUNS runs - VIRGIN DATABASE!"
echo "=================================================================="

# export OPENAI_API_KEY="your-api-key-here"  # Set in .env instead

for RUN_ID in $RUN_IDS; do
    CURRENT=$((CURRENT + 1))
    echo ""
    echo "🔥 [$CURRENT/$TOTAL_RUNS] Processing run: $RUN_ID"
    echo "=================================="
    
    # Run embedding WITHOUT --reembed-all since database is virgin
    if trailblazer embed load \
        --run-id "$RUN_ID" \
        --provider openai \
        --model text-embedding-3-small \
        --dimensions 1536; then
        echo "✅ SUCCESS: $RUN_ID"
        
        # Quick check for any skips in this run
        SKIP_COUNT=$(grep -c "skipped" /tmp/last_run.log 2>/dev/null || echo "0")
        if [ "$SKIP_COUNT" -gt 0 ]; then
            echo "⚠️  WARNING: $SKIP_COUNT skips found in $RUN_ID"
        fi
    else
        echo "❌ FAILED: $RUN_ID" | tee -a failed_runs.log
    fi
    
    sleep 0.1
done

echo ""
echo "🎉 FINAL BULK EMBEDDING COMPLETE!"
echo "=================================="

# Final stats
python3 -c "
import trailblazer.db.engine
from sqlalchemy import text
engine = trailblazer.db.engine.get_engine()
with engine.connect() as conn:
    chunk_count = conn.execute(text('SELECT COUNT(*) FROM chunks')).fetchone()[0]
    embedding_count = conn.execute(text('SELECT COUNT(*) FROM chunk_embeddings')).fetchone()[0]
    doc_count = conn.execute(text('SELECT COUNT(*) FROM documents')).fetchone()[0]
    
    print(f'📊 FINAL RESULTS:')
    print(f'Documents: {doc_count:,}')
    print(f'Chunks: {chunk_count:,}')
    print(f'Embeddings: {embedding_count:,}')
    if chunk_count > 0:
        print(f'Coverage: {(embedding_count/chunk_count*100):.1f}%')
    else:
        print('Coverage: 0%')
"
