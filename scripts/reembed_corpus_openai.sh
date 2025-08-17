#!/usr/bin/env bash
# OpenAI Corpus Re-embedding Script
# Orchestrates re-embedding of the entire corpus using OpenAI

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

echo -e "${BLUE}🚀 OpenAI Corpus Re-embedding Script${NC}"
echo "====================================="

# Check if .env exists and source it
if [[ -f .env ]]; then
    set -a
    source .env
    set +a
    echo "📊 Environment loaded from .env"
else
    echo -e "${RED}❌ Error: .env file not found${NC}"
    echo "Please create .env file with required environment variables"
    exit 1
fi

# Validate required environment variables
if [[ -z "${TRAILBLAZER_DB_URL:-}" ]]; then
    echo -e "${RED}❌ Error: TRAILBLAZER_DB_URL not set in .env${NC}"
    exit 1
fi

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
    echo -e "${RED}❌ Error: OPENAI_API_KEY not set in .env${NC}"
    exit 1
fi

# Check for list-only mode
if [[ "${1:-}" == "--list-only" ]]; then
    echo -e "${YELLOW}📋 List-only mode - showing available runs${NC}"
    echo
    
    # Find all normalized runs
    if [[ ! -d var/runs ]]; then
        echo "❌ No runs directory found"
        exit 1
    fi
    
    echo "📁 Available normalized runs:"
    echo "=============================="
    
    total_runs=0
    total_chunks=0
    
    for run_dir in var/runs/*/; do
        if [[ -d "${run_dir}" ]]; then
            run_id=$(basename "${run_dir}")
            normalized_file="${run_dir}normalize/normalized.ndjson"
            chunks_file="${run_dir}chunk/chunks.ndjson"
            
            if [[ -f "${normalized_file}" ]]; then
                # Count chunks if available
                chunk_count=0
                if [[ -f "${chunks_file}" ]]; then
                    chunk_count=$(wc -l < "${chunks_file}" 2>/dev/null || echo "0")
                fi
                
                # Check if already embedded
                embedded_marker=""
                if [[ -f "${run_dir}embed/embed_assurance.json" ]]; then
                    embedded_marker=" ✅"
                fi
                
                echo "  ${run_id}${embedded_marker} (${chunk_count} chunks)"
                total_runs=$((total_runs + 1))
                total_chunks=$((total_chunks + chunk_count))
            fi
        fi
    done
    
    echo
    echo "📊 Summary:"
    echo "  Total runs: ${total_runs}"
    echo "  Total chunks: ${total_chunks}"
    echo
    echo "💡 To re-embed all runs:"
    echo "  make reembed.openai.all"
    echo
    echo "💡 To re-embed specific runs:"
    echo "  bash scripts/embed_dispatch.sh <runs_file>"
    echo
    exit 0
fi

echo "🔌 Database: ${TRAILBLAZER_DB_URL//*@/***@}"
echo "🤖 Provider: OpenAI"
echo "🔑 API Key: ${OPENAI_API_KEY:0:8}...${OPENAI_API_KEY: -4}"

# Check if database is accessible
echo
echo "🔍 Checking database connectivity..."
if ! trailblazer db doctor >/dev/null 2>&1; then
    echo -e "${RED}❌ Error: Database not accessible${NC}"
    echo "Run 'make db.up' and 'trailblazer db doctor' to check database health"
    exit 1
fi
echo -e "${GREEN}✅ Database accessible${NC}"

# Check if any runs exist
if [[ ! -d var/runs ]] || [[ -z "$(ls -A var/runs 2>/dev/null)" ]]; then
    echo -e "${RED}❌ Error: No runs directory or no runs found${NC}"
    echo "Run ingestion first: trailblazer ingest confluence"
    exit 1
fi

# Find normalized runs
echo
echo "🔍 Scanning for normalized runs..."
NORMALIZED_RUNS=()
TOTAL_CHUNKS=0

for run_dir in var/runs/*/; do
    if [[ -d "${run_dir}" ]]; then
        run_id=$(basename "${run_dir}")
        normalized_file="${run_dir}normalize/normalized.ndjson"
        
        if [[ -f "${normalized_file}" ]]; then
            # Count chunks
            chunks_file="${run_dir}chunk/chunks.ndjson"
            chunk_count=0
            if [[ -f "${chunks_file}" ]]; then
                chunk_count=$(wc -l < "${chunks_file}" 2>/dev/null || echo "0")
            fi
            
            NORMALIZED_RUNS+=("${run_id}:${chunk_count}")
            TOTAL_CHUNKS=$((TOTAL_CHUNKS + chunk_count))
            echo "✅ ${run_id} (${chunk_count} chunks)"
        fi
    fi
