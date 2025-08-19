# Embedding Scripts

This directory contains simplified scripts for embedding operations.

## Overview

The embedding pipeline has been streamlined and consolidated into the main CLI:

```bash
# Main command for embedding entire corpus
trailblazer embed corpus

# With options
trailblazer embed corpus --provider openai --model text-embedding-3-small --dimension 1536
```

## Scripts

### `embed_corpus.sh`

A simple wrapper script that provides convenient defaults and environment variable support:

```bash
# Basic usage
./scripts/embed/embed_corpus.sh

# Resume from specific run
./scripts/embed/embed_corpus.sh --resume-from 2025-08-15_080633_c4f3

# Limit runs to process
./scripts/embed/embed_corpus.sh --max-runs 10

# Force re-embed all
./scripts/embed/embed_corpus.sh --reembed-all
```

**Environment Variables:**

- `EMBED_PROVIDER` - Embedding provider (default: openai)
- `OPENAI_EMBED_MODEL` - Model name (default: text-embedding-3-small)
- `EMBED_DIMENSIONS` - Dimensions (default: 1536)
- `EMBED_BATCH_SIZE` - Batch size (default: 1000)
- `EMBED_LARGE_RUN_THRESHOLD` - Large run threshold (default: 2000)

## Features

- **Automatic batching** for large runs
- **Progress tracking** with real-time status
- **Resume capability** from any run ID
- **Cost estimation** with --dry-run-cost
- **Selective re-embedding** with --changed-only
- **Comprehensive logging** under var/logs/embedding/
- **Progress persistence** under var/progress/embedding.json

## Monitoring

Use the monitoring script to check status:

```bash
./scripts/monitoring/monitor_embedding.sh
```

## Migration from Old Scripts

The old complex scripts have been replaced by the CLI command:

- `embed_robust_batched.sh` → `trailblazer embed corpus`
- `embed_all_runs_final.sh` → `trailblazer embed corpus`
- `retry_large_run_batched.sh` → `trailblazer embed corpus --resume-from RUN_ID`
- `retry_failed_runs.sh` → `trailblazer embed corpus --resume-from RUN_ID`

## Output

- **Logs**: `var/logs/embedding/corpus_embedding_YYYYMMDD_HHMMSS.log`
- **Progress**: `var/progress/embedding.json`
- **Console**: Real-time progress and status updates
