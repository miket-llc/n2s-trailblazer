#!/bin/bash
# Quick status script - shows current status
# Usage: ./scripts/quick-status.sh

echo "📊 Quick Trailblazer Status"
echo "=========================="
echo ""

# Show status
./scripts/tb.sh status

echo ""
echo "🔍 Runs status:"
./scripts/tb.sh runs status

echo ""
echo "📁 Workspace paths:"
./scripts/tb.sh paths show
