#!/bin/bash
# ETA Estimation Script for Corpus Re-embedding
# Provides intelligent time remaining estimates with trend analysis

set -euo pipefail
export PAGER=cat
export LESS=-RFX

# Configuration
INTERVAL="${INTERVAL:-30}"  # Check every 30 seconds by default
PROGRESS_FILE="var/logs/reembed_progress.json"
ETA_LOG="var/logs/eta_estimates.log"
LOOKBACK_MINUTES="${LOOKBACK_MINUTES:-10}"  # Use last 10 minutes for rate calculation

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Initialize ETA log if it doesn't exist
init_eta_log() {
    if [ ! -f "$ETA_LOG" ]; then
        echo "timestamp,completed_runs,completed_docs,completed_chunks,rate_docs_per_min,eta_minutes,active_workers" > "$ETA_LOG"
    fi
}

# Get current active workers
get_active_workers() {
    pgrep -f "trailblazer embed load" | wc -l | tr -d ' '
}

# Calculate completion rate over lookback period
calculate_rate() {
    local lookback_seconds=$((LOOKBACK_MINUTES * 60))
    local cutoff_time=$(($(date +%s) - lookback_seconds))
    
    # Get recent rate data
    if [ -f "$ETA_LOG" ] && [ $(wc -l < "$ETA_LOG") -gt 1 ]; then
        # Extract recent entries within lookback period
        local recent_data
        recent_data=$(tail -20 "$ETA_LOG" | awk -F, -v cutoff="$cutoff_time" '
            NR>1 && $1 >= cutoff {
                docs[NR] = $3
                times[NR] = $1
                count++
            }
            END {
                if (count >= 2) {
                    time_diff = times[NR] - times[2]
                    doc_diff = docs[NR] - docs[2]
                    if (time_diff > 0) {
                        rate_per_sec = doc_diff / time_diff
                        rate_per_min = rate_per_sec * 60
                        print rate_per_min
                    } else {
                        print 0
                    }
                } else {
                    print 0
                }
            }
        ')
        echo "${recent_data:-0}"
    else
        echo "0"
    fi
}

# Format duration in human readable format
format_duration() {
    local minutes=$1
    
    if [ "$minutes" = "0" ] || [ "$minutes" = "" ]; then
        echo "Calculating..."
        return
    fi
    
    local hours=$((minutes / 60))
    local remaining_minutes=$((minutes % 60))
    local days=$((hours / 24))
    local remaining_hours=$((hours % 24))
    
    if [ $days -gt 0 ]; then
        echo "${days}d ${remaining_hours}h ${remaining_minutes}m"
    elif [ $hours -gt 0 ]; then
        echo "${hours}h ${remaining_minutes}m"
    else
        echo "${minutes}m"
    fi
}

# Get progress data
get_progress() {
    if [ ! -f "$PROGRESS_FILE" ]; then
        echo "0 0 0 0"
        return
    fi
    
    jq -r '
        .completed_runs // 0,
        (.runs | to_entries | map(.value.docs_embedded // 0) | add) // 0,
        (.runs | to_entries | map(.value.chunks_embedded // 0) | add) // 0,
        .total_docs // 0
    ' "$PROGRESS_FILE" | tr '\n' ' '
}

# Log current stats
log_stats() {
    local timestamp="$1"
    local completed_runs="$2"
    local completed_docs="$3"
    local completed_chunks="$4"
    local rate="$5"
    local eta_minutes="$6"
    local active_workers="$7"
    
    echo "$timestamp,$completed_runs,$completed_docs,$completed_chunks,$rate,$eta_minutes,$active_workers" >> "$ETA_LOG"
}

# Display status
display_status() {
    local completed_runs="$1"
    local completed_docs="$2"
    local completed_chunks="$3"
    local total_docs="$4"
    local rate="$5"
    local eta_minutes="$6"
    local active_workers="$7"
    
    local remaining_docs=$((total_docs - completed_docs))
    local percent_complete=0
    
    if [ "$total_docs" -gt 0 ]; then
        percent_complete=$((completed_docs * 100 / total_docs))
    fi
    
    clear
    echo -e "${CYAN}🚀 Trailblazer Corpus Embedding - ETA Monitor${NC}"
    echo -e "${CYAN}=================================================${NC}"
    echo
    echo -e "${GREEN}📊 Progress Summary:${NC}"
    echo -e "  Runs completed: ${YELLOW}$completed_runs${NC}"
    echo -e "  Documents: ${YELLOW}$completed_docs${NC} / ${YELLOW}$total_docs${NC} (${YELLOW}$percent_complete%${NC})"
    echo -e "  Chunks created: ${YELLOW}$completed_chunks${NC}"
    echo -e "  Remaining docs: ${YELLOW}$remaining_docs${NC}"
    echo
    echo -e "${BLUE}⚡ Performance:${NC}"
    echo -e "  Active workers: ${YELLOW}$active_workers${NC}"
    echo -e "  Processing rate: ${YELLOW}$(printf "%.1f" "$rate")${NC} docs/min"
    echo
    if [ "$eta_minutes" != "0" ] && [ "$rate" != "0" ]; then
        local eta_formatted
        eta_formatted=$(format_duration "$eta_minutes")
        echo -e "${PURPLE}⏱️  Estimated time remaining: ${YELLOW}$eta_formatted${NC}"
    else
        echo -e "${PURPLE}⏱️  Estimated time remaining: ${YELLOW}Calculating...${NC}"
    fi
    echo
    echo -e "${CYAN}Last updated: $(date)${NC}"
    echo -e "${CYAN}Refresh interval: ${INTERVAL}s | Lookback: ${LOOKBACK_MINUTES}m${NC}"
    echo
    echo -e "${GREEN}Press Ctrl+C to stop monitoring${NC}"
}

# Main monitoring loop
main() {
    echo -e "${CYAN}🚀 Starting ETA Monitor (interval: ${INTERVAL}s)${NC}"
    init_eta_log
    
    while true; do
        local timestamp=$(date +%s)
        local progress_data
        progress_data=$(get_progress)
        read -r completed_runs completed_docs completed_chunks total_docs <<< "$progress_data"
        
        local active_workers
        active_workers=$(get_active_workers)
        
        local rate
        rate=$(calculate_rate)
        
        local eta_minutes=0
        if [ "$rate" != "0" ] && [ "$completed_docs" -lt "$total_docs" ]; then
            local remaining_docs=$((total_docs - completed_docs))
            eta_minutes=$(echo "scale=0; $remaining_docs / $rate" | bc -l 2>/dev/null || echo "0")
        fi
        
        # Log the data
        log_stats "$timestamp" "$completed_runs" "$completed_docs" "$completed_chunks" "$rate" "$eta_minutes" "$active_workers"
        
        # Display status
        display_status "$completed_runs" "$completed_docs" "$completed_chunks" "$total_docs" "$rate" "$eta_minutes" "$active_workers"
        
        sleep "$INTERVAL"
    done
}

# Handle interrupts gracefully
trap 'echo -e "\n${GREEN}ETA monitoring stopped.${NC}"; exit 0' INT TERM

# Check dependencies
if ! command -v jq >/dev/null 2>&1; then
    echo -e "${RED}Error: jq is required but not installed.${NC}" >&2
    exit 1
fi

if ! command -v bc >/dev/null 2>&1; then
    echo -e "${RED}Error: bc is required but not installed.${NC}" >&2
    exit 1
fi

# Run main function
main "$@"
