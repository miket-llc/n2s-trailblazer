#!/bin/bash
set -euo pipefail

# Setup
source .venv/bin/activate
export OPENAI_API_KEY="${OPENAI_API_KEY:?OPENAI_API_KEY must be set}"

# Get all run IDs from normalized files
ALL_RUNS=($(find var/runs -name "normalized.ndjson" -not -empty | sed 's|var/runs/||' | sed 's|/normalize/normalized.ndjson||' | sort))

echo "Found ${#ALL_RUNS[@]} runs to process"
echo "Maintaining 3 parallel processes continuously..."

MAX_PARALLEL=3
CURRENT_INDEX=0

# Function to start a process
start_process() {
    local run_id="$1"
    local process_num="$2"

    echo "Starting process $process_num for run $run_id..."
    nohup trailblazer embed load \
        --run-id "$run_id" \
        --provider openai \
        --model text-embedding-3-small \
        --batch 32 \
        --reembed-all \
        > "var/logs/parallel${process_num}.ndjson" \
        2> "var/logs/parallel${process_num}.stderr.log" &

    echo $! > "var/logs/parallel${process_num}.pid"
}

# Start initial processes
for i in $(seq 1 $MAX_PARALLEL); do
    if [ $CURRENT_INDEX -lt ${#ALL_RUNS[@]} ]; then
        start_process "${ALL_RUNS[$CURRENT_INDEX]}" "$i"
        ((CURRENT_INDEX++))
    fi
done

# Monitor and restart processes as they complete
while [ $CURRENT_INDEX -lt ${#ALL_RUNS[@]} ]; do
    sleep 10

    for i in $(seq 1 $MAX_PARALLEL); do
        PID_FILE="var/logs/parallel${i}.pid"
        if [ -f "$PID_FILE" ]; then
            PID=$(cat "$PID_FILE")
            if ! kill -0 "$PID" 2>/dev/null; then
                # Process finished, start next one
                echo "Process $i finished, starting next run..."
                if [ $CURRENT_INDEX -lt ${#ALL_RUNS[@]} ]; then
                    start_process "${ALL_RUNS[$CURRENT_INDEX]}" "$i"
                    ((CURRENT_INDEX++))
                fi
            fi
        fi
    done
done

echo "All runs queued, waiting for remaining processes to complete..."
wait
echo "All embedding processes completed!"
