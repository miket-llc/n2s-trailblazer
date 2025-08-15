#!/bin/bash
# Minimal ETA estimation wrapper (≤20 LOC)
# Usage: ./scripts/estimate_eta.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "🕐 ETA Estimator - Use 'trailblazer ops monitor' for full features"

# Just run the monitor command which already has ETA functionality
exec python3 -m trailblazer.cli.main ops monitor --interval 30
