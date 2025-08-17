#!/bin/bash

# Robust Bulk Embedding Script with Batching Support
# ==================================================
# Processes all runs with automatic batching for large runs to prevent timeouts

set -e

LOG_FILE="embedding_bulk_batched.log"
FAILURE_LOG="embedding_failures_batched.log"
BATCH_SIZE=1000  # Max chunks per batch
LARGE_RUN_THRESHOLD=2000  # Runs with more chunks get batched

log_message() {
    echo "$(date -Iseconds) [INFO] $1" | tee -a "$LOG_FILE"
}

log_error() {
    echo "$(date -Iseconds) [ERROR] $1" | tee -a "$LOG_FILE" "$FAILURE_LOG"
}

get_chunk_count() {
    local run_id="$1"
    local chunks_file="var/runs/$run_id/chunk/chunks.ndjson"
    
    if [[ -f "$chunks_file" ]]; then
        wc -l < "$chunks_file"
    else
        echo 0
    fi
}

process_run_batched() {
    local run_id="$1" 
    local total_chunks="$2"
    local batches_needed=$(( (total_chunks + BATCH_SIZE - 1) / BATCH_SIZE ))
    
    log_message "📊 Large run detected: $run_id"
    log_message "  Total chunks: $total_chunks"
    log_message "  Batches needed: $batches_needed" 
    
    local success_count=0
    local failure_count=0
    
    for batch in $(seq 1 $batches_needed); do
        log_message "🔥 Processing batch $batch/$batches_needed for run: $run_id"
        
        local start_time=$(date +%s)
        
        if timeout 1200 trailblazer embed load \
            --run-id "$run_id" \
            --provider openai \
            --model text-embedding-3-small \
            --dimensions 1536 \
            --max-chunks "$BATCH_SIZE" \
            --reembed-all >> "$LOG_FILE" 2>&1; then
            
            local end_time=$(date +%s)
            local duration=$((end_time - start_time))
            log_message "✅ SUCCESS: Batch $batch/$batches_needed completed (${duration}s)"
            ((success_count++))
        else
            local exit_code=$?
            local end_time=$(date +%s)
            local duration=$((end_time - start_time))
            
            log_error "❌ FAILED: Batch $batch/$batches_needed (exit code: $exit_code, ${duration}s)"
            ((failure_count++))
        fi
        
        # Brief pause between batches
        sleep 2
    done
    
    if [[ $failure_count -eq 0 ]]; then
        log_message "✅ SUCCESS: $run_id (all $batches_needed batches completed)"
        return 0
    else
        log_error "❌ PARTIAL FAILURE: $run_id ($failure_count/$batches_needed batches failed)"
        return 1
    fi
}

process_run_single() {
    local run_id="$1"
    local max_attempts=3
    
    for attempt in $(seq 1 $max_attempts); do
        log_message "Attempting to embed run: $run_id (attempt $attempt/$max_attempts)"
        
        local start_time=$(date +%s)
        
        if timeout 1200 trailblazer embed load \
            --run-id "$run_id" \
            --provider openai \
            --model text-embedding-3-small \
            --dimensions 1536 \
            --reembed-all >> "$LOG_FILE" 2>&1; then
            
            local end_time=$(date +%s)
            local duration=$((end_time - start_time))
            log_message "✅ SUCCESS: $run_id (${duration}s)"
            return 0
        else
            local exit_code=$?
            local end_time=$(date +%s)
            local duration=$((end_time - start_time))
            
            log_error "❌ FAILED: $run_id (exit code: $exit_code, attempt $attempt/$max_attempts, ${duration}s)"
            
            if [[ $attempt -lt $max_attempts ]]; then
                local wait_time=$((30 * attempt))
                log_message "Waiting ${wait_time}s before retry..."
                sleep $wait_time
            fi
        fi
    done
    
    log_error "❌ FINAL FAILURE: $run_id after $max_attempts attempts"
    return 1
}

process_run() {
    local run_id="$1"
    local chunk_count=$(get_chunk_count "$run_id")
    
    log_message "📋 Run analysis: $run_id ($chunk_count chunks)"
    
    if [[ $chunk_count -gt $LARGE_RUN_THRESHOLD ]]; then
        log_message "🔄 Using batched processing (chunks: $chunk_count > threshold: $LARGE_RUN_THRESHOLD)"
        process_run_batched "$run_id" "$chunk_count"
    else
        log_message "⚡ Using single processing (chunks: $chunk_count <= threshold: $LARGE_RUN_THRESHOLD)"
        process_run_single "$run_id"
    fi
}

database_health_check() {
    log_message "🔍 Performing database health check..."
    
    if ! timeout 30 trailblazer db-admin doctor >> "$LOG_FILE" 2>&1; then
        log_error "Database health check failed"
        return 1
    fi
    
    log_message "✅ Database is healthy"
    return 0
}

main() {
    local start_from="${1:-}"
    
    log_message "🚀 Starting robust bulk embedding with batching support"
    log_message "======================================================"
    
    # Setup environment
    log_message "Setting up environment..."
    source .venv/bin/activate
    source .env
    
    # Health check
    if ! database_health_check; then
        log_error "Pre-flight health check failed. Exiting."
        exit 1
    fi
    
    # Get list of runs
    local runs_file="/tmp/all_normalized_runs.txt"
    find var/runs -name "normalized.ndjson" | sed 's|var/runs/||; s|/normalize/normalized.ndjson||' | sort > "$runs_file"
    local total_runs=$(wc -l < "$runs_file")
    
    log_message "Total runs to process: $total_runs"
    
    # Find starting position if resuming
    local start_line=1
    if [[ -n "$start_from" ]]; then
        start_line=$(grep -n "$start_from" "$runs_file" | cut -d: -f1)
        if [[ -z "$start_line" ]]; then
            log_error "Start run '$start_from' not found"
            exit 1
        fi
        log_message "Resuming from run: $start_from (line $start_line)"
    fi
    
    local success_count=0
    local failure_count=0
    local current_run=0
    
    # Process each run
    while IFS= read -r run_id; do
        ((current_run++))
        
        if [[ $current_run -lt $start_line ]]; then
            continue
        fi
        
        local progress=$(( (current_run - start_line + 1) * 100 / (total_runs - start_line + 1) ))
        
        log_message ""
        log_message "🔥 [$current_run/$total_runs] Processing: $run_id"
        log_message "Progress: $current_run/$total_runs ($progress%)"
        
        if process_run "$run_id"; then
            ((success_count++))
        else
            ((failure_count++))
            echo "$(date -Iseconds) FAILED: $run_id" >> "$FAILURE_LOG"
        fi
        
        # Periodic health checks
        if (( current_run % 100 == 0 )); then
            log_message "🔍 Health check after $current_run runs..."
            database_health_check || log_error "Health check warning at run $current_run"
        fi
        
    done < "$runs_file"
    
    log_message ""
    log_message "🎉 ROBUST BULK EMBEDDING WITH BATCHING COMPLETE!"
    log_message "==============================================="
    log_message "Total runs processed: $total_runs"
    log_message "Successful: $success_count"
    log_message "Failed: $failure_count"
    log_message "Success rate: $(( success_count * 100 / total_runs ))%"
    
    if [[ $failure_count -gt 0 ]]; then
        log_message "❌ Some runs failed. Check $FAILURE_LOG for details."
        return 1
    else
        log_message "✅ All runs completed successfully!"
        return 0
    fi
}

main "$@"
