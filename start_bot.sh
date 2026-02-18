#!/bin/bash
# Start trading bot in tmux session

cd /root/.openclaw/workspace/polymarket-strategy-tester

# Kill existing tmux session if exists
tmux kill-session -t trading_bot 2>/dev/null

# Start new tmux session with trading bot
tmux new-session -d -s trading_bot "python3 run_paper_trading.py > paper_trading.log 2>&1"

echo "Trading bot started in tmux session 'trading_bot'"
echo "View logs: tmux attach -t trading_bot"
echo "View log file: tail -f paper_trading.log"
