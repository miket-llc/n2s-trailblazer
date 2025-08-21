#!/bin/bash
# Quick ingestion script - simplified interface
# Usage: ./scripts/quick-ingest.sh [space-key] [since-date]

set -e

SPACE_KEY="${1:-}"
SINCE_DATE="${2:-}"

if [[ -z "$SPACE_KEY" ]]; then
    echo "❌ Usage: $0 <space-key> [since-date]"
    echo "   Example: $0 N2S 2025-01-01"
    echo "   Example: $0 N2S (for all time)"
    exit 1
fi

echo "🚀 Quick ingestion for space: $SPACE_KEY"
if [[ -n "$SINCE_DATE" ]]; then
    echo "   Since: $SINCE_DATE"
    ./scripts/tb.sh ingest confluence --space-key "$SPACE_KEY" --since "$SINCE_DATE"
else
    echo "   All time"
    ./scripts/tb.sh ingest confluence --space-key "$SPACE_KEY"
fi
