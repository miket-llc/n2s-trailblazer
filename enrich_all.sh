#!/bin/bash
set -euo pipefail

echo "=== MASSIVE ENRICHMENT SCRIPT ==="
echo "Finding all runs that need enrichment..."

# Get all runs that need enrichment
find var/runs -maxdepth 1 -type d -name "2025-08-15_*" | while read run_dir; do
    run_id=$(basename "$run_dir")
    if [ -d "$run_dir/ingest" ] && [ -d "$run_dir/normalize" ] && [ ! -d "$run_dir/enrich" ]; then
        echo "$run_id"
    fi
done > /tmp/runs_to_enrich.txt

total_runs=$(wc -l < /tmp/runs_to_enrich.txt)
echo "Total runs to enrich: $total_runs"

counter=0
while read run_id; do
    counter=$((counter + 1))
    echo "[$counter/$total_runs] ENRICHING: $run_id"

    # Run enrichment with minimal output
    trailblazer enrich "$run_id" --no-llm --no-progress > /dev/null 2>&1

    # Progress update every 50 runs
    if [ $((counter % 50)) -eq 0 ]; then
        echo "Progress: $counter/$total_runs runs enriched"
    fi
done < /tmp/runs_to_enrich.txt

echo "=== MASSIVE ENRICHMENT COMPLETE ==="
echo "All $total_runs runs have been enriched!"
