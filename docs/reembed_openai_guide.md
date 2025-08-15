# OpenAI Corpus Re-embedding Guide

This guide explains how to re-embed the entire Ellucian documentation corpus with OpenAI embeddings in a repeatable, maintainable way.

## Overview

The re-embedding process converts the entire corpus from dummy embeddings to OpenAI embeddings, providing much better retrieval quality. The process is designed to be:

- **Repeatable**: Can be run multiple times safely
- **Maintainable**: Well-documented and configurable
- **Observable**: Progress tracking and logging
- **Resumable**: Can continue from where it left off
- **Cost-aware**: Estimates and tracks OpenAI API costs

## Prerequisites

1. **Environment Setup**

   ```bash
   # Ensure virtual environment is activated
   source .venv/bin/activate

   # Check that OpenAI package is installed
   pip list | grep openai
   ```

1. **Environment Variables** (in `.env`)

   ```bash
   OPENAI_API_KEY=your_openai_api_key_here
   TRAILBLAZER_DB_URL=postgresql+psycopg2://trailblazer:trailblazer_dev_password@localhost:5432/trailblazer
   ```

1. **Database Running**

   ```bash
   make db.up
   make db.wait
   ```

## Quick Start

### Option 1: Parallel Processing (Recommended)

```bash
# Pilot with 2 largest runs (safe testing)
make reembed.openai.pilot

# Full corpus with 2 workers (safe default)
make reembed.openai.all

# Full corpus with 3 workers (if API rate limits allow)
make reembed.openai.all WORKERS=3
```

### Option 2: Live Monitoring

```bash
# In a separate terminal, monitor progress
make embed.monitor

# To stop all embedding jobs cleanly
make embed.kill
```

### Option 3: Single-Run Processing (Original)

```bash
make reembed.openai
```

## Parallel Processing Details

### Commands Explained

- **`make reembed.openai.pilot`** → 2 runs, then check `var/reembed_progress.json` & `var/logs/...`
- **`make reembed.openai.all WORKERS=3`** → full corpus with 3 workers
- **`make embed.monitor`** → live dashboard
- **`make embed.kill`** → stop everything cleanly

### Worker Configuration

**Default WORKERS=2** (safe vs rate-limits). You can override:

```bash
# Conservative (safe for any API limits)
WORKERS=1 make reembed.openai.all

# Recommended (good balance)
WORKERS=2 make reembed.openai.all  # default

# Aggressive (if API headers show no throttling and DB is comfy)
WORKERS=3 make reembed.openai.all
WORKERS=4 make reembed.openai.all
```

### Monitoring & Control

```bash
# Watch live progress (refreshes every 15 seconds)
make embed.monitor

# Custom refresh interval
INTERVAL=5 make embed.monitor

# Kill all embedding jobs safely
make embed.kill
```

### ETA Computation

**How ETA is computed (EWMA docs/sec; worker-aware):**

- **EWMA Rate**: Uses Exponentially Weighted Moving Average to smooth the document processing rate
- **Worker-Aware**: Detects active `trailblazer embed load` processes to account for parallel workers
- **Planned vs Embedded**: Tracks `docs_planned` per run and `docs_embedded` progress
- **Converging ETA**: ETA becomes more accurate as the run proceeds and rate stabilizes

How to increase to 3–4 workers:

- Monitor API headers for throttling
- Ensure DB is comfortable with the load
- `WORKERS=3 make reembed.openai.all` or `WORKERS=4 make reembed.openai.all`

## What Gets Embedded

The script intelligently filters runs to embed:

### ✅ **Runs to Embed**

- **Large DITA runs (1000+ docs)**: Main Ellucian documentation corpus
- **Medium runs (100-999 docs)**: Substantial content
- **Small runs with unique content**: Any run with real content

### ❌ **Runs to Skip**

- **Personal site "Overview" templates**: 114 characters, empty content
- **Spanish "Descripción general" templates**: 172 characters, empty content
- **Confirmed duplicate templates only**

### Expected Corpus Size

- **Total runs**: ~949 runs
- **Total documents**: ~72,752 documents
- **Estimated cost**: ~$7-15 (depending on content length)

## Process Flow

1. **Initialization**

   - Load environment variables
   - Initialize progress tracking
   - Identify runs worth embedding

1. **Content Analysis**

   - Filter out empty templates
   - Sort runs by document count (largest first)
   - Estimate costs per run

1. **Embedding Process**

   - Process runs sequentially (one at a time)
   - Track progress and metrics
   - Handle errors gracefully
   - Log costs and performance

1. **Completion**

   - Generate summary report
   - Save progress for potential resumption
   - Clean up temporary files

## Monitoring and Progress

### Progress Tracking

