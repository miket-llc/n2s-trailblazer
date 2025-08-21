#!/bin/bash
# Trailblazer wrapper script - automatically handles virtual environment
# Usage: ./scripts/trailblazer.sh [command] [args...]

set -e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Check if virtual environment exists
if [[ ! -d "$PROJECT_ROOT/.venv" ]]; then
    echo "❌ Virtual environment not found at $PROJECT_ROOT/.venv"
    echo "Please run 'make setup' or 'python3 -m venv .venv' first"
    exit 1
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source "$PROJECT_ROOT/.venv/bin/activate"

# Check if trailblazer is installed
if ! python3 -c "import trailblazer" 2>/dev/null; then
    echo "❌ Trailblazer package not found. Installing in development mode..."
    pip install -e .
fi

# Run the trailblazer command
echo "🚀 Running: trailblazer $*"
exec trailblazer "$@"
