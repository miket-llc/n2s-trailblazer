#!/bin/bash
set -e

source .venv/bin/activate
export OPENAI_API_KEY="${OPENAI_API_KEY:?OPENAI_API_KEY must be set}"

echo "Starting continuous embedding of all runs..."

# Get all runs
ALL_RUNS=($(find var/runs -name "normalized.ndjson" -not -empty | sed 's|var/runs/||' | sed 's|/normalize/normalized.ndjson||' | sort))
echo "Found ${#ALL_RUNS[@]} total runs to process"

MAX_PARALLEL=3
current_idx=0

while [ $current_idx -lt ${#ALL_RUNS[@]} ]; do
    # Count currently running processes
    running=$(ps aux | grep -v grep | grep "trailblazer embed" | wc -l)

    if [ $running -lt $MAX_PARALLEL ]; then
        # Start a new process
        run_id="${ALL_RUNS[$current_idx]}"
        log_num=$((current_idx % 10))  # Cycle through log files 0-9

        echo "Starting process for run $run_id (index $current_idx)"
        nohup trailblazer embed load \
            --run-id "$run_id" \
            --provider openai \
            --model text-embedding-3-small \
            --batch 32 \
            --reembed-all \
            > "var/logs/continuous_${log_num}.ndjson" \
            2> "var/logs/continuous_${log_num}.stderr.log" &

        current_idx=$((current_idx + 1))
        sleep 2  # Brief pause between starts
    else
        # Wait a bit before checking again
        sleep 5
    fi
done

echo "All runs started, waiting for completion..."
wait
echo "All embedding processes completed!"
