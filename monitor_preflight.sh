#!/bin/bash
while true; do
    clear
    echo "🔍 DISPATCHER PREFLIGHT PROGRESS"
    echo "==============================="
    echo "$(date)"
    echo
    
    # Count completed preflight checks
    COMPLETED=$(tmux capture-pane -t tb_embed_FIXED -p -S -3000 | grep -c "preflight passed" 2>/dev/null || echo 0)
    TOTAL=1804
    PERCENT=$(python3 -c "print(f\"{$COMPLETED/$TOTAL*100:.1f}%\")" 2>/dev/null || echo "0%")
    
    echo "Preflight checks completed: $COMPLETED / $TOTAL ($PERCENT)"
    
    # Show recent activity
    echo
    echo "Recent activity:"
    tmux capture-pane -t tb_embed_FIXED -p | tail -5
    
    # Check if dispatcher.out exists (means preflight is done)
    if [[ -f "var/logs/dispatch/20250818_235943/dispatcher.out" ]]; then
        echo
        echo "🎉 PREFLIGHT COMPLETE! Workers should be starting..."
        break
    fi
    
    echo
    echo "⏳ Still in preflight phase... refreshing in 30s"
    sleep 30
done
