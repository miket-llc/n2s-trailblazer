#!/usr/bin/env bash
set -euo pipefail
echo "[KILL] stopping all embed jobs…"
# tmux session used? kill it safely
tmux has-session -t embed_workers 2>/dev/null && tmux kill-session -t embed_workers || true
# kill any embed load processes (trailing ones)
pkill -f "trailblazer embed load" || true
pkill -f "reembed_corpus_openai.sh" || true
echo "[KILL] done."
