# Logs Directory

**Note: This directory has been deprecated in favor of the new structure.**

## New Structure

- **Embedding logs**: `var/logs/embedding/`
- **Progress tracking**: `var/progress/embedding.json`
- **General logs**: `var/logs/`

## Migration

Old logs have been archived to `logs/archive_YYYYMMDD_HHMMSS/`.

## Current Usage

Use the new CLI commands for embedding:

```bash
# Start embedding
trailblazer embed corpus

# Monitor progress
./scripts/monitoring/monitor_embedding.sh
```

The new system provides:

- Real-time progress tracking
- Structured logging under var/
- Better observability
- Consolidated CLI interface
