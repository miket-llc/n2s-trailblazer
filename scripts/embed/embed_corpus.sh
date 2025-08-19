#!/bin/bash

# Simple wrapper for trailblazer embed.corpus command
# ================================================

set -e

# Default values
PROVIDER=${EMBED_PROVIDER:-"openai"}
MODEL=${OPENAI_EMBED_MODEL:-"text-embedding-3-small"}
DIMENSIONS=${EMBED_DIMENSIONS:-1536}
BATCH_SIZE=${EMBED_BATCH_SIZE:-1000}
LARGE_RUN_THRESHOLD=${EMBED_LARGE_RUN_THRESHOLD:-2000}

# Parse command line arguments
RESUME_FROM=""
REEMBED_ALL=false
CHANGED_ONLY=false
MAX_RUNS=""
DRY_RUN_COST=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --resume-from)
            RESUME_FROM="$2"
            shift 2
            ;;
        --reembed-all)
            REEMBED_ALL=true
            shift
            ;;
        --changed-only)
            CHANGED_ONLY=true
            shift
            ;;
        --max-runs)
            MAX_RUNS="$2"
            shift 2
            ;;
        --dry-run-cost)
            DRY_RUN_COST=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Wrapper for trailblazer embed.corpus command"
            echo ""
            echo "Options:"
            echo "  --resume-from RUN_ID    Resume from specific run ID"
            echo "  --reembed-all           Force re-embed all documents"
            echo "  --changed-only          Only embed changed documents"
            echo "  --max-runs N            Maximum number of runs to process"
            echo "  --dry-run-cost          Estimate cost without calling API"
            echo "  --help, -h              Show this help message"
            echo ""
            echo "Environment variables:"
            echo "  EMBED_PROVIDER          Embedding provider (default: openai)"
            echo "  OPENAI_EMBED_MODEL      Model name (default: text-embedding-3-small)"
            echo "  EMBED_DIMENSIONS        Dimensions (default: 1536)"
            echo "  EMBED_BATCH_SIZE        Batch size (default: 1000)"
            echo "  EMBED_LARGE_RUN_THRESHOLD  Large run threshold (default: 2000)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Build command
CMD="trailblazer embed corpus"
CMD="$CMD --provider $PROVIDER"
CMD="$CMD --model $MODEL"
CMD="$CMD --dimension $DIMENSIONS"
CMD="$CMD --batch $BATCH_SIZE"
CMD="$CMD --large-run-threshold $LARGE_RUN_THRESHOLD"

if [[ -n "$RESUME_FROM" ]]; then
    CMD="$CMD --resume-from $RESUME_FROM"
fi

if [[ "$REEMBED_ALL" == true ]]; then
    CMD="$CMD --reembed-all"
fi

if [[ "$CHANGED_ONLY" == true ]]; then
    CMD="$CMD --changed-only"
fi

if [[ -n "$MAX_RUNS" ]]; then
    CMD="$CMD --max-runs $MAX_RUNS"
fi

if [[ "$DRY_RUN_COST" == true ]]; then
    CMD="$CMD --dry-run-cost"
fi

echo "🚀 Starting corpus embedding with CLI..."
echo "Command: $CMD"
echo ""

# Execute the command
exec $CMD
