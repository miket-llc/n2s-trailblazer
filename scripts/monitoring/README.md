# Monitoring Scripts

This directory contains monitoring scripts for embedding processes.

## Scripts

### `monitor_batched.sh`

Real-time monitoring for the batched embedding process.

### `monitor_embedding.sh`

General embedding process monitoring.

### `monitor_retry.sh`

Monitoring for retry processes.

## Usage

Run these scripts from the project root while embedding processes are running:

```bash
./scripts/monitoring/monitor_batched.sh
```

The scripts show:

- Live progress updates
- Database statistics
- Error summaries
- Performance metrics
