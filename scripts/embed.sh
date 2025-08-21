#!/bin/bash
# Quick embedding script - simplified interface
# Usage: ./scripts/quick-embed.sh [run-id] [provider] [model] [dimensions]

set -e

RUN_ID="${1:-}"
PROVIDER="${2:-openai}"
MODEL="${3:-text-embedding-3-small}"
DIMENSIONS="${4:-1536}"

if [[ -z "$RUN_ID" ]]; then
    echo "❌ Usage: $0 <run-id> [provider] [model] [dimensions]"
    echo "   Example: $0 2025-01-15-1234 openai text-embedding-3-small 1536"
    exit 1
fi

echo "🚀 Quick embedding for run: $RUN_ID"
echo "   Provider: $PROVIDER"
echo "   Model: $MODEL"
echo "   Dimensions: $DIMENSIONS"
echo ""

# Use the wrapper script
./scripts/tb.sh embed load \
    --run-id "$RUN_ID" \
    --provider "$PROVIDER" \
    --model "$MODEL" \
    --dimension "$DIMENSIONS"
