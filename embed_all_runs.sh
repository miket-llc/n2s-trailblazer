#!/bin/bash

# Get all run IDs
RUN_IDS=$(find var/runs -name "normalized.ndjson" | sed 's|var/runs/||' | sed 's|/normalize/normalized.ndjson||' | sort)
TOTAL_RUNS=$(echo "$RUN_IDS" | wc -l)
CURRENT=0

echo "🚀 Starting bulk embedding for $TOTAL_RUNS runs - NO CHUNK LIMITS!"
echo "=================================="

# Activate environment and set API key
source .venv/bin/activate
# export OPENAI_API_KEY="your-api-key-here"  # Set in .env instead

for RUN_ID in $RUN_IDS; do
    CURRENT=$((CURRENT + 1))
    echo ""
    echo "🔥 [$CURRENT/$TOTAL_RUNS] Processing run: $RUN_ID"
    echo "=================================="
    
    # Run embedding with NO chunk limits
    if trailblazer embed load \
        --run-id "$RUN_ID" \
        --provider openai \
        --model text-embedding-3-small \
        --dimensions 1536; then
        echo "✅ SUCCESS: $RUN_ID"
    else
        echo "❌ FAILED: $RUN_ID" | tee -a failed_runs.log
        # Continue processing other runs even if one fails
    fi
    
    # Brief pause to avoid overwhelming the API
    sleep 0.1
done

echo ""
echo "🎉 BULK EMBEDDING COMPLETE!"
echo "=================================="
echo "Processed: $TOTAL_RUNS runs"

# Check final database stats
python -c "
from trailblazer.db.engine import get_session
from sqlalchemy import text

with get_session() as session:
    chunk_count = session.execute(text('SELECT COUNT(*) FROM chunks;')).scalar()
    embedding_count = session.execute(text('SELECT COUNT(*) FROM chunk_embeddings;')).scalar()
    doc_count = session.execute(text('SELECT COUNT(DISTINCT doc_id) FROM chunks;')).scalar()
    
    print(f'')
    print(f'📊 FINAL RESULTS:')
    print(f'Documents: {doc_count:,}')
    print(f'Chunks: {chunk_count:,}')
    print(f'Embeddings: {embedding_count:,}')
    print(f'Coverage: {(embedding_count/chunk_count*100):.1f}%')
"

if [ -f failed_runs.log ]; then
    echo ""
    echo "⚠️  Failed runs logged to: failed_runs.log"
fi
