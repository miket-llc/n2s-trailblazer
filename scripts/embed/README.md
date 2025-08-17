# Embedding Scripts

This directory contains scripts for bulk embedding processing.

## Main Scripts

### `embed_robust_batched.sh`

The primary production embedding script with:

- Automatic batching for large runs (>2000 chunks)
- Retry logic with exponential backoff
- Comprehensive logging
- Database health checks
- Resume capability

**Usage:**

```bash
# From project root
./scripts/embed/embed_robust_batched.sh

# With resume from specific run
./scripts/embed/embed_robust_batched.sh 2025-08-15_080633_c4f3
```

### `retry_failed_runs.sh`

Retry specific failed runs from the failure log.

### `retry_large_run_batched.sh`

Specialized script for handling very large runs with custom batching.

## Prerequisites

1. Virtual environment activated with trailblazer installed
1. Environment variables set (especially `OPENAI_API_KEY`)
1. Database properly initialized
1. Run from project root directory for proper path resolution

## Logs

- `embedding_bulk_batched.log` - Main execution log
- `embedding_failures_batched.log` - Failed runs only
