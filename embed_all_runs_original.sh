#!/bin/bash
set -euo pipefail

cd /Users/miket/dev/n2s-trailblazer
source .venv/bin/activate
source .env

echo "🚀 EMBEDDING ALL RUNS - 163,444+ DOCUMENTS (ORIGINAL CONFIG)"
echo "=============================================================="

# Get all run IDs that have normalized documents
run_ids=($(find var/runs -name "normalized.ndjson" -not -empty | sed 's|var/runs/||; s|/normalize/normalized.ndjson||' | sort))

total_runs=${#run_ids[@]}
echo "📊 Found $total_runs runs to embed"

counter=0
for run_id in "${run_ids[@]}"; do
    counter=$((counter + 1))
    doc_count=$(wc -l < "var/runs/$run_id/normalize/normalized.ndjson")

    echo ""
    echo "🔄 [$counter/$total_runs] Embedding run: $run_id ($doc_count docs)"
    echo "   Progress: $(( counter * 100 / total_runs ))%"

    # Use original text-embedding-3-small with original batch size
    if trailblazer embed load --run-id "$run_id" --provider openai --reembed-all; then
        echo "✅ Success: $run_id"
    else
        echo "❌ Failed: $run_id (continuing...)"
        # Continue with next run instead of stopping
    fi
done

echo ""
echo "🎉 FINISHED EMBEDDING ALL RUNS!"
echo "=============================================================="

# Final verification
echo "📋 Final database verification:"
docker exec -it trailblazer-postgres env PAGER=cat psql -U trailblazer -P pager=off -d trailblazer -c "
SELECT COUNT(*) AS total_chunks FROM public.chunks;
SELECT COUNT(*) AS total_embeddings FROM public.chunk_embeddings;
"
