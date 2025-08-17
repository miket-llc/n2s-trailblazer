#!/usr/bin/env bash
# PostgreSQL embeddings restore utility (EMERGENCY USE ONLY)
# This script documents the restore process but does NOT auto-execute
# 
# WARNING: Restoring will OVERWRITE existing data!
# Always verify your backup before restoring.
# 
# Prerequisites:
# - Database running (make db.up)
# - .env with TRAILBLAZER_DB_URL set
# - Valid backup directory from backup_pg_embeddings.sh

set -euo pipefail

# Ensure no pagers trigger
export PAGER=cat
export LESS=-RFX

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${RED}🚨 EMERGENCY RESTORE UTILITY${NC}"
echo "================================"
echo
echo -e "${YELLOW}⚠️  WARNING: This will OVERWRITE existing data!${NC}"
echo
echo "This script documents the restore process but does NOT execute it."
echo "You must manually run the commands below."
echo

# Check if backup directory was provided
if [[ $# -eq 0 ]]; then
    echo -e "${RED}❌ Error: No backup directory specified${NC}"
    echo
    echo "Usage: $0 <backup_directory>"
    echo "Example: $0 var/backups/20250101T120000Z"
    echo
    echo "Available backups:"
    if [[ -d var/backups ]]; then
        ls -la var/backups/ 2>/dev/null || echo "No backups found"
    else
        echo "No backups directory found"
    fi
    exit 1
fi

BACKUP_DIR="$1"

# Validate backup directory
if [[ ! -d "${BACKUP_DIR}" ]]; then
    echo -e "${RED}❌ Error: Backup directory '${BACKUP_DIR}' not found${NC}"
    exit 1
fi

# Check required files exist
REQUIRED_FILES=("schema.sql" "embeddings.dump" "manifest.json")
for file in "${REQUIRED_FILES[@]}"; do
    if [[ ! -f "${BACKUP_DIR}/${file}" ]]; then
        echo -e "${RED}❌ Error: Required file '${file}' not found in backup${NC}"
        exit 1
    fi
done

echo -e "${GREEN}✅ Backup directory validated: ${BACKUP_DIR}${NC}"
echo

# Source .env file (zsh-safe)
if [[ -f .env ]]; then
    set -a
    source .env
    set +a
    echo "📊 Database URL: ${TRAILBLAZER_DB_URL//*@/***@}"
else
    echo -e "${RED}❌ Error: .env file not found${NC}"
    echo "Please create .env file with TRAILBLAZER_DB_URL"
    exit 1
fi

# Display backup manifest
echo
echo "📋 Backup manifest:"
if command -v jq >/dev/null 2>&1; then
    jq . "${BACKUP_DIR}/manifest.json"
else
    cat "${BACKUP_DIR}/manifest.json"
fi

echo
echo -e "${YELLOW}🔧 MANUAL RESTORE INSTRUCTIONS:${NC}"
echo "======================================"
echo
echo "1. Ensure database is running:"
echo "   make db.up"
echo
echo "2. Wait for database to be ready:"
echo "   make db.wait"
echo
echo "3. Restore schema (creates tables):"
echo "   psql -d \"\${TRAILBLAZER_DB_URL}\" -f ${BACKUP_DIR}/schema.sql"
echo
echo "4. Restore data (embeddings):"
echo "   pg_restore -d \"\${TRAILBLAZER_DB_URL}\" -Fc ${BACKUP_DIR}/embeddings.dump"
echo
echo "5. Verify restore:"
echo "   trailblazer db doctor"
echo
echo -e "${RED}⚠️  IMPORTANT:${NC}"
echo "   - Schema must be restored BEFORE data"
echo "   - This will overwrite existing tables"
echo "   - Ensure no applications are using the database during restore"
echo
echo -e "${GREEN}✅ Restore process documented above${NC}"
echo "Run the commands manually in the order shown."
echo
echo "For automated restore, you can run:"
echo "   bash -c 'psql -d \"\${TRAILBLAZER_DB_URL}\" -f ${BACKUP_DIR}/schema.sql && pg_restore -d \"\${TRAILBLAZER_DB_URL}\" -Fc ${BACKUP_DIR}/embeddings.dump'"