- **File**: `var/reembed_progress.json`
- **Content**: Run-by-run status, metrics, timestamps
- **Format**: JSON for easy parsing and analysis

### Logs

- **Main logs**: `var/logs/embed-{run_id}.jsonl`
- **Error logs**: `var/reembed_errors.log`
- **Cost logs**: `var/reembed_cost.log`

### Real-time Monitoring

```bash
# Watch progress
tail -f var/reembed_progress.json

# Monitor errors
tail -f var/reembed_errors.log

# Track costs
tail -f var/reembed_cost.log
```

## Configuration

### Script Configuration

Edit `scripts/reembed_corpus_openai.sh` for:

- Embedding parameters (model, dimensions, batch size)
- Logging paths
- Processing behavior

### YAML Configuration

Edit `configs/reembed_openai.yaml` for:

- Content filtering rules
- Processing options
- Cost estimation parameters

## Error Handling and Recovery

### Automatic Recovery

- **Continue on errors**: Process continues even if individual runs fail
- **Error logging**: All errors are logged with context
- **Progress preservation**: Completed runs are tracked

### Manual Recovery

```bash
# Check progress
cat var/reembed_progress.json | jq '.'

# Resume from specific point
# (Script automatically skips completed runs)

# Retry failed runs
# (Script can be run multiple times safely)
```

### Common Issues and Solutions

#### 1. OpenAI API Rate Limits

- **Symptom**: 429 errors in logs
- **Solution**: Script includes backoff logic, wait and retry

#### 2. Database Connection Issues

- **Symptom**: Connection failures
- **Solution**: Check `make db.up` and database health

#### 3. Insufficient API Credits

- **Symptom**: 401/403 errors
- **Solution**: Check OpenAI account balance

## Cost Management

### Cost Estimation

- **Per run**: Script estimates cost before processing
- **Running total**: Tracked in cost log
- **Final summary**: Total cost reported at completion

### Cost Optimization

- **Batch processing**: Efficient API usage
- **Skip duplicates**: Avoid embedding same content multiple times
- **Smart filtering**: Only embed runs with real content

### Expected Costs

- **text-embedding-3-small**: $0.0001 per 1K tokens
- **~72K documents**: Estimated $7-15 total
- **Per run**: Varies by content length

## Performance and Timing

### Processing Speed

- **Large runs (1000+ docs)**: 1-3 minutes each
- **Medium runs (100-999 docs)**: 30 seconds - 2 minutes each
- **Small runs (< 100 docs)**: 10-60 seconds each

### Total Duration

- **Estimated time**: 4-8 hours for full corpus
- **Progress tracking**: Real-time updates every run
- **Resumable**: Can be stopped and resumed

## Maintenance and Updates

### Regular Maintenance

- **Clean up logs**: Archive old log files
- **Monitor costs**: Review cost logs for anomalies
- **Update configurations**: Adjust filtering rules as needed

### Updating the Process

- **Script updates**: Modify `scripts/reembed_corpus_openai.sh`
- **Configuration changes**: Edit `configs/reembed_openai.yaml`
- **New filtering rules**: Add to template skip list

### Version Control

- **Script changes**: Commit to git
- **Configuration updates**: Track in version control
- **Progress files**: Exclude from git (add to .gitignore)

## Troubleshooting

### Debug Mode

```bash
# Enable verbose logging
export REEMBED_DEBUG=1
./scripts/reembed_corpus_openai.sh
```

### Manual Verification

```bash
# Check specific run status
jq ".runs[\"$RUN_ID\"]" var/reembed_progress.json

# Verify embeddings in database
docker compose -f docker-compose.db.yml exec postgres psql -U trailblazer -d trailblazer -c "SELECT COUNT(*) FROM chunk_embeddings WHERE provider='openai';"
```

### Common Commands

```bash
# Check progress
make reembed.openai

# View logs
tail -f var/logs/embed-{run_id}.out

# Monitor database
docker compose -f docker-compose.db.yml exec postgres psql -U trailblazer -d trailblazer -c "SELECT provider, COUNT(*) FROM chunk_embeddings GROUP BY provider;"
```

## Best Practices

1. **Test First**: Run on a small subset before full corpus
1. **Monitor Progress**: Watch logs and progress files
1. **Handle Interruptions**: Script can be safely stopped and resumed
1. **Track Costs**: Monitor OpenAI API usage
1. **Document Changes**: Update configurations and scripts as needed

## Support and Maintenance

For issues or questions:

1. Check the logs for error details
1. Review this documentation
1. Check the script configuration
1. Verify environment setup

The re-embedding process is designed to be robust and maintainable, providing a solid foundation for building a high-quality searchable corpus of Ellucian documentation.
