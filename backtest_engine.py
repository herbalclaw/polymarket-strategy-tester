#!/usr/bin/env python3
"""
Backtesting Engine for Polymarket Strategies

Uses historical data from collector to backtest strategies
before deploying to paper trading.

Workflow:
1. Load historical price data from collector DB
2. Run strategy on historical data
3. Calculate realistic P&L with fees/slippage
4. If profitable, deploy to paper trading
"""

import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import json
import sys
import os

sys.path.insert(0, '/root/.openclaw/workspace/polymarket-strategy-tester')

from core.base_strategy import BaseStrategy, Signal, MarketData


@dataclass
class BacktestTrade:
    """Single backtest trade record."""
    timestamp: int
    strategy: str
    side: str  # 'up' or 'down'
    entry_price: float
    exit_price: float
    pnl: float
    fees: float
    slippage: float
    market_ts: int


class BacktestEngine:
    """
    Backtesting engine for Polymarket strategies.
    
    Features:
    - Realistic fee model (2% taker)
    - Realistic slippage (10-25 bps)
    - Market settlement simulation
    - Performance metrics
    """
    
    def __init__(self, 
                 db_path: str,
                 initial_capital: float = 100.0,
                 trade_size: float = 5.0,
                 taker_fee: float = 0.02,
                 slippage_range: Tuple[float, float] = (10, 25)):
        self.db_path = db_path
        self.initial_capital = initial_capital
        self.trade_size = trade_size
        self.taker_fee = taker_fee
        self.slippage_range = slippage_range
        
        self.trades: List[BacktestTrade] = []
        self.capital = initial_capital
        
    def load_price_data(self, start_time: Optional[int] = None, 
                       end_time: Optional[int] = None) -> pd.DataFrame:
        """Load price data from collector database."""
        conn = sqlite3.connect(self.db_path)
        
        query = '''
            SELECT timestamp_ms, market_ts, side, bid, ask, mid, spread_bps
            FROM price_updates
            WHERE 1=1
        '''
        
        if start_time:
            query += f' AND timestamp_ms >= {start_time}'
        if end_time:
            query += f' AND timestamp_ms <= {end_time}'
        
        query += ' ORDER BY timestamp_ms'
        
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        # Convert scaled prices back to decimals
        df['bid'] = df['bid'] / 1_000_000
        df['ask'] = df['ask'] / 1_000_000
        df['mid'] = df['mid'] / 1_000_000
        
        return df
    
    def create_market_data(self, row: pd.Series) -> MarketData:
        """Create MarketData object from DataFrame row."""
        return MarketData(
            timestamp=row['timestamp_ms'] / 1000,
            asset='BTC',
            price=row['mid'],
            bid=row['bid'],
            ask=row['ask'],
            mid=row['mid'],
            vwap=row['mid'],
            spread_bps=row['spread_bps'],
            volume_24h=0,
            order_book={
                'best_bid': row['bid'],
                'best_ask': row['ask'],
                'spread_bps': row['spread_bps'],
                'bid_depth': 1,
                'ask_depth': 1
            },
            metadata={'source': 'backtest'},
            market_end_time=row['market_ts']
        )
    
    def simulate_fill(self, price: float, side: str) -> Tuple[float, float]:
        """
        Simulate realistic fill with slippage and fees.
        
        Returns:
            (fill_price, total_cost)
        """
        # Add slippage (10-25 bps)
        slippage_bps = np.random.uniform(*self.slippage_range)
        slippage = slippage_bps / 10000
        
        if side == 'up':
            fill_price = price + slippage
        else:
            fill_price = price - slippage
        
        # Apply taker fee (2%)
        fee_cost = self.trade_size * self.taker_fee
        
        return fill_price, fee_cost
    
    def simulate_settlement(self, entry_price: float, side: str, 
                           final_price: float) -> float:
        """
        Simulate market settlement.
        
        Binary options settle to $1.00 or $0.00.
        For backtest, we use the final market price as proxy.
        """
        if side == 'up':
            # If final price > 0.50, UP wins
            if final_price > 0.50:
                return 1.0 - entry_price  # Win: payout - entry
            else:
                return -entry_price  # Loss: -entry
        else:  # side == 'down'
            # If final price < 0.50, DOWN wins
            if final_price < 0.50:
                return 1.0 - (1.0 - entry_price)  # Win: payout - entry
            else:
                return -(1.0 - entry_price)  # Loss: -entry
    
    def run_backtest(self, strategy: BaseStrategy, 
                     start_time: Optional[int] = None,
                     end_time: Optional[int] = None) -> Dict:
        """Run backtest for a single strategy."""
        df = self.load_price_data(start_time, end_time)
        
        if len(df) == 0:
            return {'error': 'No data available'}
        
        self.trades = []
        self.capital = self.initial_capital
        
        # Group by market window (5-min periods)
        df['market_window'] = df['market_ts']
        
        for market_ts, window_df in df.groupby('market_window'):
            # Process each timestamp in window
            for idx, row in window_df.iterrows():
                market_data = self.create_market_data(row)
                
                # Get signal from strategy
                try:
                    signal = strategy.generate_signal(market_data)
                except Exception as e:
                    continue
                
                if signal and signal.confidence >= 0.6:
                    # Simulate entry
                    entry_price, entry_fee = self.simulate_fill(
                        row['mid'], signal.signal
                    )
                    
                    # Find exit price (end of window)
                    window_end = window_df.iloc[-1]
                    exit_price, exit_fee = self.simulate_fill(
                        window_end['mid'], signal.signal
                    )
                    
                    # Calculate P&L
                    raw_pnl = self.simulate_settlement(
                        entry_price, signal.signal, window_end['mid']
                    ) * self.trade_size
                    
                    total_fees = entry_fee + exit_fee
                    net_pnl = raw_pnl - total_fees
                    
                    # Record trade
                    trade = BacktestTrade(
                        timestamp=int(row['timestamp_ms']),
                        strategy=strategy.name,
                        side=signal.signal,
                        entry_price=entry_price,
                        exit_price=exit_price,
                        pnl=net_pnl,
                        fees=total_fees,
                        slippage=self.slippage_range[1] / 10000,
                        market_ts=int(market_ts)
                    )
                    self.trades.append(trade)
                    self.capital += net_pnl
                    
                    # Only one trade per window per strategy
                    break
        
        return self.calculate_metrics()
    
    def calculate_metrics(self) -> Dict:
        """Calculate backtest performance metrics."""
        if not self.trades:
            return {
                'total_trades': 0,
                'total_pnl': 0,
                'win_rate': 0,
                'sharpe': 0,
                'max_drawdown': 0
            }
        
        pnls = [t.pnl for t in self.trades]
        
        total_pnl = sum(pnls)
        win_rate = len([p for p in pnls if p > 0]) / len(pnls)
        
        # Sharpe ratio (simplified)
        returns = np.array(pnls)
        sharpe = np.mean(returns) / np.std(returns) if np.std(returns) > 0 else 0
        
        # Max drawdown
        cumulative = np.cumsum(returns)
        running_max = np.maximum.accumulate(cumulative)
        drawdown = running_max - cumulative
        max_drawdown = np.max(drawdown) if len(drawdown) > 0 else 0
        
        return {
            'total_trades': len(self.trades),
            'total_pnl': total_pnl,
            'win_rate': win_rate,
            'sharpe': sharpe,
            'max_drawdown': max_drawdown,
            'final_capital': self.capital,
            'return_pct': (self.capital - self.initial_capital) / self.initial_capital * 100
        }


