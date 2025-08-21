# Trailblazer Scripts

This directory contains scripts to make running Trailblazer easier and more reliable.

## 🚀 **New Simplified Workflow**

### **Main Wrapper Script**

```bash
# Automatically handles virtual environment and package installation
./scripts/tb.sh [command] [args...]
```

### **Helper Scripts**

```bash
# Embedding
./scripts/embed.sh <run-id> [provider] [model] [dimensions]
./scripts/embed.sh 2025-01-15-1234 openai text-embedding-3-small 1536

# Ingestion
./scripts/ingest.sh <space-key> [since-date]
./scripts/ingest.sh N2S 2025-01-01

# Status
./scripts/status.sh
```

## 🔧 **What Changed**

### **Before (Complex)**

```bash
# Had to manually set PYTHONPATH and use long paths
PYTHONPATH=src python3 -m trailblazer.cli.main embed load --run-id "$run_id" --provider openai --model text-embedding-3-small --dimension 1536
```

### **After (Simple)**

```bash
# Just use the wrapper script
./scripts/tb.sh embed load --run-id "$run_id" --provider openai --model text-embedding-3-small --dimension 1536

# Or use helper scripts for common operations
./scripts/embed.sh "$run_id"
```

## 📋 **Common Operations**

### **Embedding**

```bash
# Full command
./scripts/tb.sh embed load --run-id 2025-01-15-1234 --provider openai --model text-embedding-3-small --dimension 1536

# Helper version
./scripts/embed.sh 2025-01-15-1234
```

### **Ingestion**

```bash
# Full command
./scripts/tb.sh ingest confluence --space-key N2S --since 2025-01-01

# Helper version
./scripts/ingest.sh N2S 2025-01-01
```

### **Status & Monitoring**

```bash
# Status overview
./scripts/status.sh

# Monitor processes
./scripts/tb.sh monitor

# Check paths
./scripts/tb.sh paths show
```

## 🎯 **Benefits**

1. **No more PYTHONPATH confusion** - automatically handled
1. **Virtual environment always activated** - no more "command not found"
1. **Package always installed** - automatically checks and installs if needed
1. **Shorter commands** - quick scripts for common operations
1. **More reliable** - consistent environment every time

## 🚨 **Requirements**

- Virtual environment must exist at `.venv/`
- Run `make setup` or `python3 -m venv .venv` first if it doesn't exist
- The wrapper script will automatically install the package in development mode

## 🔍 **Troubleshooting**

If you get errors:

1. **Virtual environment missing**: Run `make setup`
1. **Package not found**: The wrapper will auto-install it
1. **Permission denied**: Run `chmod +x scripts/*.sh`

## 📚 **Full Command Reference**

For all available commands, run:

```bash
./scripts/tb.sh --help
```

For specific command help:

```bash
./scripts/tb.sh embed --help
./scripts/tb.sh ingest --help
./scripts/tb.sh monitor --help
```
