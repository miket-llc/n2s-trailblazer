#!/usr/bin/env bash

# Compatibility wrapper to the canonical monitor script location
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$DIR/scripts/monitoring/monitor_embedding.sh" "$@"

#!/bin/bash
# Embedding progress monitor script
export TRAILBLAZER_DB_URL="postgresql://trailblazer:trailblazer_dev_password@localhost:5432/trailblazer"

while true; do
    clear
    echo "🚀 EMBEDDING PROGRESS MONITOR"
    echo "============================="
    echo "$(date)"
    echo
    
    # Get current counts
    EMBEDDINGS=$(python3 -c "import psycopg2; conn=psycopg2.connect(\"postgresql://trailblazer:trailblazer_dev_password@localhost:5432/trailblazer\"); cur=conn.cursor(); cur.execute(\"SELECT COUNT(*) FROM public.chunk_embeddings\"); print(cur.fetchone()[0]); conn.close()")
    
    TARGET=314174
    PERCENT=$(python3 -c "print(f\"{$EMBEDDINGS/$TARGET*100:.3f}\")")
    REMAINING=$(python3 -c "print($TARGET - $EMBEDDINGS)")
    
    echo "📊 PROGRESS:"
    echo "   Embeddings created: $EMBEDDINGS"
    echo "   Target total: $TARGET"
    echo "   Remaining: $REMAINING"
    echo "   Progress: $PERCENT%"
    echo
    
    # Estimate time remaining
    if [ "$EMBEDDINGS" -gt 15 ]; then
        RATE=$(python3 -c "print(f\"{$EMBEDDINGS/60:.1f}\")")  # assuming 1 minute elapsed
        ETA=$(python3 -c "print(int($REMAINING/$RATE/60) if $RATE > 0 else 999)")
        echo "   Rate: $RATE embeddings/min"
        echo "   ETA: ~$ETA minutes"
    fi
    
    echo
    echo "🔄 Refreshing every 30 seconds..."
    echo "Press Ctrl+C to stop monitoring"
    sleep 30
done