done

if [[ ${#NORMALIZED_RUNS[@]} -eq 0 ]]; then
    echo -e "${RED}❌ Error: No normalized runs found${NC}"
    echo "Run normalization first: trailblazer normalize from-ingest"
    exit 1
fi

echo
echo "📊 Found ${#NORMALIZED_RUNS[@]} normalized runs with ${TOTAL_CHUNKS} total chunks"

# Check for existing embeddings
echo
echo "🔍 Checking existing embeddings..."
EMBEDDED_RUNS=()
UNEMBEDDED_RUNS=()

for run_info in "${NORMALIZED_RUNS[@]}"; do
    run_id="${run_info%:*}"
    chunk_count="${run_info#*:}"
    
    if [[ -f "var/runs/${run_id}/embed/embed_assurance.json" ]]; then
        EMBEDDED_RUNS+=("${run_info}")
        echo "✅ ${run_id} (already embedded)"
    else
        UNEMBEDDED_RUNS+=("${run_info}")
        echo "⏳ ${run_id} (needs embedding)"
    fi
done

echo
echo "📊 Embedding Status:"
echo "  Already embedded: ${#EMBEDDED_RUNS[@]} runs"
echo "  Needs embedding: ${#UNEMBEDDED_RUNS[@]} runs"

if [[ ${#UNEMBEDDED_RUNS[@]} -eq 0 ]]; then
    echo -e "${GREEN}🎉 All runs are already embedded!${NC}"
    echo
    echo "💡 To force re-embedding, use:"
    echo "  trailblazer embed corpus --reembed-all"
    exit 0
fi

# Create runs file for embedding
RUNS_FILE="var/temp_runs_to_embed.txt"
echo
echo "📝 Creating runs file: ${RUNS_FILE}"

# Clear existing file
> "${RUNS_FILE}"

# Add unembedded runs to file
for run_info in "${UNEMBEDDED_RUNS[@]}"; do
    echo "${run_info}" >> "${RUNS_FILE}"
done

echo "✅ Added ${#UNEMBEDDED_RUNS[@]} runs to ${RUNS_FILE}"

# Show embedding plan
echo
echo "📋 Embedding Plan:"
echo "=================="
echo "Provider: OpenAI (text-embedding-3-small)"
echo "Dimensions: 1536"
echo "Batch size: 128"
echo "Total chunks to embed: ${TOTAL_CHUNKS}"
echo

# Estimate cost (rough approximation)
# OpenAI text-embedding-3-small: $0.00002 per 1K tokens
# Assume average 100 tokens per chunk
ESTIMATED_TOKENS=$((TOTAL_CHUNKS * 100))
ESTIMATED_COST=$(echo "scale=6; ${ESTIMATED_TOKENS} * 0.00002 / 1000" | bc 2>/dev/null || echo "unknown")

echo "💰 Cost Estimate:"
echo "  Estimated tokens: ${ESTIMATED_TOKENS:,}"
echo "  Estimated cost: $${ESTIMATED_COST}"

# Ask for confirmation
echo
echo -e "${YELLOW}⚠️  Ready to start embedding?${NC}"
echo "This will process ${#UNEMBEDDED_RUNS[@]} runs with ${TOTAL_CHUNKS} chunks."
echo "Estimated cost: $${ESTIMATED_COST}"
echo
read -p "Continue? (y/N): " -r
if [[ ! "${REPLY}" =~ ^[Yy]$ ]]; then
    echo "❌ Embedding cancelled"
    exit 0
fi

# Start embedding
echo
echo "🚀 Starting OpenAI corpus embedding..."
echo "====================================="

# Use the embed dispatch script
if bash scripts/embed_dispatch.sh "${RUNS_FILE}"; then
    echo
    echo -e "${GREEN}🎉 OpenAI corpus embedding completed successfully!${NC}"
    echo
    echo "📊 Final Status:"
    echo "  Runs processed: ${#UNEMBEDDED_RUNS[@]}"
    echo "  Chunks embedded: ${TOTAL_CHUNKS}"
    echo "  Cost: $${ESTIMATED_COST}"
    echo
    echo "💡 To verify:"
    echo "  trailblazer embed status"
    echo "  trailblazer db doctor"
else
    echo
    echo -e "${RED}❌ OpenAI corpus embedding failed${NC}"
    echo "Check the logs for details"
    exit 1
fi
