# Trailblazer CLI Examples

This file shows the recommended workflow using the simplified wrapper commands.

## Quick Start

```bash
# 1. Preview what would be ingested (no writes)
trailblazer plan

# 2. Ingest everything with enforced ADF format
trailblazer ingest-all

# 3. Normalize all ingested data
trailblazer normalize-all

# 4. Check status and results
trailblazer status
```

## Common Workflows

### Fresh Start (Clear State)

```bash
# Clear state and ingest everything from scratch
trailblazer ingest-all --from-scratch
trailblazer normalize-all
```

### Delta Ingestion (Since Timestamp)

```bash
# Ingest only changes since a specific date
trailblazer ingest-all --since "2025-01-01T00:00:00Z"
trailblazer normalize-all
```

### Auto-Delta Mode

```bash
# Let the system auto-detect the last ingestion timestamp
trailblazer ingest-all --auto-since
trailblazer normalize-all
```

### Source-Specific Ingestion

```bash
# Ingest only Confluence (skip DITA)
trailblazer ingest-all --no-dita

# Ingest only DITA (skip Confluence)  
trailblazer ingest-all --no-confluence
```

### Debug Mode (Limited Pages)

```bash
# Limit to 50 pages for testing
trailblazer ingest-all --max-pages 50
```

### Quiet Mode

```bash
# Run with minimal output
trailblazer ingest-all --no-progress --no-color
trailblazer normalize-all --no-progress
```

## What These Commands Do

### `trailblazer plan`

- Dry-run preview of what would be ingested
- Shows space counts for Confluence
- Shows file counts for DITA
- No files written

### `trailblazer ingest-all`

- Calls `trailblazer ingest confluence` for every space
- Enforces `--body-format atlas_doc_format` for all Confluence
- Calls `trailblazer ingest dita` for all XML files
- Creates session index: `var/runs/INDEX-{timestamp}.md`
- Validates workspace is `var/` only

### `trailblazer normalize-all`

- Scans `var/runs/` for ingested data
- Calls `trailblazer normalize from-ingest` for each run
- Skips already-normalized runs

### `trailblazer status`

- Shows workspace overview
- Reports recent activity by source
- Identifies runs needing normalization
- Shows disk usage

## Advanced Usage

For fine-grained control, use the underlying commands directly:

```bash
# Ingest specific spaces
trailblazer ingest confluence --space DEV --space PROD

# Normalize specific run
trailblazer normalize from-ingest --run-id 2025-08-14_160534_03b2

# List all Confluence spaces
trailblazer confluence spaces
```

## File Locations

All data is stored under `var/`:

- **Raw ingested data**: `var/runs/{run-id}/ingest/`
- **Normalized data**: `var/runs/{run-id}/normalize/`
- **Session indices**: `var/runs/INDEX-{timestamp}.md`
- **Event logs**: `var/logs/{run-id}.ndjson`
- **State files**: `var/state/`

## Observability

Each command provides:

- Rich-formatted progress with colored output
- Real-time heartbeats every 30 seconds
- Structured NDJSON event logs
- Assurance reports with quality analysis
- Attachment verification with retry logic

Use `--no-color` to disable colors for automation.
