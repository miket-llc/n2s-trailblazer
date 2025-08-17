#!/bin/bash

echo "🔍 EMBEDDING MONITOR - Real-time Status"
echo "======================================"

PID_FILE="embedding_process.pid"
if [[ -f "$PID_FILE" ]]; then
    PID=$(cat $PID_FILE)
    if ps -p $PID > /dev/null 2>&1; then
        echo "✅ Embedding process is RUNNING (PID: $PID)"
    else
        echo "❌ Embedding process is NOT running (PID: $PID)"
    fi
else
    echo "❓ No PID file found"
fi

echo ""
echo "📊 Current Database Stats:"
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
echo "🔍 Checking for errors/skips..."
LOG_FILE="embedding_fixed_run.log"
if [[ -f "$LOG_FILE" ]]; then
    if grep -q -i "skip\|error\|fail" "$LOG_FILE"; then
        echo "⚠️  ISSUES FOUND:"
        grep -i "skip\|error\|fail" "$LOG_FILE" | tail -3
    else
        echo "✅ No issues detected"
    fi
    
    echo ""
    echo "📝 Recent Progress:"
    tail -5 "$LOG_FILE"
else
    echo "❓ Log file not found"
fi

echo ""
echo "🔄 Following log in real-time (Ctrl+C to exit)..."
if [[ -f "$LOG_FILE" ]]; then
    tail -f "$LOG_FILE"
else
    echo "❌ Log file not accessible"
fi
