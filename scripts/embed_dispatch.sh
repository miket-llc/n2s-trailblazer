#!/usr/bin/env bash
# Embed dispatch script - orchestrates embedding runs with worker management
# Usage: ./embed_dispatch.sh [OPTIONS]

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

# Default values
WORKERS="${WORKERS:-2}"
PLAN_PREFLIGHT_DIR=""
PLAN_FILE=""
QA_DIR=""
SKIP_UNCHANGED=false
NOTES=""
RUNS_FILE=""

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --plan-preflight-dir)
            PLAN_PREFLIGHT_DIR="$2"
            shift 2
            ;;
        --plan-file)
            PLAN_FILE="$2"
            shift 2
            ;;
        --qa-dir)
            QA_DIR="$2"
            shift 2
            ;;
        --skip-unchanged)
            SKIP_UNCHANGED=true
            shift
            ;;
        --notes)
            NOTES="$2"
            shift 2
            ;;
        --workers)
            WORKERS="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo
            echo "Options:"
            echo "  --plan-preflight-dir <DIR>  Use plan from <DIR>/ready.txt"
            echo "  --plan-file <FILE>          Use specific plan file"
            echo "  --qa-dir <DIR>              Archive QA results from directory"
            echo "  --skip-unchanged            Use reembed-if-changed to skip unchanged runs"
            echo "  --notes \"<TEXT>\"            Add operator notes to manifest"
            echo "  --workers <N>               Number of parallel workers (default: 2)"
            echo "  --help                      Show this help"
            echo
            echo "Plan resolution order:"
            echo "  1. --plan-preflight-dir if provided → use <DIR>/ready.txt"
            echo "  2. --plan-file if provided → use it"
            echo "  3. Auto-pick latest var/plan_preflight/<TS>/ready.txt if available"
            echo "  4. Fall back to var/temp_runs_to_embed.txt"
            echo
            echo "Examples:"
            echo "  $0 --plan-preflight-dir var/plan_preflight/20250118_143022/"
            echo "  $0 --plan-file my_plan.txt --skip-unchanged"
            echo "  $0 --qa-dir var/retrieval_qc/20250118_143022/ --notes \"Production deployment\""
            exit 0
            ;;
        *)
            # For backward compatibility, treat first positional arg as runs file
            if [[ -z "$RUNS_FILE" && ! "$1" =~ ^-- ]]; then
                RUNS_FILE="$1"
                shift
            else
                echo -e "${RED}❌ Error: Unknown option '$1'${NC}"
                exit 1
            fi
            ;;
    esac
done

# Plan source resolution
SELECTED_PLAN_FILE=""
PLAN_PREFLIGHT_SOURCE_DIR=""

# 1. If --plan-preflight-dir provided, use <DIR>/ready.txt
if [[ -n "$PLAN_PREFLIGHT_DIR" ]]; then
    if [[ ! -d "$PLAN_PREFLIGHT_DIR" ]]; then
        echo -e "${RED}❌ Error: Plan preflight directory '${PLAN_PREFLIGHT_DIR}' not found${NC}"
        exit 1
    fi
    READY_FILE="${PLAN_PREFLIGHT_DIR}/ready.txt"
    if [[ ! -f "$READY_FILE" ]]; then
        echo -e "${RED}❌ Error: ready.txt not found in '${PLAN_PREFLIGHT_DIR}'${NC}"
        exit 1
    fi
    SELECTED_PLAN_FILE="$READY_FILE"
    PLAN_PREFLIGHT_SOURCE_DIR="$PLAN_PREFLIGHT_DIR"

# 2. Else if --plan-file provided, use it
elif [[ -n "$PLAN_FILE" ]]; then
    if [[ ! -f "$PLAN_FILE" ]]; then
        echo -e "${RED}❌ Error: Plan file '${PLAN_FILE}' not found${NC}"
        exit 1
    fi
    SELECTED_PLAN_FILE="$PLAN_FILE"

