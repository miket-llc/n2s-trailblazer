#!/bin/bash
set -euo pipefail

# Setup
source .venv/bin/activate
export OPENAI_API_KEY="${OPENAI_API_KEY:?OPENAI_API_KEY must be set}"

# Get all run IDs from normalized files
ALL_RUNS=($(find var/runs -name "normalized.ndjson" -not -empty | sed 's|var/runs/||' | sed 's|/normalize/normalized.ndjson||' | sort))

echo "Found ${#ALL_RUNS[@]} runs to process"

# Process runs in parallel batches
BATCH_SIZE=2
for ((i=0; i<${#ALL_RUNS[@]}; i+=BATCH_SIZE)); do
    BATCH=(${ALL_RUNS[@]:i:BATCH_SIZE})
    echo "Processing batch starting at index $i: ${BATCH[@]}"

    # Start processes for this batch
    for j in "${!BATCH[@]}"; do
        RUN_ID="${BATCH[j]}"
        LOG_PREFIX="embed$(printf "%02d" $((i+j)))"

        echo "Starting process for run $RUN_ID..."
        nohup trailblazer embed load \
            --run-id "$RUN_ID" \
            --provider openai \
            --model text-embedding-3-small \
            --batch 32 \
            --reembed-all \
            > "var/logs/${LOG_PREFIX}.ndjson" \
            2> "var/logs/${LOG_PREFIX}.stderr.log" &
    done

    # Wait for this batch to complete before starting next
    wait
    echo "Batch completed"
done

echo "All runs processed!"
