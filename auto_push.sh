#!/bin/bash
# Auto-push script for trading results
# Pushes live_trading_results.xlsx to GitHub every 2 minutes

cd /root/.openclaw/workspace/polymarket-strategy-tester

while true; do
    sleep 120
    
    # Check if there are changes
    if git diff --quiet HEAD -- live_trading_results.xlsx 2>/dev/null; then
        continue
    fi
    
    # Add and commit
    git add -f live_trading_results.xlsx
    git commit -m "Trading update: $(date '+%Y-%m-%d %H:%M:%S')" 2>/dev/null || continue
    
    # Push
    git push origin master 2>/dev/null || echo "Push failed at $(date)"
done
