#!/bin/bash
# Page titles tracker - saves all processed page titles to a file
# This creates a permanent record of what pages were processed

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

PAGES_LOG="var/logs/processed_pages.log"

echo "🚀 Starting page titles tracker..."
echo "Log file: $PAGES_LOG"
echo "Press Ctrl+C to stop"

# Initialize log file
{
    echo "=== Page Titles Tracking Started at $(date) ==="
    echo "Format: [TIMESTAMP] [DOC_NUMBER] TITLE (STATUS)"
    echo
} > "$PAGES_LOG"

# Function to extract and log page titles
track_pages() {
    local log_file="$1"
    local run_id=$(basename "$log_file" .out | sed 's/embed-//')
    
    tail -f "$log_file" 2>/dev/null | while read line; do
        if [[ $line =~ (📖|⏭️).*\[([0-9]+)\].*\((embedding|skipped)\) ]]; then
            local timestamp=$(date "+%Y-%m-%d %H:%M:%S")
            local icon="${BASH_REMATCH[1]}"
            local doc_num="${BASH_REMATCH[2]}"
            local status="${BASH_REMATCH[3]}"
            
            # Extract title (everything between ] and ( )
            local title=$(echo "$line" | sed -n 's/.*\] \(.*\) (\(embedding\|skipped\)).*/\1/p')
            
            # Log to file
            echo "[$timestamp] [$doc_num] $title ($status) - Run: $run_id" >> "$PAGES_LOG"
            
            # Also display to console
            if [[ $status == "embedding" ]]; then
                echo "✨ [$doc_num] $title"
            else
                echo "⏭️  [$doc_num] $title (skipped)"
            fi
        fi
    done
}

# Monitor all current and future embedding logs
while true; do
    # Find the most recent embedding log
    latest_log=$(ls -t var/logs/embed-*.out 2>/dev/null | head -1 || echo "")
    
    if [ -n "$latest_log" ] && [ -f "$latest_log" ]; then
        echo "Tracking pages from: $latest_log"
        track_pages "$latest_log"
    else
        echo "Waiting for embedding logs..."
        sleep 5
    fi
done