# 3. Backward compatibility: if RUNS_FILE set, use it
elif [[ -n "$RUNS_FILE" ]]; then
    if [[ ! -f "$RUNS_FILE" ]]; then
        echo -e "${RED}❌ Error: Runs file '${RUNS_FILE}' not found${NC}"
        exit 1
    fi
    SELECTED_PLAN_FILE="$RUNS_FILE"

# 4. Auto-pick latest var/plan_preflight/<TS>/ready.txt if available
else
    LATEST_PREFLIGHT_DIR=$(find var/plan_preflight/ -maxdepth 1 -type d -name "20*" 2>/dev/null | sort -r | head -n1)
    if [[ -n "$LATEST_PREFLIGHT_DIR" && -f "${LATEST_PREFLIGHT_DIR}/ready.txt" ]]; then
        SELECTED_PLAN_FILE="${LATEST_PREFLIGHT_DIR}/ready.txt"
        PLAN_PREFLIGHT_SOURCE_DIR="$LATEST_PREFLIGHT_DIR"
        echo -e "${YELLOW}ℹ️  Auto-selected latest plan-preflight: ${LATEST_PREFLIGHT_DIR}${NC}"
    # 5. Fall back to var/temp_runs_to_embed.txt
    else
        FALLBACK_FILE="var/temp_runs_to_embed.txt"
        if [[ ! -f "$FALLBACK_FILE" ]]; then
            echo -e "${RED}❌ Error: No plan found. Options:${NC}"
            echo "  1. Use --plan-preflight-dir <DIR> (expects <DIR>/ready.txt)"
            echo "  2. Use --plan-file <FILE>"
            echo "  3. Create var/temp_runs_to_embed.txt"
            echo "  4. Run 'trailblazer embed plan-preflight' to create a plan"
            exit 1
        fi
        SELECTED_PLAN_FILE="$FALLBACK_FILE"
    fi
fi

# Validate selected plan file has content
if [[ ! -s "$SELECTED_PLAN_FILE" ]]; then
    echo -e "${RED}❌ Error: Selected plan file '${SELECTED_PLAN_FILE}' is empty${NC}"
    exit 1
fi

# Count runs in plan
PLAN_RUN_COUNT=$(grep -v '^#' "$SELECTED_PLAN_FILE" | grep -v '^[[:space:]]*$' | wc -l | tr -d ' ')

# Print green confirmation
echo -e "${GREEN}✅ Using plan: ${SELECTED_PLAN_FILE} (planned: ${PLAN_RUN_COUNT})${NC}"

# If plan-preflight was used, show additional info
if [[ -n "$PLAN_PREFLIGHT_SOURCE_DIR" ]]; then
    PLAN_JSON="${PLAN_PREFLIGHT_SOURCE_DIR}/plan_preflight.json"
    if [[ -f "$PLAN_JSON" ]]; then
        # Extract summary info from JSON using basic tools (avoid jq dependency)
        READY_COUNT=$(grep -o '"runsReady":[0-9]*' "$PLAN_JSON" 2>/dev/null | cut -d: -f2 || echo "0")
        BLOCKED_COUNT=$(grep -o '"runsBlocked":[0-9]*' "$PLAN_JSON" 2>/dev/null | cut -d: -f2 || echo "0")
        EST_TOKENS=$(grep -o '"tokens":[0-9]*' "$PLAN_JSON" 2>/dev/null | cut -d: -f2 || echo "0")
        EST_COST=$(grep -o '"estCostUSD":[0-9.]*' "$PLAN_JSON" 2>/dev/null | cut -d: -f2 || echo "0")

        echo "  Plan totals: ready=${READY_COUNT}, blocked=${BLOCKED_COUNT}"
        if [[ "$EST_TOKENS" != "0" ]]; then
            echo "  Estimates: ${EST_TOKENS} tokens"
            if [[ "$EST_COST" != "0" ]]; then
                echo "  Estimated cost: \$${EST_COST} USD"
            fi
        fi
    fi
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

