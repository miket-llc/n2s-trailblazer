#!/usr/bin/env bash
# Embed dispatch script - orchestrates embedding runs with worker management
# Usage: ./embed_dispatch.sh <runs_file> [WORKERS=N]

set -euo pipefail

# Ensure no pagers trigger
export PAGER=cat
export LESS=-RFX

# Create logs directory if it doesn't exist
mkdir -p var/logs

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🚀 Embed Dispatch Script${NC}"
echo "========================"

# Check if runs file was provided
if [[ $# -eq 0 ]]; then
    echo -e "${RED}❌ Error: No runs file specified${NC}"
    echo
    echo "Usage: $0 <runs_file> [WORKERS=N]"
    echo "Example: $0 var/temp_runs_to_embed.txt WORKERS=3"
    echo
    echo "The runs file should contain one run ID per line, optionally with chunk counts:"
    echo "  run_id_1:1000"
    echo "  run_id_2:500"
    echo
    exit 1
fi

RUNS_FILE="$1"
WORKERS="${WORKERS:-2}"

# Validate runs file
if [[ ! -f "${RUNS_FILE}" ]]; then
    echo -e "${RED}❌ Error: Runs file '${RUNS_FILE}' not found${NC}"
    exit 1
fi

# Check if .env exists and source it
if [[ -f .env ]]; then
    set -a
    source .env
    set +a
    echo "📊 Environment loaded from .env"
else
    echo -e "${YELLOW}⚠️  Warning: .env file not found${NC}"
fi

# Validate TRAILBLAZER_DB_URL
if [[ -z "${TRAILBLAZER_DB_URL:-}" ]]; then
    echo -e "${RED}❌ Error: TRAILBLAZER_DB_URL not set${NC}"
    echo "Please set TRAILBLAZER_DB_URL in your .env file or environment"
    exit 1
fi

echo "🔌 Database: ${TRAILBLAZER_DB_URL//*@/***@}"
echo "👥 Workers: ${WORKERS}"

# Read and validate runs with preflight checks
RUNS=()
TOTAL_CHUNKS=0
DISPATCHER_LOG="var/logs/dispatcher.out"

while IFS=':' read -r run_id chunk_count; do
    # Handle lines without chunk counts
    if [[ -z "${chunk_count:-}" ]]; then
        chunk_count=0
    fi

    # Validate run directory exists
    if [[ ! -d "var/runs/${run_id}" ]]; then
        echo -e "${YELLOW}⚠️  Warning: Run directory 'var/runs/${run_id}' not found${NC}"
        continue
    fi

    # Run preflight check before enqueuing
    echo "🔍 Running preflight check for ${run_id}..."
    if trailblazer embed preflight --run "${run_id}" --provider openai --model text-embedding-3-small --dim 1536 >/dev/null 2>&1; then
        RUNS+=("${run_id}:${chunk_count}")
        TOTAL_CHUNKS=$((TOTAL_CHUNKS + chunk_count))
        echo "✅ Run: ${run_id} (${chunk_count} chunks) - preflight passed"
    else
        # Log preflight failure to dispatcher.out
        local preflight_json="var/runs/${run_id}/preflight/preflight.json"
        if [[ -f "${preflight_json}" ]]; then
            echo -e "${RED}❌ SKIPPED RID ${run_id}: preflight failed - see ${preflight_json}${NC}" | tee -a "${DISPATCHER_LOG}"
        else
            echo -e "${RED}❌ SKIPPED RID ${run_id}: preflight failed - no preflight.json generated${NC}" | tee -a "${DISPATCHER_LOG}"
        fi
    fi
done < "${RUNS_FILE}"

if [[ ${#RUNS[@]} -eq 0 ]]; then
    echo -e "${RED}❌ Error: No valid runs found${NC}"
    exit 1
fi

echo
echo "📊 Summary:"
echo "  Total runs: ${#RUNS[@]}"
echo "  Total chunks: ${TOTAL_CHUNKS}"
echo "  Workers: ${WORKERS}"

# Check if database is accessible
echo
echo "🔍 Checking database connectivity..."
if ! trailblazer db doctor >/dev/null 2>&1; then
    echo -e "${RED}❌ Error: Database not accessible${NC}"
    echo "Run 'make db.up' and 'trailblazer db doctor' to check database health"
    exit 1
fi
echo -e "${GREEN}✅ Database accessible${NC}"

# Create worker directories
WORKER_DIRS=()
for i in $(seq 1 "${WORKERS}"); do
    WORKER_DIR="var/tmp/embed_worker_${i}"
    mkdir -p "${WORKER_DIR}"
    WORKER_DIRS+=("${WORKER_DIR}")
done

echo
echo "👥 Starting ${WORKERS} embedding workers..."

# Function to process a run
process_run() {
    local run_info="$1"
    local worker_id="$2"
    local run_id="${run_info%:*}"
    local chunk_count="${run_info#*:}"

    local worker_log="${WORKER_DIRS[worker_id-1]}/worker_${worker_id}.log"

    echo "[Worker ${worker_id}] 🚀 Processing run: ${run_id}" | tee -a "${worker_log}"

    # Check if run is already processed
    if [[ -f "var/runs/${run_id}/embed/embed_assurance.json" ]]; then
        echo "[Worker ${worker_id}] ✅ Run ${run_id} already embedded, skipping" | tee -a "${worker_log}"
        return 0
    fi

    # Capture worker environment before starting embed process
    local embed_pid=$$
    local resolved_batch=128
    local resolved_workers="${WORKERS}"
    local timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    local env_file="var/logs/embed_env.${embed_pid}.json"
    cat > "${env_file}" <<EOF
{
  "pid": ${embed_pid},
  "provider": "openai",
  "model": "text-embedding-3-small",
  "dimension": 1536,
  "batch_size": ${resolved_batch},
  "workers": ${resolved_workers},
  "timestamp": "${timestamp}",
  "rid": "${run_id}"
}
EOF

    # Process the run
    local start_time=$(date +%s)

    if trailblazer embed load --run-id "${run_id}" --provider openai --model text-embedding-3-small --dimensions 1536 --batch 128; then
        local end_time=$(date +%s)
        local duration=$((end_time - start_time))
        echo "[Worker ${worker_id}] ✅ Run ${run_id} completed in ${duration}s" | tee -a "${worker_log}"
        # Log successful enqueue to dispatcher.out
        echo "✅ ENQUEUED RID ${run_id}: preflight passed, worker ${worker_id} completed in ${duration}s" >> "${DISPATCHER_LOG}"
        return 0
    else
        local end_time=$(date +%s)
        local duration=$((end_time - start_time))
        echo "[Worker ${worker_id}] ❌ Run ${run_id} failed after ${duration}s" | tee -a "${worker_log}"
        return 1
    fi
}

# Distribute runs among workers
declare -A WORKER_QUEUES
for i in $(seq 1 "${WORKERS}"); do
    WORKER_QUEUES[$i]=""
done

# Simple round-robin distribution
worker_idx=1
for run_info in "${RUNS[@]}"; do
    if [[ -z "${WORKER_QUEUES[$worker_idx]}" ]]; then
        WORKER_QUEUES[$worker_idx]="${run_info}"
    else
        WORKER_QUEUES[$worker_idx]="${WORKER_QUEUES[$worker_idx]} ${run_info}"
    fi
    worker_idx=$((worker_idx % WORKERS + 1))
done

# Start workers
PIDS=()
for i in $(seq 1 "${WORKERS}"); do
    if [[ -n "${WORKER_QUEUES[$i]}" ]]; then
        (
            for run_info in ${WORKER_QUEUES[$i]}; do
                process_run "${run_info}" "${i}"
            done
        ) &
        PIDS+=($!)
        echo "👷 Worker ${i} started (PID: $!)"
    fi
done

# Wait for all workers to complete
echo
echo "⏳ Waiting for all workers to complete..."
for pid in "${PIDS[@]}"; do
    wait "${pid}"
done

echo
echo -e "${GREEN}🎉 All workers completed!${NC}"

# Show summary
echo
echo "📊 Final Summary:"
echo "================="
for i in $(seq 1 "${WORKERS}"); do
    if [[ -n "${WORKER_QUEUES[$i]}" ]]; then
        worker_log="${WORKER_DIRS[i-1]}/worker_${i}.log"
        if [[ -f "${worker_log}" ]]; then
            echo "👷 Worker ${i}:"
            tail -5 "${worker_log}" | sed 's/^/  /'
        fi
    fi
done

echo
echo "🔍 Check individual worker logs in:"
for worker_dir in "${WORKER_DIRS[@]}"; do
    echo "  ${worker_dir}/"
done

echo
echo "✅ Embedding dispatch completed!"
