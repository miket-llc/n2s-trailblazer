#!/bin/bash
# Activation script for Trailblazer development environment

# Change to project root directory (since script is in scripts/)
cd "$(dirname "$0")/.."

# Set pager environment for script safety (per guardrails)
export PAGER=cat
export LESS=-RFX

# Activate virtual environment
source .venv/bin/activate

echo "🚀 Trailblazer development environment activated!"
echo "📁 Project: $(pwd)"
echo "🐍 Python: $(which python)"
echo "📦 Virtual env: $VIRTUAL_ENV"
echo ""
echo "💡 Quick commands:"
echo "   trailblazer --help           # Show all commands"
echo "   trailblazer status           # Show workspace status"
echo "   trailblazer db doctor        # Check database health"
echo "   trailblazer confluence spaces # List Confluence spaces"
echo "   make ci                      # Run full CI pipeline"
echo ""
echo "📖 Ready to receive real-world data in var/runs/"
echo "💡 To use this script: source scripts/activate.sh"
