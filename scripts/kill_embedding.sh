#!/usr/bin/env bash
# Kill embedding processes script
# Safely stops all running embedding workers and processes

set -euo pipefail

# Ensure no pagers trigger
export PAGER=cat
export LESS=-RFX

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🛑 Embedding Process Killer${NC}"
echo "============================="

# Function to find and kill embedding processes
kill_embedding_processes() {
    local killed_count=0
    
    echo "🔍 Searching for embedding processes..."
    
    # Find Python processes with embedding-related commands
    local pids=()
    
    # Look for trailblazer embed commands
    while IFS= read -r line; do
        if [[ -n "${line}" ]]; then
            pids+=("${line}")
        fi
    done < <(pgrep -f "trailblazer.*embed" 2>/dev/null || true)
    
    # Look for Python processes with embedding in command line
    while IFS= read -r line; do
        if [[ -n "${line}" ]]; then
            pids+=("${line}")
        fi
    done < <(pgrep -f "python.*embed" 2>/dev/null || true)
    
    # Look for worker processes
    while IFS= read -r line; do
        if [[ -n "${line}" ]]; then
            pids+=("${line}")
        fi
    done < <(pgrep -f "embed_worker" 2>/dev/null || true)
    
    # Remove duplicates
    local unique_pids=()
    for pid in "${pids[@]}"; do
        if [[ ! " ${unique_pids[*]} " =~ " ${pid} " ]]; then
            unique_pids+=("${pid}")
        fi
    done
    
    if [[ ${#unique_pids[@]} -eq 0 ]]; then
        echo -e "${GREEN}✅ No embedding processes found${NC}"
        return 0
    fi
    
    echo "📋 Found ${#unique_pids[@]} embedding process(es):"
    
    # Show process details before killing
    for pid in "${unique_pids[@]}"; do
        if kill -0 "${pid}" 2>/dev/null; then
            local cmdline
            cmdline=$(ps -p "${pid}" -o args= 2>/dev/null || echo "Unknown")
            echo "  PID ${pid}: ${cmdline}"
        fi
    done
    
    echo
    echo -e "${YELLOW}⚠️  Stopping embedding processes...${NC}"
    
    # Kill processes gracefully first
    for pid in "${unique_pids[@]}"; do
        if kill -0 "${pid}" 2>/dev/null; then
            echo "🔄 Sending SIGTERM to PID ${pid}..."
            if kill -TERM "${pid}" 2>/dev/null; then
                killed_count=$((killed_count + 1))
            fi
        fi
    done
    
    # Wait a moment for graceful shutdown
    if [[ ${killed_count} -gt 0 ]]; then
        echo "⏳ Waiting for graceful shutdown..."
        sleep 3
        
        # Check if any processes are still running
        local still_running=()
        for pid in "${unique_pids[@]}"; do
            if kill -0 "${pid}" 2>/dev/null; then
                still_running+=("${pid}")
            fi
        done
        
        # Force kill if necessary
        if [[ ${#still_running[@]} -gt 0 ]]; then
            echo -e "${YELLOW}⚠️  Some processes still running, sending SIGKILL...${NC}"
            for pid in "${still_running[@]}"; do
                echo "💀 Force killing PID ${pid}..."
                kill -KILL "${pid}" 2>/dev/null || true
            done
        fi
    fi
    
    echo -e "${GREEN}✅ Stopped ${killed_count} embedding process(es)${NC}"
}

# Function to clean up worker directories
cleanup_worker_dirs() {
    echo
    echo "🧹 Cleaning up worker directories..."
    
    local worker_dirs=()
    while IFS= read -r dir; do
        if [[ -n "${dir}" ]]; then
            worker_dirs+=("${dir}")
        fi
    done < <(find var/tmp -maxdepth 1 -type d -name "embed_worker_*" 2>/dev/null || true)
    
    if [[ ${#worker_dirs[@]} -eq 0 ]]; then
        echo "✅ No worker directories to clean up"
        return 0
    fi
    
    echo "📁 Found ${#worker_dirs[@]} worker directory(ies):"
    for dir in "${worker_dirs[@]}"; do
        echo "  ${dir}"
    done
    
    # Archive worker logs instead of deleting
    local archive_dir="var/logs/_archive/$(date -u +%Y%m%dT%H%M%SZ)_workers"
    mkdir -p "${archive_dir}"
    
    for dir in "${worker_dirs[@]}"; do
        if [[ -d "${dir}" ]]; then
            local dirname
            dirname=$(basename "${dir}")
            echo "📦 Archiving ${dirname}..."
            mv "${dir}" "${archive_dir}/" 2>/dev/null || echo "  ⚠️  Could not archive ${dirname}"
        fi
    done
    
    echo -e "${GREEN}✅ Worker directories archived to ${archive_dir}${NC}"
}

# Function to check for any remaining embedding processes
check_remaining() {
    echo
    echo "🔍 Checking for remaining embedding processes..."
    
    local remaining_pids=()
    
    # Check for any remaining embedding processes
    while IFS= read -r line; do
        if [[ -n "${line}" ]]; then
            remaining_pids+=("${line}")
        fi
    done < <(pgrep -f "trailblazer.*embed\|python.*embed\|embed_worker" 2>/dev/null || true)
    
    if [[ ${#remaining_pids[@]} -eq 0 ]]; then
        echo -e "${GREEN}✅ No embedding processes remaining${NC}"
    else
        echo -e "${YELLOW}⚠️  ${#remaining_pids[@]} embedding process(es) still running:${NC}"
        for pid in "${remaining_pids[@]}"; do
            local cmdline
            cmdline=$(ps -p "${pid}" -o args= 2>/dev/null || echo "Unknown")
            echo "  PID ${pid}: ${cmdline}"
        done
        echo -e "${YELLOW}⚠️  You may need to manually kill these processes${NC}"
    fi
}

# Main execution
main() {
    echo "🚀 Starting embedding process cleanup..."
    
    # Kill embedding processes
    kill_embedding_processes
    
    # Clean up worker directories
    cleanup_worker_dirs
    
    # Check for remaining processes
    check_remaining
    
    echo
    echo -e "${GREEN}🎉 Embedding cleanup completed!${NC}"
    echo
    echo "📋 Summary:"
    echo "  • Stopped embedding processes"
    echo "  • Archived worker directories"
    echo "  • Verified cleanup completion"
    echo
    echo "💡 To restart embedding, use:"
    echo "  make reembed.openai"
    echo "  or"
    echo "  bash scripts/embed_dispatch.sh <runs_file>"
}

# Run main function
main "$@"
