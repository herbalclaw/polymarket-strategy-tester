#!/usr/bin/env python3
"""
Strategy Performance Monitor
Automatically removes underperforming strategies based on rules:
1. No trades in 6 hours → Remove
2. Negative P&L after 24 hours → Remove
"""

import pandas as pd
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, '/root/.openclaw/workspace/polymarket-strategy-tester')

def analyze_strategies():
    """Analyze strategy performance and return lists to remove."""
    df = pd.read_excel('/root/.openclaw/workspace/polymarket-strategy-tester/live_trading_results.xlsx', 
                       sheet_name='All Trades')
    
    df['DateTime'] = pd.to_datetime(df['Date'] + ' ' + df['Time'])
    now = datetime.now()
    
    to_remove_stale = []
    to_remove_negative = []
    
    for strategy in df['Strategy'].unique():
        strat_df = df[df['Strategy'] == strategy]
        last_trade = strat_df['DateTime'].max()
        hours_since = (now - last_trade).total_seconds() / 3600
        total_pnl = strat_df['P&L $'].sum()
        
        # Rule 1: No trades in 6 hours
        if hours_since >= 6:
            to_remove_stale.append({
                'strategy': strategy,
                'reason': f'No trades in {hours_since:.1f} hours',
                'last_trade': last_trade,
                'total_pnl': total_pnl
            })
        # Rule 2: Negative P&L (only if strategy has been running for 24h+)
        elif total_pnl < 0:
            # Check if strategy has been running for 24+ hours
            first_trade = strat_df['DateTime'].min()
            hours_running = (now - first_trade).total_seconds() / 3600
            if hours_running >= 24:
                to_remove_negative.append({
                    'strategy': strategy,
                    'reason': f'Negative P&L (${total_pnl:.2f}) after {hours_running:.1f} hours',
                    'total_pnl': total_pnl,
                    'hours_running': hours_running
                })
    
    return to_remove_stale, to_remove_negative

def remove_strategy(strategy_name):
    """Remove a strategy from the trading bot."""
    # Read the current strategy list
    strategy_file = '/root/.openclaw/workspace/polymarket-strategy-tester/run_paper_trading.py'
    
    with open(strategy_file, 'r') as f:
        content = f.read()
    
    # Find and comment out the strategy instantiation
    lines = content.split('\n')
    new_lines = []
    removed = False
    
    for line in lines:
        if strategy_name in line and 'Strategy()' in line:
            new_lines.append(f"            # REMOVED: {line.strip()}")
            removed = True
        else:
            new_lines.append(line)
    
    if removed:
        with open(strategy_file, 'w') as f:
            f.write('\n'.join(new_lines))
        print(f"✓ Removed {strategy_name}")
        return True
    else:
        print(f"✗ Could not find {strategy_name}")
        return False

def main():
    print("=== Strategy Performance Monitor ===")
    print(f"Time: {datetime.now()}")
    print()
    
    stale, negative = analyze_strategies()
    
    if stale:
        print(f"🗑️  STALE STRATEGIES (no trades in 6h): {len(stale)}")
        for s in stale:
            print(f"   - {s['strategy']}: {s['reason']}, P&L: ${s['total_pnl']:.2f}")
            remove_strategy(s['strategy'])
        print()
    
    if negative:
        print(f"📉 NEGATIVE P&L STRATEGIES (24h+): {len(negative)}")
        for s in negative:
            print(f"   - {s['strategy']}: {s['reason']}")
            remove_strategy(s['strategy'])
        print()
    
    if not stale and not negative:
        print("✅ All strategies performing within criteria")
    
    print()
    print("Note: Restart trading bot for changes to take effect")

if __name__ == '__main__':
    main()