# Create dispatch timestamp and log directory
DISPATCH_TS=$(date -u +"%Y%m%d_%H%M%S")
DISPATCH_LOG_DIR="var/logs/dispatch/${DISPATCH_TS}"
mkdir -p "${DISPATCH_LOG_DIR}"

echo "📁 Dispatch logs: ${DISPATCH_LOG_DIR}"

# Archive plan-preflight bundle if used
if [[ -n "$PLAN_PREFLIGHT_SOURCE_DIR" ]]; then
    echo "📦 Archiving plan-preflight bundle..."
    cp -r "$PLAN_PREFLIGHT_SOURCE_DIR" "${DISPATCH_LOG_DIR}/plan_preflight/"
    echo "  Archived: ${PLAN_PREFLIGHT_SOURCE_DIR} → ${DISPATCH_LOG_DIR}/plan_preflight/"
fi

# Archive QA directory if provided
if [[ -n "$QA_DIR" ]]; then
    if [[ -d "$QA_DIR" ]]; then
        echo "📦 Archiving QA results..."
        cp -r "$QA_DIR" "${DISPATCH_LOG_DIR}/retrieval_qc/"
        echo "  Archived: ${QA_DIR} → ${DISPATCH_LOG_DIR}/retrieval_qc/"
    else
        echo -e "${YELLOW}⚠️  Warning: QA directory '${QA_DIR}' not found, skipping archive${NC}"
        QA_DIR=""  # Clear it so manifest shows null
    fi
fi

# Resolve provider/model/dimension from environment or defaults
RESOLVED_PROVIDER="${TRAILBLAZER_EMBED_PROVIDER:-openai}"
RESOLVED_MODEL="${TRAILBLAZER_EMBED_MODEL:-text-embedding-3-small}"
RESOLVED_DIMENSION="${TRAILBLAZER_EMBED_DIMENSIONS:-1536}"
RESOLVED_BATCH_SIZE="${BATCH_SIZE:-128}"

# Get git commit if available
GIT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "null")

# Determine mode
if [[ "$SKIP_UNCHANGED" == "true" ]]; then
    MODE="reembed-if-changed"
else
    MODE="embed"
fi

# Create dispatch_manifest.json
MANIFEST_FILE="${DISPATCH_LOG_DIR}/dispatch_manifest.json"
cat > "$MANIFEST_FILE" <<EOF
{
  "dispatchTs": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "planPreflightDir": $(if [[ -n "$PLAN_PREFLIGHT_SOURCE_DIR" ]]; then echo "\"${PLAN_PREFLIGHT_SOURCE_DIR}\""; else echo "null"; fi),
  "planFileUsed": "${SELECTED_PLAN_FILE}",
  "runsPlanned": ${PLAN_RUN_COUNT},
  "provider": "${RESOLVED_PROVIDER}",
  "model": "${RESOLVED_MODEL}",
  "dimension": ${RESOLVED_DIMENSION},
  "workers": ${WORKERS},
  "batchSize": ${RESOLVED_BATCH_SIZE},
  "gitCommit": $(if [[ "$GIT_COMMIT" != "null" ]]; then echo "\"${GIT_COMMIT}\""; else echo "null"; fi),
  "qaDir": $(if [[ -n "$QA_DIR" ]]; then echo "\"${QA_DIR}\""; else echo "null"; fi),
  "notes": "${NOTES}",
  "mode": "${MODE}"
}
EOF

echo "📄 Created dispatch manifest: ${MANIFEST_FILE}"

# Read and validate runs with preflight checks
RUNS=()
TOTAL_CHUNKS=0
DISPATCHER_LOG="${DISPATCH_LOG_DIR}/dispatcher.out"

# Initialize counters early
QUEUED_COUNT=0
SKIPPED_PREFLIGHT_COUNT=0
SKIPPED_UNCHANGED_COUNT=0
ERROR_COUNT=0

