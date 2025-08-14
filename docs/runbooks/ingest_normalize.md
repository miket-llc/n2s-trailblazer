# Ingest & Normalize Runbook

This runbook provides copy-paste commands for the most common ingest and normalization workflows.

## Prerequisites

```bash
# 1. Setup environment (one-time)
make setup

# 2. Create .env file with Confluence credentials
cp configs/dev.env.example .env
# Edit .env to set CONFLUENCE_EMAIL and CONFLUENCE_API_TOKEN

# 3. Verify setup
make fmt && make lint && make test
```

## Basic Workflow

### 1. List Available Spaces

```bash
trailblazer confluence spaces
```

**Expected Output:**

- Console: Table showing space keys, names, and types
- Files: `runs/<run_id>/ingest/spaces.json`

### 2. Ingest from Confluence

**Small test ingest:**

```bash
trailblazer ingest confluence --space DEV --max-pages 10 --progress
```

**Full space ingest with progress:**

```bash
trailblazer ingest confluence --space DEV --progress --progress-every 5
```

**Multiple spaces:**

```bash
trailblazer ingest confluence --space DEV --space PROD --progress
```

**Expected Console Output:**

```
🚀 Starting ingest run: 2025-08-14_125430_abc1
📊 Spaces: DEV (1/1)
Mode: full
Pages: 0 → 50 → 100 → 150 (75.2 pages/s)
✅ Completed ingest run: 2025-08-14_125430_abc1
   Elapsed: 45.2s
   Total: 150 pages, 75 attachments
```

**Expected Files:**

```
runs/2025-08-14_125430_abc1/ingest/
├── confluence.ndjson          # Main output: one JSON per page
├── metrics.json               # Run statistics
├── manifest.json              # Artifact metadata
├── pages.csv                  # Human-readable page list
├── attachments.csv            # Human-readable attachment list
├── summary.json               # Space-by-space breakdown
├── links.jsonl               # All extracted links
├── attachments_manifest.jsonl # Attachment details
└── DEV_seen_page_ids.json    # Seen page IDs for delta detection
```

### 3. Normalize to Markdown

**From previous ingest run:**

```bash
trailblazer normalize from-ingest --run-id 2025-08-14_125430_abc1
```

**From custom file:**

```bash
trailblazer normalize from-ingest --input path/to/confluence.ndjson
```

**Expected Console Output:**

```
Normalized to: runs/2025-08-14_125430_abc1/normalize/normalized.ndjson
```

**Expected Files:**

```
runs/2025-08-14_125430_abc1/normalize/
├── normalized.ndjson          # Converted Markdown content
├── metrics.json               # Normalization statistics  
└── manifest.json              # Artifact metadata
```

## Advanced Workflows

### Incremental Ingest (Delta Updates)

**Using explicit timestamp:**

```bash
trailblazer ingest confluence --space DEV --since 2025-08-01T00:00:00Z --progress
```

**Using auto-since (reads from state files):**

```bash
trailblazer ingest confluence --space DEV --auto-since --progress
```

**Detect deletions between runs:**

```bash
trailblazer ingest diff-deletions \
  --space DEV \
  --baseline-run 2025-08-14_125430_abc1 \
  --current-run 2025-08-14_130245_def2
```

### Body Format Options

**ADF format (default, recommended):**

```bash
trailblazer ingest confluence --space DEV --body-format atlas_doc_format
```

**Storage format (legacy compatibility):**

```bash
trailblazer ingest confluence --space DEV --body-format storage
```

### Empty Results Handling

**Fail if no pages found (default):**

```bash
trailblazer ingest confluence --space NONEXISTENT
# → exits with code 4
```

**Allow empty results:**

```bash
trailblazer ingest confluence --space NONEXISTENT --allow-empty
# → exits with code 0
```

## Logging and Observability

### Progress Options

**Show progress bars:**

```bash
trailblazer ingest confluence --space DEV --progress --progress-every 10
```

**Quiet mode (banners hidden, progress shown):**

```bash
trailblazer ingest confluence --space DEV --progress --quiet-pretty
```

### Log Formats

**Auto-detect (TTY = pretty, CI = JSON):**

```bash
trailblazer ingest confluence --space DEV --log-format auto
```

**Force JSON logs:**

```bash
trailblazer ingest confluence --space DEV --log-format json
```

**Force plain logs:**

```bash
trailblazer ingest confluence --space DEV --log-format plain
```

## Troubleshooting

### Common Issues

**Authentication failure:**

```bash
# Check credentials in .env
cat .env | grep CONFLUENCE

# Test with spaces command
trailblazer confluence spaces
```

**Empty results:**

```bash
# Check if space key exists
trailblazer confluence spaces | grep YOUR_SPACE

# Try with --allow-empty to see what's happening
trailblazer ingest confluence --space YOUR_SPACE --allow-empty --progress
```

**Slow performance:**

```bash
# Use smaller batches
trailblazer ingest confluence --space DEV --max-pages 50 --progress

# Check network connectivity
curl -I https://ellucian.atlassian.net/wiki
```

### Important Notes

1. **No Database Required**: Ingest and normalize work without any database setup
1. **Database Only for Retrieval**: PostgreSQL + pgvector is only needed for `embed load` and `ask` commands
1. **ADF Default**: `atlas_doc_format` is the default and recommended body format
1. **Immutable Artifacts**: Each run creates a new directory under `runs/`; previous runs are never modified
1. **State Management**: Auto-since reads/writes state files in `state/confluence/` for incremental updates

### Run Structure

Every command produces artifacts in a consistent structure:

```
runs/<run_id>/
├── ingest/               # Raw ingested data
│   ├── confluence.ndjson # Main data file
│   ├── *.csv            # Human-readable exports
│   └── *.json(l)        # Metadata and sidecars
├── normalize/            # Processed Markdown
│   ├── normalized.ndjson # Converted content
│   └── *.json           # Metadata
└── embed/               # (Future: embeddings output)
```

The `<run_id>` format is: `YYYY-MM-DD_HHMMSS_<4-char-hex>` (e.g., `2025-08-14_125430_abc1`)
