# Monitoring Scripts

This directory contains monitoring scripts for various processes.

## Scripts

### `monitor_embedding.sh`

Simple monitoring for the corpus embedding process that reads CLI progress and status:

```bash
./scripts/monitoring/monitor_embedding.sh
```

**What it shows:**

- Current embedding progress and status
- Database statistics (documents, chunks, embeddings)
- Recent log entries
- Usage examples

**Prerequisites:**

- Corpus embedding must be running via `trailblazer embed corpus`
- Progress file at `var/progress/embedding.json`

### `monitor_batched.sh`

Monitoring for batched processes (legacy, may be removed).

### `monitor_retry.sh`

Monitoring for retry processes (legacy, may be removed).

## Usage

Run these scripts from the project root while processes are running:

```bash
# Monitor embedding progress
./scripts/monitoring/monitor_embedding.sh

# Monitor other processes (if applicable)
./scripts/monitoring/monitor_batched.sh
./scripts/monitoring/monitor_retry.sh
```

## Integration with CLI

The monitoring scripts now work with the consolidated CLI commands:

- **Embedding**: `trailblazer embed corpus` → `monitor_embedding.sh`
- **Progress**: Stored in `var/progress/embedding.json`
- **Logs**: Stored in `var/logs/embedding/`
