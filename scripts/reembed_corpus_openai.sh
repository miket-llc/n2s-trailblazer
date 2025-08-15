#!/bin/bash
# Re-embed Entire Corpus with OpenAI (Serial, Observable)
# This script provides a repeatable, maintainable way to re-embed the entire
# Ellucian documentation corpus with OpenAI embeddings.

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Load environment variables
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Required environment variables
: "${OPENAI_API_KEY:?OPENAI_API_KEY is required}"
: "${TRAILBLAZER_DB_URL:?TRAILBLAZER_DB_URL is required}"
export DB_URL="$TRAILBLAZER_DB_URL"

# Embedding configuration
EMBED_PROVIDER="openai"
EMBED_MODEL="text-embedding-3-small"
EMBED_DIMENSIONS="1536"  # Match expected default for compatibility
BATCH_SIZE="128"

# Export for trailblazer CLI
export OPENAI_EMBED_DIM="$EMBED_DIMENSIONS"

# Logging and progress tracking
LOG_DIR="var/logs"
PROGRESS_FILE="var/reembed_progress.json"
ERROR_LOG="var/reembed_errors.log"
COST_LOG="var/reembed_cost.log"

# Create log directory
mkdir -p "$LOG_DIR"

# Support single-run mode for dispatcher
if [[ "${1:-}" == "--single" ]]; then
  shift
  run_id="$1"; docs_count="${2:-0}"
  # shellcheck disable=SC2034
  BATCH_SIZE="${BATCH_SIZE:-128}"   # allow override from env
  init_progress
  embed_run "$run_id" "$docs_count"
  exit $?
fi

# Support list-only mode to identify runs without starting embedding
if [[ "${1:-}" == "--list-only" ]]; then
  echo "🔍 Identifying runs to embed (largest first)..."
  init_progress
  runs_file=$(get_runs_to_embed)
  total_runs=$(wc -l < "$runs_file")
  total_docs=$(awk -F: '{sum += $2} END {print sum}' "$runs_file")
  
  echo "✅ Found $total_runs runs with $total_docs total documents"
  echo "📄 Runs file: $runs_file"
  echo "📊 Progress tracking initialized: $PROGRESS_FILE"
  echo ""
  echo "🔝 Top 10 runs by document count:"
  head -10 "$runs_file" | while IFS=: read -r run_id docs_count; do
    echo "  - $run_id: $docs_count docs"
  done
  exit 0
fi

# Initialize progress tracking
init_progress() {
    if [ ! -f "$PROGRESS_FILE" ]; then
        cat > "$PROGRESS_FILE" << EOF
{
  "started_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "total_runs": 0,
  "completed_runs": 0,
  "failed_runs": 0,
  "total_docs": 0,
  "total_chunks": 0,
  "estimated_cost": 0.0,
  "runs": {}
}
EOF
    fi
}

# Update progress
update_progress() {
    local run_id="$1"
    local status="$2"
    local docs_embedded="${3:-0}"
    local chunks_embedded="${4:-0}"
    local duration="${5:-0}"
    local error="${6:-}"

    # Update progress file
    jq --arg run_id "$run_id" \
       --arg status "$status" \
       --argjson docs "$docs_embedded" \
       --argjson chunks "$chunks_embedded" \
       --argjson duration "$duration" \
       --arg error "$error" \
       --arg completed_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
       '.runs[$run_id] = {
         "status": $status,
         "docs_embedded": $docs,
         "chunks_embedded": $chunks,
         "duration_seconds": $duration,
         "error": $error,
         "completed_at": $completed_at
       } | .completed_runs += 1' \
       "$PROGRESS_FILE" > "${PROGRESS_FILE}.tmp" && mv "${PROGRESS_FILE}.tmp" "$PROGRESS_FILE"
}