while IFS= read -r run_id; do
    # Skip empty lines and comments
    if [[ -z "$run_id" || "$run_id" =~ ^[[:space:]]*# ]]; then
        continue
    fi
    
    # Remove any trailing colon and chunk count if present
    run_id="${run_id%%:*}"

    # Validate run directory exists
    if [[ ! -d "var/runs/${run_id}" ]]; then
        echo -e "${YELLOW}⚠️  Warning: Run directory 'var/runs/${run_id}' not found${NC}"
        continue
    fi

    # Count actual chunks from chunk file
    chunk_count=0
    if [[ -f "var/runs/${run_id}/chunk/chunks.ndjson" ]]; then
        chunk_count=$(wc -l < "var/runs/${run_id}/chunk/chunks.ndjson" 2>/dev/null || echo 0)
    fi

    # Always run per-RID preflight check for safety
    echo "🔍 Running preflight check for ${run_id}..."
    if trailblazer embed preflight "${run_id}" --provider "${RESOLVED_PROVIDER}" --model "${RESOLVED_MODEL}" --dim "${RESOLVED_DIMENSION}" >/dev/null 2>&1; then
        RUNS+=("${run_id}:${chunk_count}")
        TOTAL_CHUNKS=$((TOTAL_CHUNKS + chunk_count))
        echo "✅ Run: ${run_id} (${chunk_count} chunks) - preflight passed"
    else
        # Log preflight failure to dispatcher.out
        preflight_json="var/runs/${run_id}/preflight/preflight.json"
        if [[ -f "${preflight_json}" ]]; then
            echo -e "${RED}❌ SKIPPED RID ${run_id}: preflight failed - see ${preflight_json}${NC}" | tee -a "${DISPATCHER_LOG}"
        else
            echo -e "${RED}❌ SKIPPED RID ${run_id}: preflight failed - no preflight.json generated${NC}" | tee -a "${DISPATCHER_LOG}"
        fi
        SKIPPED_PREFLIGHT_COUNT=$((SKIPPED_PREFLIGHT_COUNT + 1))
    fi
done < "${SELECTED_PLAN_FILE}"

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

# Global counters for final summary (initialized earlier)

# Function to process a run
process_run() {
    local run_info="$1"
    local worker_id="$2"
    local run_id="${run_info%:*}"
    local chunk_count="${run_info#*:}"

    local worker_log="${WORKER_DIRS[worker_id-1]}/worker_${worker_id}.log"

    echo "[Worker ${worker_id}] 🚀 Processing run: ${run_id}" | tee -a "${worker_log}"

    # Check if run is already processed (only for regular embed mode)
    if [[ "$SKIP_UNCHANGED" != "true" && -f "var/runs/${run_id}/embed/embed_assurance.json" ]]; then
        echo "[Worker ${worker_id}] ✅ Run ${run_id} already embedded, skipping" | tee -a "${worker_log}"
        return 0
    fi

    # Capture worker environment before starting embed process
    local embed_pid=$$
    local timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    local env_file="var/logs/embed_env.${embed_pid}.json"
    cat > "${env_file}" <<EOF
{
  "pid": ${embed_pid},
  "provider": "${RESOLVED_PROVIDER}",
  "model": "${RESOLVED_MODEL}",
  "dimension": ${RESOLVED_DIMENSION},
  "batch_size": ${RESOLVED_BATCH_SIZE},
  "workers": ${WORKERS},
  "timestamp": "${timestamp}",
  "rid": "${run_id}"
}
EOF

    # Process the run
    local start_time=$(date +%s)

    if [[ "$SKIP_UNCHANGED" == "true" ]]; then
        # Use reembed-if-changed mode
        echo "[Worker ${worker_id}] 🔄 Using reembed-if-changed for ${run_id}" | tee -a "${worker_log}"

        if trailblazer embed reembed-if-changed "${run_id}" --provider "${RESOLVED_PROVIDER}" --model "${RESOLVED_MODEL}" --dimension "${RESOLVED_DIMENSION}" --batch "${RESOLVED_BATCH_SIZE}" 2>&1 | tee -a "${worker_log}"; then
            local end_time=$(date +%s)
            local duration=$((end_time - start_time))

            # Check if it was skipped due to no changes (look for specific message in output)
            if grep -q "No changes detected, skipping embedding" "${worker_log}"; then
                echo "[Worker ${worker_id}] ⏭️  Run ${run_id} skipped (unchanged) in ${duration}s" | tee -a "${worker_log}"
                echo "⏭️  SKIPPED RID ${run_id}: unchanged, worker ${worker_id} completed in ${duration}s" >> "${DISPATCHER_LOG}"
                SKIPPED_UNCHANGED_COUNT=$((SKIPPED_UNCHANGED_COUNT + 1))
                return 0
            else
                echo "[Worker ${worker_id}] ✅ Run ${run_id} completed in ${duration}s" | tee -a "${worker_log}"
                echo "✅ QUEUED RID ${run_id}: preflight passed, worker ${worker_id} completed in ${duration}s" >> "${DISPATCHER_LOG}"
                QUEUED_COUNT=$((QUEUED_COUNT + 1))
                return 0
            fi
        else
            local end_time=$(date +%s)
            local duration=$((end_time - start_time))
            echo "[Worker ${worker_id}] ❌ Run ${run_id} failed after ${duration}s" | tee -a "${worker_log}"
            echo "❌ ERROR RID ${run_id}: reembed-if-changed failed, worker ${worker_id} after ${duration}s" >> "${DISPATCHER_LOG}"
            ERROR_COUNT=$((ERROR_COUNT + 1))
            return 1
        fi
    else
        # Use regular embed mode
        if trailblazer embed load --run-id "${run_id}" --provider "${RESOLVED_PROVIDER}" --model "${RESOLVED_MODEL}" --dimensions "${RESOLVED_DIMENSION}" --batch "${RESOLVED_BATCH_SIZE}"; then
            local end_time=$(date +%s)
            local duration=$((end_time - start_time))
            echo "[Worker ${worker_id}] ✅ Run ${run_id} completed in ${duration}s" | tee -a "${worker_log}"
            echo "✅ QUEUED RID ${run_id}: preflight passed, worker ${worker_id} completed in ${duration}s" >> "${DISPATCHER_LOG}"
            QUEUED_COUNT=$((QUEUED_COUNT + 1))
            return 0
        else
            local end_time=$(date +%s)
            local duration=$((end_time - start_time))
            echo "[Worker ${worker_id}] ❌ Run ${run_id} failed after ${duration}s" | tee -a "${worker_log}"
            echo "❌ ERROR RID ${run_id}: embed failed, worker ${worker_id} after ${duration}s" >> "${DISPATCHER_LOG}"
            ERROR_COUNT=$((ERROR_COUNT + 1))
            return 1
        fi
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
echo "Queued: ${QUEUED_COUNT}, Skipped (preflight): ${SKIPPED_PREFLIGHT_COUNT}, Skipped (unchanged): ${SKIPPED_UNCHANGED_COUNT}, Errors: ${ERROR_COUNT}"
echo

# Show dispatch artifacts
echo "📄 Dispatch artifacts:"
echo "  Manifest: ${MANIFEST_FILE}"
if [[ -n "$PLAN_PREFLIGHT_SOURCE_DIR" ]]; then
    echo "  Archived plan-preflight: ${DISPATCH_LOG_DIR}/plan_preflight/"
fi
if [[ -n "$QA_DIR" && -d "${DISPATCH_LOG_DIR}/retrieval_qc/" ]]; then
    echo "  Archived QA results: ${DISPATCH_LOG_DIR}/retrieval_qc/"
fi
echo "  Dispatcher log: ${DISPATCHER_LOG}"

echo
echo "🔍 Check individual worker logs in:"
for worker_dir in "${WORKER_DIRS[@]}"; do
    echo "  ${worker_dir}/"
done

echo
echo "✅ Embedding dispatch completed!"
