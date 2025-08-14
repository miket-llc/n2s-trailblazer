#!/usr/bin/env bash

echo "🔍 TRAILBLAZER INGEST MONITOR"
echo "============================="

# Function to show current status
show_status() {
    echo ""
    echo "📊 CURRENT STATUS $(date)"
    echo "-------------------------"
    
    # Check if overnight process is running
    if pgrep -f "overnight_ingest.sh" > /dev/null; then
        echo "✅ Overnight ingest process: RUNNING"
    else
        echo "❌ Overnight ingest process: NOT RUNNING"
    fi
    
    # Show latest console output
    if [ -f "logs/overnight.console" ]; then
        echo "📋 Latest console output:"
        tail -5 "logs/overnight.console" | sed 's/^/   /'
    fi
    
    # Show recent runs
    echo ""
    echo "📁 Recent runs:"
    ls -1t runs | head -3 | while read RID; do
        if [ -f "runs/$RID/ingest/progress.json" ]; then
            PAGES=$(jq -r '.pages_processed // 0' "runs/$RID/ingest/progress.json" 2>/dev/null || echo "0")
            ATTACHMENTS=$(jq -r '.attachments_processed // 0' "runs/$RID/ingest/progress.json" 2>/dev/null || echo "0") 
            TIMESTAMP=$(jq -r '.timestamp // ""' "runs/$RID/ingest/progress.json" 2>/dev/null || echo "")
            echo "   $RID: $PAGES pages, $ATTACHMENTS attachments ($TIMESTAMP)"
        else
            echo "   $RID: (in progress or no data)"
        fi
    done
    
    # Show active log files
    echo ""
    echo "📄 Active log files (last 5 minutes):"
    find logs -name "*.out" -mmin -5 2>/dev/null | head -5 | while read LOG; do
        SIZE=$(wc -l < "$LOG" 2>/dev/null || echo "0")
        echo "   $LOG ($SIZE lines)"
    done
}

# If argument provided, show status once and exit
if [ $# -gt 0 ]; then
    show_status
    exit 0
fi

# Otherwise, monitor continuously
echo "Starting continuous monitoring (Ctrl+C to stop)..."
echo "Use: $0 status  for one-time status check"
echo ""

while true; do
    show_status
    echo ""
    echo "⏱️  Sleeping 30 seconds... (Ctrl+C to stop)"
    sleep 30
    clear
done
