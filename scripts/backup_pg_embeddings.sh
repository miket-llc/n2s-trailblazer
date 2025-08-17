#!/usr/bin/env bash
# PostgreSQL embeddings backup utility
# Creates timestamped backups of schema and embeddings data
# Requires: .env with TRAILBLAZER_DB_URL and TB_PG_CONTAINER

set -euo pipefail

# Ensure no pagers trigger
export PAGER=cat
export LESS=-RFX

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🔒 PostgreSQL Embeddings Backup Utility${NC}"
echo "=========================================="

# Check if .env exists
if [[ ! -f .env ]]; then
    echo -e "${RED}❌ Error: .env file not found${NC}"
    echo "Please create .env file with TRAILBLAZER_DB_URL and TB_PG_CONTAINER"
    exit 1
fi

# Source .env file (zsh-safe)
set -a
source .env
set +a

# Validate required environment variables
if [[ -z "${TRAILBLAZER_DB_URL:-}" ]]; then
    echo -e "${RED}❌ Error: TRAILBLAZER_DB_URL not set in .env${NC}"
    exit 1
fi

# Extract container name from .env or use default
TB_PG_CONTAINER="${TB_PG_CONTAINER:-trailblazer-postgres}"

echo "📊 Database: ${TRAILBLAZER_DB_URL//*@/***@}"
echo "🐳 Container: ${TB_PG_CONTAINER}"

# Generate timestamp
TS=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_DIR="var/backups/${TS}"

echo "⏰ Timestamp: ${TS}"
echo "📁 Backup directory: ${BACKUP_DIR}"

# Create backup directory
mkdir -p "${BACKUP_DIR}"

# Check if Docker container is running
if ! docker ps --format '{{.Names}}' | grep -q "^${TB_PG_CONTAINER}$"; then
    echo -e "${RED}❌ Error: Docker container '${TB_PG_CONTAINER}' is not running${NC}"
    echo "Start the database with: make db.up"
    exit 1
fi

echo -e "${YELLOW}📋 Creating schema backup...${NC}"

# Dump schema only
docker exec "${TB_PG_CONTAINER}" pg_dump \
    --host=localhost \
    --username=trailblazer \
    --dbname=trailblazer \
    --schema-only \
    --no-owner \
    --no-privileges \
    --file="/tmp/schema.sql"

# Copy schema from container
docker cp "${TB_PG_CONTAINER}:/tmp/schema.sql" "${BACKUP_DIR}/schema.sql"

echo -e "${YELLOW}💾 Creating embeddings data backup...${NC}"

# Dump embeddings-related tables with custom format
docker exec "${TB_PG_CONTAINER}" pg_dump \
    --host=localhost \
    --username=trailblazer \
    --dbname=trailblazer \
    --data-only \
    --format=custom \
    --verbose \
    --table=documents \
    --table=chunks \
    --table=chunk_embeddings \
    --file="/tmp/embeddings.dump"

# Copy data dump from container
docker cp "${TB_PG_CONTAINER}:/tmp/embeddings.dump" "${BACKUP_DIR}/embeddings.dump"

# Clean up temporary files in container
docker exec "${TB_PG_CONTAINER}" rm -f /tmp/schema.sql /tmp/embeddings.dump

echo -e "${YELLOW}📊 Generating backup manifest...${NC}"

# Get database info and table sizes
DB_INFO=$(docker exec "${TB_PG_CONTAINER}" psql \
    --host=localhost \
    --username=trailblazer \
    --dbname=trailblazer \
    --tuples-only \
    --no-align \
    --command="SELECT 
        current_database() as db_name,
        current_user as db_user,
        version() as pg_version;")

# Get table sizes
TABLE_SIZES=$(docker exec "${TB_PG_CONTAINER}" psql \
    --host=localhost \
    --username=trailblazer \
    --dbname=trailblazer \
    --tuples-only \
    --no-align \
    --command="SELECT 
        schemaname,
        tablename,
        pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size,
        pg_total_relation_size(schemaname||'.'||tablename) as size_bytes
    FROM pg_tables 
    WHERE tablename IN ('documents', 'chunks', 'chunk_embeddings')
    ORDER BY size_bytes DESC;")

# Create manifest.json
cat > "${BACKUP_DIR}/manifest.json" << EOF
{
  "backup_timestamp": "${TS}",
  "backup_created_at": "$(date -u -Iseconds)",
  "database_info": {
    "url": "${TRAILBLAZER_DB_URL//*@/***@}",
    "container": "${TB_PG_CONTAINER}",
    "details": "${DB_INFO//$'\n'/ }"
  },
  "backup_contents": {
    "schema_file": "schema.sql",
    "data_file": "embeddings.dump",
    "format": "PostgreSQL custom format (-Fc)"
  },
  "tables_backed_up": [
    "documents",
    "chunks", 
    "chunk_embeddings"
  ],
  "table_sizes": [
$(echo "${TABLE_SIZES}" | while IFS='|' read -r schema table size size_bytes; do
    if [[ -n "${schema}" && -n "${table}" ]]; then
        echo "    {\"schema\": \"${schema}\", \"table\": \"${table}\", \"size\": \"${size}\", \"size_bytes\": ${size_bytes:-0}}"
    fi
done | sed 's/,$//')
  ],
  "restore_instructions": {
    "schema": "psql -d \"\${TRAILBLAZER_DB_URL}\" -f schema.sql",
    "data": "pg_restore -d \"\${TRAILBLAZER_DB_URL}\" -Fc embeddings.dump",
    "order": "Restore schema first, then data"
  }
}
EOF

echo -e "${GREEN}✅ Backup completed successfully!${NC}"
echo
echo "📁 Backup location: ${BACKUP_DIR}"
echo "📋 Files created:"
echo "  - schema.sql (database schema)"
echo "  - embeddings.dump (embeddings data)"
echo "  - manifest.json (backup metadata)"
echo
echo "🔧 To restore from this backup:"
echo "  1. Ensure database is running: make db.up"
echo "  2. Restore schema: psql -d \"\${TRAILBLAZER_DB_URL}\" -f ${BACKUP_DIR}/schema.sql"
echo "  3. Restore data: pg_restore -d \"\${TRAILBLAZER_DB_URL}\" -Fc ${BACKUP_DIR}/embeddings.dump"
echo
echo "⚠️  WARNING: Restoring will overwrite existing data!"
echo "   Always verify your backup before restoring."
echo
echo "📊 Backup size: $(du -sh "${BACKUP_DIR}" | cut -f1)"