# Get runs worth embedding (exclude empty templates)
get_runs_to_embed() {
    echo "=== Identifying runs worth embedding ===" >&2

    local runs_file="var/temp_runs_to_embed.txt"
    if [ -s "$runs_file" ]; then
      echo "Using existing $runs_file" >&2
      # ensure sorted largest-first by the count column if present
      sort -t: -k2 -nr "$runs_file" -o "$runs_file" || true
      # update totals in progress file
      local total_runs=$(wc -l < "$runs_file")
      local total_docs=$(awk -F: '{sum += $2} END {print sum}' "$runs_file")
      jq --argjson total_runs "$total_runs" --argjson total_docs "$total_docs" \
         '.total_runs=$total_runs | .total_docs=$total_docs' \
         "$PROGRESS_FILE" > "${PROGRESS_FILE}.tmp" && mv "${PROGRESS_FILE}.tmp" "$PROGRESS_FILE"

      # Add docs_planned for existing temp file
      while IFS=: read -r rid docs; do
        jq --arg rid "$rid" --argjson docs "$docs" '
          .runs[$rid] = (.runs[$rid] // {})
          | .runs[$rid].docs_planned = $docs
          | .runs[$rid].status = (.runs[$rid].status // "planned")
        ' "$PROGRESS_FILE" > "$PROGRESS_FILE.tmp" && mv "$PROGRESS_FILE.tmp" "$PROGRESS_FILE"
      done < "$runs_file"

      echo "$runs_file"
      return 0
    fi

    for run in $(ls -1t var/runs | grep -v '^INDEX' | grep -v '^logs$' | grep -v '^nonexistent-run-id$' | grep -v '^test'); do
        if [ -f "var/runs/$run/enrich/enriched.jsonl" ]; then
            local size=$(wc -l < "var/runs/$run/enrich/enriched.jsonl")
            if [ $size -gt 0 ]; then
                # Check if this is an empty template
                local title=$(cat "var/runs/$run/normalize/normalized.ndjson" | jq -r '.title' 2>/dev/null | head -1)
                local text_length=$(cat "var/runs/$run/normalize/normalized.ndjson" | jq -r '.text_md' 2>/dev/null | head -1 | wc -c)

                # Skip only confirmed empty templates
                if [ "$text_length" != 114 ] || [ "$title" != "Overview" ]; then
                    if [ "$text_length" != 172 ] || [ "$title" != "Descripción general" ]; then
                        echo "$run:$size" >> "$runs_file"
                    fi
                fi
            fi
        fi
    done

    # Sort by document count (largest first for efficiency)
    sort -t: -k2 -nr "$runs_file" > "${runs_file}.sorted" && mv "${runs_file}.sorted" "$runs_file"

    local total_runs=$(wc -l < "$runs_file")
    local total_docs=$(awk -F: '{sum += $2} END {print sum}' "$runs_file")

    echo "Found $total_runs runs with $total_docs total documents"
    echo "Runs file: $runs_file"

    # Update progress file with totals
    jq --argjson total_runs "$total_runs" \
       --argjson total_docs "$total_docs" \
       '.total_runs = $total_runs | .total_docs = $total_docs' \
       "$PROGRESS_FILE" > "${PROGRESS_FILE}.tmp" && mv "${PROGRESS_FILE}.tmp" "$PROGRESS_FILE"

    # After computing $runs_file, $total_runs, $total_docs …
    # Write a runs_plan map { run_id: {docs_planned: N, status:"planned"} }
    jq -n --argfile p "$PROGRESS_FILE" '
      $p as $base
      | $base
    ' > "$PROGRESS_FILE.tmp" && mv "$PROGRESS_FILE.tmp" "$PROGRESS_FILE"

    while IFS=: read -r rid docs; do
      jq --arg rid "$rid" --argjson docs "$docs" '
        .runs[$rid] = (.runs[$rid] // {})
        | .runs[$rid].docs_planned = $docs
        | .runs[$rid].status = (.runs[$rid].status // "planned")
      ' "$PROGRESS_FILE" > "$PROGRESS_FILE.tmp" && mv "$PROGRESS_FILE.tmp" "$PROGRESS_FILE"
    done < "$runs_file"

    echo "$runs_file"
}

# Estimate cost for a run
estimate_run_cost() {
  local run_id="$1"
  # Total chars across all text_md in the run
  local total_chars
  total_chars=$(jq -r '.text_md' "var/runs/$run_id/normalize/normalized.ndjson" | wc -c | tr -d ' ')
  # rough tokens ≈ chars/4
  local tokens=$(( total_chars / 4 ))

  # pick price per 1k tokens by model (default small)
  local price_per_1k="0.00002"
  case "$EMBED_MODEL" in
    *text-embedding-3-large*) price_per_1k="0.00013" ;;
  esac

  # cost = tokens/1k * price_per_1k
  echo "$(echo "scale=6; ($tokens / 1000) * $price_per_1k" | bc -l)"
}

# Embed a single run
embed_run() {
    local run_id="$1"
    local docs_count="$2"

    echo "🔄 Embedding run: $run_id ($docs_count docs)"

    local start_time=$(date +%s)
    local log_file="var/logs/embed-$run_id.jsonl"
    local error_file="var/logs/embed-$run_id.out"

    # Estimate cost
    local estimated_cost=$(estimate_run_cost "$run_id" "$docs_count")
    echo "  💰 Estimated cost: \$${estimated_cost}"

    # Start monitoring log file for page-by-page progress
    echo "  📋 Monitoring progress (Ctrl+C to stop monitoring, embedding continues)..."

    # Function to monitor and show page titles
    monitor_embedding_progress() {
        local log_file="$1"
        local error_file="$2"
        local run_id="$3"

        # Show a few sample page titles from this run first
        echo "  📄 Sample pages in this run:"
        if [ -f "var/runs/$run_id/normalize/normalized.ndjson" ]; then
            head -3 "var/runs/$run_id/normalize/normalized.ndjson" | jq -r '.title' | sed 's/^/    • /'
        fi
        echo

        # Monitor the error file for progress updates
        tail -f "$error_file" 2>/dev/null &
        local tail_pid=$!

        # Wait for the command to complete
        wait $embed_pid 2>/dev/null
        local result=$?

        # Stop monitoring
        kill $tail_pid 2>/dev/null

        return $result
    }

    # Run embedding in background so we can monitor it
    (source .venv/bin/activate && \
     trailblazer embed load \
       --run-id "$run_id" \
       --provider "$EMBED_PROVIDER" \
       --model "$EMBED_MODEL" \
       --batch "$BATCH_SIZE" \
       --reembed-all \
       1> "$log_file" \
       2> "$error_file") &
    local embed_pid=$!

    # Monitor progress
    monitor_embedding_progress "$log_file" "$error_file" "$run_id"
    local result=$?

    if [ $result -eq 0 ]; then

        local end_time=$(date +%s)
        local duration=$((end_time - start_time))

        # Extract metrics from assurance file
        if [ -f "var/runs/$run_id/embed_assurance.json" ]; then
            local docs_embedded=$(jq -r '.docs_embedded' "var/runs/$run_id/embed_assurance.json")
            local chunks_embedded=$(jq -r '.chunks_embedded' "var/runs/$run_id/embed_assurance.json")

            echo "  ✅ Success: $docs_embedded docs, $chunks_embedded chunks in ${duration}s"
            update_progress "$run_id" "completed" "$docs_embedded" "$chunks_embedded" "$duration"

            # Log cost
            echo "$(date -u +%Y-%m-%dT%H:%M:%SZ),$run_id,$docs_embedded,$chunks_embedded,$estimated_cost" >> "$COST_LOG"
        else
            echo "  ⚠️  Warning: No assurance file found"
            update_progress "$run_id" "completed" "$docs_count" "unknown" "$duration"
        fi

        # After reading embed_assurance.json (or if missing), update per-run entry
        jq --arg run_id "$run_id" \
           --argjson docs "${docs_embedded:-0}" \
           --argjson chunks "${chunks_embedded:-0}" \
           '.runs[$run_id].docs_embedded = ($docs)
            | .runs[$run_id].chunks_embedded = ($chunks)' \
           "$PROGRESS_FILE" > "${PROGRESS_FILE}.tmp" && mv "${PROGRESS_FILE}.tmp" "$PROGRESS_FILE"

        return 0
    else
        local end_time=$(date +%s)
        local duration=$((end_time - start_time))
        local error_msg=$(tail -1 "$error_file" 2>/dev/null || echo "Unknown error")

        echo "  ❌ Failed: $error_msg"
        update_progress "$run_id" "failed" "0" "0" "$duration" "$error_msg"

        # Log error
        echo "$(date -u +%Y-%m-%dT%H:%M:%SZ),$run_id,ERROR,$error_msg" >> "$ERROR_LOG"

        return 1
    fi
}

# Main execution
main() {
    echo "🚀 Starting OpenAI corpus re-embedding"
    echo "Provider: $EMBED_PROVIDER"
    echo "Model: $EMBED_MODEL"
    echo "Dimensions: $EMBED_DIMENSIONS"
    echo "Batch size: $BATCH_SIZE"
    echo "Log directory: $LOG_DIR"
    echo

    # Initialize progress tracking
    init_progress

    # Get list of runs to embed
    local runs_file=$(get_runs_to_embed)

    # Process runs
    local total_runs=$(wc -l < "$runs_file")
    local current_run=0
    local failed_runs=0

    echo "=== Starting embedding process ==="

    while IFS=: read -r run_id docs_count; do
        current_run=$((current_run + 1))
        echo "[$current_run/$total_runs] Processing $run_id"

        if embed_run "$run_id" "$docs_count"; then
            echo "  ✅ Completed successfully"
        else
            echo "  ❌ Failed"
            failed_runs=$((failed_runs + 1))
        fi

        echo

        # Progress update
        local progress=$((current_run * 100 / total_runs))
        echo "Progress: $progress% ($current_run/$total_runs runs processed)"
        echo

    done < "$runs_file"

    # Final summary
    echo "=== Embedding Complete ==="
    echo "Total runs processed: $total_runs"
    echo "Successful runs: $((total_runs - failed_runs))"
    echo "Failed runs: $failed_runs"
    echo "Progress file: $PROGRESS_FILE"
    echo "Error log: $ERROR_LOG"
    echo "Cost log: $COST_LOG"

    # Calculate total cost
    if [ -f "$COST_LOG" ]; then
        local total_cost=$(awk -F, 'NR>1 {sum += $5} END {print sum}' "$COST_LOG" 2>/dev/null || echo "0")
        echo "Total estimated cost: \$${total_cost:-0.00}"
    fi

    # Cleanup
    rm -f "$runs_file"
}

# Handle interrupts gracefully
trap 'echo -e "\n⚠️  Interrupted. Progress saved to $PROGRESS_FILE"; exit 1' INT TERM

# Run main function
main "$@"