def main():
    """Run backtest on all strategies."""
    print("=== Polymarket Strategy Backtester ===\n")
    
    # Find largest database (most data)
    import glob
    dbs = glob.glob('/root/.openclaw/workspace/polymarket-data-collector/data/raw/btc_hf_*.db')
    if not dbs:
        print("No databases found!")
        return
    
    # Use the AM database (largest with 4154 records)
    largest_db = '/root/.openclaw/workspace/polymarket-data-collector/data/raw/btc_hf_2026-02-20_AM.db'
    print(f"Using database: {largest_db}")
    print(f"Records: ~4154\n")
    
    # Create backtest engine
    engine = BacktestEngine(largest_db)
    
    # Load and test strategies
    from strategies.first_principles_momentum import FirstPrinciplesMomentumStrategy
    
    strategy = FirstPrinciplesMomentumStrategy()
    print(f"Backtesting: {strategy.name}")
    print("-" * 50)
    
    results = engine.run_backtest(strategy)
    
    print(f"Total Trades: {results['total_trades']}")
    print(f"Total P&L: ${results['total_pnl']:.2f}")
    print(f"Win Rate: {results['win_rate']*100:.1f}%")
    print(f"Sharpe: {results['sharpe']:.2f}")
    print(f"Max Drawdown: ${results['max_drawdown']:.2f}")
    
    # Profitable threshold
    if results['total_pnl'] > 0 and results['win_rate'] > 0.5:
        print("\n✅ STRATEGY PASSED - Ready for paper trading")
    elif results['total_trades'] == 0:
        print("\n⚠️  NO TRADES - Strategy didn't generate signals")
    else:
        print("\n❌ STRATEGY FAILED - Needs improvement")


if __name__ == '__main__':
    main()
