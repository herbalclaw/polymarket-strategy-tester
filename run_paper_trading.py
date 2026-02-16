#!/usr/bin/env python3
"""
Paper Trading Bot with Real Polymarket Binary Settlement
Correctly handles BTC 5-min prediction markets (settle to $1.00 or $0.00)
"""

import asyncio
import logging
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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
    """Paper trading bot with correct binary settlement for prediction markets."""
    
    def __init__(self):
        self.running = False
        self.cycle = 0
        self.trades_executed = 0
        self.trade_counter = 0
        
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
        # Key: trade_id, Value: position dict with market_window info
        self.open_positions: Dict[int, Dict] = {}
        
        # Track market windows we've processed
        self.processed_windows: set = set()
    
    def get_current_market_window(self) -> int:
        """Get current 5-minute market window timestamp."""
        return (int(time.time()) // 300) * 300
    
    def get_window_end_time(self, window_ts: int) -> datetime:
        """Get datetime when window ends."""
        return datetime.fromtimestamp(window_ts + 300)
    
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
    
    async def execute_trade(self, signal: Signal, market_window: int) -> Optional[Dict]:
        """
        Execute a trade for a specific market window.
        
        For BTC 5-min markets:
        - Entry: Buy UP or DOWN token at current price
        - Settlement: Window closes, BTC price vs strike determines winner
        - Winner pays $1.00, loser pays $0.00
        """
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
        
        # Get strike price for this window
        strike_price = self.feed.get_strike_price()
        
        logger.info(f"Entry: {entry_price:.4f} | Window: {market_window} | Strike: {strike_price}")
        
        return {
            'signal': signal,
            'entry_price': entry_price,
            'entry_slippage_bps': entry_slippage,
            'market_window': market_window,
            'strike_price': strike_price,
            'side': signal.signal,  # 'up' or 'down'
        }
    
    def check_settlement(self, position: Dict) -> Tuple[bool, float, float]:
        """
        Check if position has settled and calculate P&L.
        
        Returns:
            (settled, pnl_amount, pnl_pct)
        """
        market_window = position['market_window']
        current_window = self.get_current_market_window()
        
        # Window hasn't closed yet
        if current_window <= market_window:
            return False, 0.0, 0.0
        
        # Get actual BTC price at settlement
        settlement_price = self.feed.get_settlement_price(market_window)
        if settlement_price is None:
            return False, 0.0, 0.0
        
        strike_price = position['strike_price']
        entry_price = position['entry_price']
        side = position['side']
        
        # Determine winner
        # UP wins if settlement > strike
        # DOWN wins if settlement < strike
        up_wins = settlement_price > strike_price
        down_wins = settlement_price < strike_price
        
        if side == 'up':
            if up_wins:
                # Winner: paid entry_price, receive $1.00
                pnl_amount = 1.0 - entry_price
                pnl_pct = (pnl_amount / entry_price) * 100
            else:
                # Loser: paid entry_price, receive $0.00
                pnl_amount = -entry_price
                pnl_pct = -100.0
        else:  # side == 'down'
            if down_wins:
                # Winner: paid entry_price, receive $1.00
                pnl_amount = 1.0 - entry_price
                pnl_pct = (pnl_amount / entry_price) * 100
            else:
                # Loser: paid entry_price, receive $0.00
                pnl_amount = -entry_price
                pnl_pct = -100.0
        
        return True, pnl_amount, pnl_pct
    
    async def run(self):
        """Main trading loop."""
        self.running = True
        
        logger.info("=" * 70)
        logger.info("🚀 PAPER TRADING BOT - Binary Settlement (Corrected)")
        logger.info("=" * 70)
        logger.info(f"Strategies: {len(self.strategies)}")
        logger.info("Capital: $100 per strategy, $5 per trade")
        logger.info("Settlement: Winner=$1.00, Loser=$0.00")
        logger.info("=" * 70)
        
        while self.running:
            try:
                self.cycle += 1
                current_time = datetime.now()
                current_window = self.get_current_market_window()
                
                # Check for settled positions
                settled_trades = []
                for trade_id, position in list(self.open_positions.items()):
                    settled, pnl_amount, pnl_pct = self.check_settlement(position)
                    
                    if settled:
                        settled_trades.append((trade_id, position, pnl_amount, pnl_pct))
                
                # Process settlements
                for trade_id, position, pnl_amount, pnl_pct in settled_trades:
                    del self.open_positions[trade_id]
                    
                    # Close in reporter with binary settlement
                    self.reporter.record_trade_close(
                        trade_id=trade_id,
                        exit_price=1.0 if pnl_amount > 0 else 0.0,  # Winner pays 1.0, loser 0.0
                        pnl_pct=pnl_pct,
                        exit_reason='binary_settlement',
                        duration_minutes=5.0
                    )
                    
                    self.trades_executed += 1
                    result_str = "WIN" if pnl_amount > 0 else "LOSE"
                    logger.info(f"🔒 Trade #{trade_id} SETTLED | {result_str} | P&L: ${pnl_amount:+.4f} ({pnl_pct:+.1f}%)")
                
                # Get market data
                try:
                    market_data = self.feed.fetch_data()
                except Exception as e:
                    logger.error(f"Error fetching market data: {e}")
                    market_data = None
                
                if not market_data:
                    logger.warning("No market data, skipping cycle")
                    await asyncio.sleep(5)
                    continue
                
                # Validate market data
                if not hasattr(market_data, 'price') or market_data.price is None:
                    logger.warning("Invalid market data (no price), skipping")
                    await asyncio.sleep(5)
                    continue
                
                # Only trade if we're in a new window (avoid trading in closing window)
                window_progress = time.time() % 300  # Seconds into current 5-min window
                
                # Don't trade in last 30 seconds of window (too close to settlement)
                if window_progress > 270:
                    logger.debug(f"Window closing ({window_progress:.0f}s), skipping entry")
                    await asyncio.sleep(5)
                    continue
                
                # Get signals
                signals = self.evaluate_strategies(market_data)
                
                if signals:
                    best = max(signals, key=lambda x: x.confidence)
                    logger.info(f"🎯 SIGNAL: {best.signal.upper()} | {best.strategy} | {best.confidence:.1%}")
                    
                    # Execute trade for current window
                    result = await self.execute_trade(best, current_window)
                    if not result:
                        continue
                    
                    # Record open
                    self.trade_counter += 1
                    trade_id = self.trade_counter
                    
                    open_record = self.reporter.record_trade_open(
                        strategy_name=best.strategy,
                        signal=best,
                        entry_price=result['entry_price'],
                        entry_reason=best.reason
                    )
                    
                    if not open_record:
                        continue
                    
                    self.open_positions[trade_id] = {
                        'entry_time': current_time,
                        'market_window': result['market_window'],
                        'strike_price': result['strike_price'],
                        'entry_price': result['entry_price'],
                        'side': result['side'],
                    }
                    
                    logger.info(f"🔓 Trade #{trade_id} opened | Price: {result['entry_price']:.4f} | Window: {result['market_window']}")
                
                # Status
                if self.cycle % 10 == 0:
                    logger.info(f"📊 Cycle {self.cycle} | Open: {len(self.open_positions)} | Settled: {self.trades_executed}")
                
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
