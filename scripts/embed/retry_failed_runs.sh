#!/bin/bash

# Retry Failed Embedding Runs with Extended Timeout
# =================================================

set -e

LOG_FILE="embedding_retry_failed.log"
FAILURE_LOG="embedding_retry_failures.log"

# Failed run IDs from the previous batch
FAILED_RUNS=(
    "2025-08-15_021543_a9bf"
    "2025-08-15_035201_5a0d" 
    "2025-08-15_050056_9ec6"
)

log_message() {
    echo "$(date -Iseconds) [INFO] $1" | tee -a "$LOG_FILE"
}

log_error() {
    echo "$(date -Iseconds) [ERROR] $1" | tee -a "$LOG_FILE" "$FAILURE_LOG"
}

retry_run() {
    local run_id="$1"
    local max_attempts=3
    
    log_message "🔥 Retrying failed run: $run_id"
    
    for attempt in $(seq 1 $max_attempts); do
        log_message "Attempting to embed run: $run_id (attempt $attempt/$max_attempts)"
        
        local start_time=$(date +%s)
        
        # Use extended 2-hour timeout for large runs
        if timeout 7200 trailblazer embed load \
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

main() {
    log_message "🚀 Starting retry of failed embedding runs"
    log_message "========================================"
    
    # Setup environment
    log_message "Setting up environment..."
    source .venv/bin/activate
    source .env
    
    local success_count=0
    local failure_count=0
    local total_runs=${#FAILED_RUNS[@]}
    
    log_message "Total failed runs to retry: $total_runs"
    log_message ""
    
    for run_id in "${FAILED_RUNS[@]}"; do
        if retry_run "$run_id"; then
            ((success_count++))
        else
            ((failure_count++))
        fi
        log_message ""
    done
    
    log_message "🎉 RETRY PROCESS COMPLETE!"
    log_message "========================="
    log_message "Total runs: $total_runs"
    log_message "Successful: $success_count" 
    log_message "Failed: $failure_count"
    
    if [[ $failure_count -gt 0 ]]; then
        log_message "❌ Some runs still failed. Check $FAILURE_LOG for details."
        return 1
    else
        log_message "✅ All failed runs completed successfully!"
        return 0
    fi
}

main "$@"
