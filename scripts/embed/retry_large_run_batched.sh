#!/bin/bash

# Retry Large Run in Batches to Avoid Transaction Timeouts
# ========================================================

set -e

LOG_FILE="embedding_large_run_batched.log"
FAILURE_LOG="embedding_large_run_failures.log" 
LARGE_RUN="2025-08-15_021543_a9bf"
BATCH_SIZE=1000  # Process 1000 chunks at a time

log_message() {
    echo "$(date -Iseconds) [INFO] $1" | tee -a "$LOG_FILE"
}

log_error() {
    echo "$(date -Iseconds) [ERROR] $1" | tee -a "$LOG_FILE" "$FAILURE_LOG"
}

process_batch() {
    local run_id="$1"
    local max_chunks="$2"
    local batch_num="$3"
    
    log_message "🔥 Processing batch $batch_num: $run_id (max $max_chunks chunks)"
    
    local start_time=$(date +%s)
    
    # Use shorter timeout for smaller batches (20 minutes should be plenty)
    if timeout 1200 trailblazer embed load \
        --run-id "$run_id" \
        --provider openai \
        --model text-embedding-3-small \
        --dimensions 1536 \
        --max-chunks "$max_chunks" \
        --reembed-all >> "$LOG_FILE" 2>&1; then
        
        local end_time=$(date +%s)
        local duration=$((end_time - start_time))
        log_message "✅ SUCCESS: Batch $batch_num completed (${duration}s)"
        return 0
    else
        local exit_code=$?
        local end_time=$(date +%s)
        local duration=$((end_time - start_time))
        
        log_error "❌ FAILED: Batch $batch_num (exit code: $exit_code, ${duration}s)"
        return 1
    fi
}

retry_large_run_batched() {
    local run_id="$LARGE_RUN"
    local total_chunks=$(wc -l < "var/runs/$run_id/chunk/chunks.ndjson")
    local batches_needed=$(( (total_chunks + BATCH_SIZE - 1) / BATCH_SIZE ))
    
    log_message "📊 Large run analysis:"
    log_message "  Run: $run_id"
    log_message "  Total chunks: $total_chunks"
    log_message "  Batch size: $BATCH_SIZE"
    log_message "  Batches needed: $batches_needed"
    log_message ""
    
    local success_count=0
    local failure_count=0
    
    # Process in batches
    for batch in $(seq 1 $batches_needed); do
        if process_batch "$run_id" "$BATCH_SIZE" "$batch"; then
            ((success_count++))
        else
            ((failure_count++))
            # Continue with next batch even if one fails
        fi
        
        # Brief pause between batches to be nice to the API
        sleep 5
    done
    
    log_message "🎯 Batched processing complete:"
    log_message "  Successful batches: $success_count/$batches_needed"
    log_message "  Failed batches: $failure_count"
    
    return $failure_count
}

retry_small_runs() {
    local small_runs=("2025-08-15_035201_5a0d" "2025-08-15_050056_9ec6")
    local success_count=0
    local failure_count=0
    
    for run_id in "${small_runs[@]}"; do
        log_message "🔥 Processing small run: $run_id"
        
        local start_time=$(date +%s)
        
        if timeout 600 trailblazer embed load \
            --run-id "$run_id" \
            --provider openai \
            --model text-embedding-3-small \
            --dimensions 1536 \
            --reembed-all >> "$LOG_FILE" 2>&1; then
            
            local end_time=$(date +%s)
            local duration=$((end_time - start_time))
            log_message "✅ SUCCESS: $run_id (${duration}s)"
            ((success_count++))
        else
            local exit_code=$?
            local end_time=$(date +%s)
            local duration=$((end_time - start_time))
            
            log_error "❌ FAILED: $run_id (exit code: $exit_code, ${duration}s)"
            ((failure_count++))
        fi
    done
    
    log_message "Small runs complete: $success_count/2 successful, $failure_count failed"
    return $failure_count
}

main() {
    log_message "🚀 Starting batched retry of failed embedding runs"
    log_message "==============================================="
    
    # Setup environment  
    log_message "Setting up environment..."
    source .venv/bin/activate
    source .env
    
    local total_failures=0
    
    # Process the large run in batches
    log_message "Phase 1: Processing large run in batches..."
    if ! retry_large_run_batched; then
        ((total_failures += $?))
    fi
    
    log_message ""
    log_message "Phase 2: Processing small runs..."
    if ! retry_small_runs; then
        ((total_failures += $?))
    fi
    
    log_message ""
    log_message "🎉 BATCHED RETRY PROCESS COMPLETE!"
    log_message "================================="
    
    if [[ $total_failures -eq 0 ]]; then
        log_message "✅ All runs completed successfully!"
        return 0
    else
        log_message "❌ Some batches/runs failed. Check $FAILURE_LOG for details."
        return 1
    fi
}

main "$@"
