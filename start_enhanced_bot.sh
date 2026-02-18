#!/bin/bash
# Start enhanced paper trading bot in tmux session

SESSION_NAME="enhanced_trading_bot"
BOT_DIR="/root/.openclaw/workspace/polymarket-strategy-tester"

cd "$BOT_DIR"

# Check if session already exists
if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    echo "Session $SESSION_NAME already exists. Attaching..."
    tmux attach -t "$SESSION_NAME"
    exit 0
fi

# Create new session and run bot
echo "Starting enhanced paper trading bot in tmux session: $SESSION_NAME"
tmux new-session -d -s "$SESSION_NAME" -c "$BOT_DIR"

# Send commands to the session
tmux send-keys -t "$SESSION_NAME" "cd $BOT_DIR" C-m
tmux send-keys -t "$SESSION_NAME" "source venv/bin/activate 2>/dev/null || true" C-m
tmux send-keys -t "$SESSION_NAME" "python3 enhanced_paper_trading.py" C-m

echo "Enhanced bot started in tmux session: $SESSION_NAME"
echo ""
echo "Commands:"
echo "  Attach: tmux attach -t $SESSION_NAME"
echo "  Detach: Ctrl+B, then D"
echo "  Kill: tmux kill-session -t $SESSION_NAME"
echo "  View logs: tail -f $BOT_DIR/enhanced_paper_trading.log"
