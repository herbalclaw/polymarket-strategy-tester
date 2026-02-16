#!/usr/bin/env python3
"""
Paper Trading Bot with Real Polymarket Fills
Uses actual order book walking for realistic trade simulation
"""

import asyncio
import logging
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))

from core.base_strategy import Signal
from core.excel_reporter import ExcelReporter
from core.github_pusher import GitHubAutoPusher
from data.polymarket_feed import PolymarketDataFeed
from strategies.momentum import MomentumStrategy
from strategies.arbitrage import ArbitrageStrategy
from strategies.vwap import VWAPStrategy
from strategies.leadlag import LeadLagStrategy
from strategies.sentiment import SentimentStrategy
from strategies.orderbook_imbalance import OrderBookImbalanceStrategy
from strategies.sharp_money import SharpMoneyStrategy
from strategies.volatility_scorer import VolatilityScorerStrategy
from strategies.breakout_momentum import BreakoutMomentumStrategy
from strategies.high_prob_convergence import HighProbabilityConvergenceStrategy
from strategies.market_making import MarketMakingStrategy
from strategies.copy_trading import CopyTradingStrategy

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('paper_trading.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('paper_trader')


class PaperTrader:
    """Paper trading bot with real Polymarket order book fills."""
    
    def __init__(self):
        self.running = False
        self.cycle = 0
        self.trades_executed = 0
        
        # Components
        self.feed = PolymarketDataFeed()
        self.reporter = ExcelReporter(
            filename="live_trading_results.xlsx",
            initial_capital=100.0,
            trade_size=5.0
        )
        self.pusher = GitHubAutoPusher(excel_filename="live_trading_results.xlsx")
        
        # Strategies
        self.strategies = [
            MomentumStrategy(),
            ArbitrageStrategy(),
            VWAPStrategy(),
            LeadLagStrategy(),
            SentimentStrategy(),
            OrderBookImbalanceStrategy(),
            SharpMoneyStrategy(),
            VolatilityScorerStrategy(),
            BreakoutMomentumStrategy(),
            HighProbabilityConvergenceStrategy(),
            MarketMakingStrategy(),
            CopyTradingStrategy(),
        ]
        
        # Register all strategies
        strategy_names = [s.name for s in self.strategies]
        self.reporter.register_strategies(strategy_names)
        
        # Track open positions
        self.open_positions: Dict[int, Dict] = {}
    
    def evaluate_strategies(self, market_data) -> List[Signal]:
        """Get signals from active (non-bankrupt) strategies."""
        signals = []
        for strategy in self.strategies:
            if not self.reporter.is_strategy_active(strategy.name):
                continue
            try:
                signal = strategy.generate_signal(market_data)
                if signal and signal.confidence >= 0.6:
                    signals.append(signal)
            except Exception as e:
                logger.error(f"Strategy {strategy.name} error: {e}")
        return signals
    
    async def execute_trade(self, signal: Signal) -> Optional[Dict]:
        """Execute a trade with real Polymarket fills."""
        # Get entry fill
        entry_price, entry_slippage, entry_status = self.feed.simulate_fill(
            side=signal.signal,
            size_dollars=5.0
        )
        
        if entry_price == 0 or entry_price == 0.5:
            logger.warning(f"No fill for entry: {entry_status}")
            return None
        
        if entry_status == "high_slippage":
            logger.warning(f"High slippage: {entry_slippage} bps, skipping")
            return None
        
        logger.info(f"Entry: {entry_price:.4f} (slippage: {entry_slippage} bps)")
        
        # Wait 5 minutes
        await asyncio.sleep(0.1)  # Instant for simulation
        
        # Get exit fill
        exit_side = 'down' if signal.signal == 'up' else 'up'
        exit_price, exit_slippage, exit_status = self.feed.simulate_fill(
            side=exit_side,
            size_dollars=5.0
        )
        
        if exit_price == 0 or exit_price == 0.5:
            exit_price = entry_price
            exit_slippage = 0
            exit_status = "fallback"
        
        logger.info(f"Exit: {exit_price:.4f} (slippage: {exit_slippage} bps)")
        
        # Calculate P&L
        if signal.signal == "up":
            pnl_pct = (exit_price - entry_price) / entry_price * 100
        else:
            pnl_pct = (entry_price - exit_price) / entry_price * 100
        
        return {
            'signal': signal,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'entry_slippage_bps': entry_slippage,
            'exit_slippage_bps': exit_slippage,
            'pnl_pct': pnl_pct,
            'pnl_amount': pnl_pct * 5 / 100,
            'exit_reason': 'time_exit_5min',
            'duration': 5,
        }
    
    async def run(self):
        """Main trading loop."""
        self.running = True
        
        logger.info("=" * 70)
        logger.info("🚀 PAPER TRADING BOT - Real Polymarket Fills")
        logger.info("=" * 70)
        logger.info(f"Strategies: {len(self.strategies)}")
        logger.info("Capital: $100 per strategy, $5 per trade")
        logger.info("=" * 70)
        
        while self.running:
            try:
                self.cycle += 1
                current_time = datetime.now()
                
                # Close expired positions (5-min hold)
                expired = [
                    (tid, pos) for tid, pos in self.open_positions.items()
                    if (current_time - pos['entry_time']).total_seconds() / 60 >= 5
                ]
                
                for trade_id, position in expired:
                    del self.open_positions[trade_id]
                    
                    # Close in reporter
                    result = position['result']
                    self.reporter.record_trade_close(
                        trade_id=trade_id,
                        exit_price=result['exit_price'],
                        pnl_pct=result['pnl_pct'],
                        exit_reason='time_exit_5min',
                        duration_minutes=5.0
                    )
                    
                    self.trades_executed += 1
                    logger.info(f"🔒 Trade #{trade_id} closed | P&L: {result['pnl_pct']:+.3f}%")
                
                # Get market data
                market_data = self.feed.fetch_data()
                if not market_data:
                    logger.warning("No market data")
                    await asyncio.sleep(5)
                    continue
                
                # Get signals
                signals = self.evaluate_strategies(market_data)
                
                if signals:
                    best = max(signals, key=lambda x: x.confidence)
                    logger.info(f"🎯 SIGNAL: {best.signal.upper()} | {best.strategy} | {best.confidence:.1%}")
                    
                    # Execute trade
                    result = await self.execute_trade(best)
                    if not result:
                        continue
                    
                    # Record open
                    open_record = self.reporter.record_trade_open(
                        strategy_name=best.strategy,
                        signal=best,
                        entry_price=result['entry_price'],
                        entry_reason=best.reason
                    )
                    
                    if not open_record:
                        continue
                    
                    trade_id = open_record['Trade #']
                    self.open_positions[trade_id] = {
                        'entry_time': current_time,
                        'result': result
                    }
                    
                    logger.info(f"🔓 Trade #{trade_id} opened | Price: {result['entry_price']:.4f}")
                
                # Status
                if self.cycle % 10 == 0:
                    logger.info(f"📊 Cycle {self.cycle} | Open: {len(self.open_positions)} | Closed: {self.trades_executed}")
                
                await asyncio.sleep(5)
                
            except Exception as e:
                logger.error(f"Error: {e}")
                await asyncio.sleep(5)
    
    def stop(self):
        """Stop gracefully."""
        self.running = False
        logger.info("Stopping...")


async def main():
    trader = PaperTrader()
    
    def handle_signal(sig, frame):
        trader.stop()
    
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    
    await trader.run()


if __name__ == "__main__":
    asyncio.run(main())
