#!/usr/bin/env bash
# Safe migration of existing data to var/ structure
set -euo pipefail

echo "🚀 Migrating workspace data to var/ structure"
echo "=============================================="
echo ""

# Check if we have data to migrate
DIRS_TO_MIGRATE=()
[ -d "runs" ] && DIRS_TO_MIGRATE+=("runs")
[ -d "state" ] && DIRS_TO_MIGRATE+=("state")
[ -d "logs" ] && DIRS_TO_MIGRATE+=("logs")
[ -d "archive" ] && DIRS_TO_MIGRATE+=("archive")

if [ ${#DIRS_TO_MIGRATE[@]} -eq 0 ]; then
    echo "✅ No existing data to migrate"
    exit 0
fi

echo "📊 Data to migrate:"
for dir in "${DIRS_TO_MIGRATE[@]}"; do
    size=$(du -sh "$dir" | cut -f1)
    echo "  $dir/ -> var/$dir/ ($size)"
done
echo ""

# Ensure var/ structure exists
echo "📁 Creating var/ directory structure..."
mkdir -p var

# Migrate each directory safely
for dir in "${DIRS_TO_MIGRATE[@]}"; do
    echo "🔄 Migrating $dir/ -> var/$dir/"

    if [ -d "var/$dir" ]; then
        echo "⚠️  var/$dir already exists, merging content..."
        # Use rsync for safe merging
        rsync -av "$dir/" "var/$dir/"
    else
        # Simple move for new directories
        mv "$dir" "var/$dir"
    fi

    echo "✅ Migrated $dir/"
done

echo ""
echo "🎉 Migration completed successfully!"
echo ""
echo "📋 Verification:"
echo "==============="
ls -la var/
echo ""
echo "💾 Preserved data summary:"
du -sh var/* 2>/dev/null || echo "No data in var/"
echo ""
echo "🔍 Quick sanity check:"
echo "Confluence runs: $(find var/runs -name "confluence.ndjson" 2>/dev/null | wc -l)"
echo "DITA runs: $(find var/runs -name "dita.ndjson" 2>/dev/null | wc -l)"
echo "State files: $(find var/state -name "*_state.json" 2>/dev/null | wc -l)"
