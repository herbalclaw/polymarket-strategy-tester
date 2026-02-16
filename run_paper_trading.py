#!/usr/bin/env python3
"""
Paper Trading Bot for Polymarket BTC 5-min Markets
Correctly handles binary settlement and position management
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
    """Paper trading bot for BTC 5-min prediction markets."""
    
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
        
        # Track open positions per strategy
        # Key: strategy_name, Value: position dict
        self.open_positions: Dict[str, Dict] = {}
    
    def get_current_market_window(self) -> int:
        """Get current 5-minute market window timestamp."""
        return (int(time.time()) // 300) * 300
    
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
    
    def calculate_binary_pnl(self, entry_price: float, exit_price: float, side: str) -> Tuple[float, float]:
        """
        Calculate P&L for binary prediction market.
        
        For binary markets:
        - You buy a token at price P (0.01 to 0.99)
        - If you win: token settles to $1.00, profit = (1 - P)
        - If you lose: token settles to $0.00, loss = -P
        - If you exit early at price X: P&L = (X - P) / P * 100%
        
        Returns: (pnl_amount, pnl_pct)
        """
        if side == 'up':
            # UP token: value goes to 1.0 if BTC up, 0.0 if BTC down
            pnl_amount = exit_price - entry_price
        else:  # side == 'down'
            # DOWN token: value goes to 1.0 if BTC down, 0.0 if BTC up
            pnl_amount = exit_price - entry_price
        
        pnl_pct = (pnl_amount / entry_price) * 100 if entry_price > 0 else 0
        
        return pnl_amount, pnl_pct
    
    async def execute_entry(self, signal: Signal) -> Optional[Dict]:
        """Open a new position."""
        strategy_name = signal.strategy
        
        # Check if strategy already has open position
        if strategy_name in self.open_positions:
            logger.debug(f"{strategy_name} already has open position, skipping entry")
            return None
        
        # Get entry fill from Polymarket
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
        
        market_window = self.get_current_market_window()
        
        logger.info(f"Entry: {entry_price:.4f} | Strategy: {strategy_name} | Window: {market_window}")
        
        return {
            'signal': signal,
            'entry_price': entry_price,
            'entry_slippage_bps': entry_slippage,
            'market_window': market_window,
            'side': signal.signal,
        }
    
    async def execute_exit(self, position: Dict) -> Optional[Dict]:
        """Close an existing position."""
        side = position['side']
        entry_price = position['entry_price']
        
        # Get exit fill from Polymarket (same side token)
        exit_price, exit_slippage, exit_status = self.feed.simulate_fill(
            side=side,
            size_dollars=5.0
        )
        
        if exit_price == 0 or exit_price == 0.5:
            logger.warning(f"No fill for exit: {exit_status}, using entry price")
            exit_price = entry_price
            exit_slippage = 0
        
        # Calculate P&L
        pnl_amount, pnl_pct = self.calculate_binary_pnl(entry_price, exit_price, side)
        
        return {
            'exit_price': exit_price,
            'exit_slippage_bps': exit_slippage,
            'pnl_amount': pnl_amount,
            'pnl_pct': pnl_pct,
        }
    
    async def run(self):
        """Main trading loop."""
        self.running = True
        
        logger.info("=" * 70)
        logger.info("🚀 PAPER TRADING BOT - BTC 5-min Markets")
        logger.info("=" * 70)
        logger.info(f"Strategies: {len(self.strategies)}")
        logger.info("Capital: $100 per strategy, $5 per trade")
        logger.info("Exit: Anytime (not held to settlement)")
        logger.info("=" * 70)
        
        while self.running:
            try:
                self.cycle += 1
                current_time = datetime.now()
                
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
                
                # Check for exit signals on open positions
                for strategy_name, position in list(self.open_positions.items()):
                    # Check if strategy wants to exit
                    strategy_obj = next((s for s in self.strategies if s.name == strategy_name), None)
                    if strategy_obj:
                        try:
                            # For now, use simple time-based exit (5 min max hold)
                            # In future, strategies can generate exit signals
                            entry_time = position.get('entry_time', current_time)
                            hold_time = (current_time - entry_time).total_seconds()
                            
                            # Exit after 5 minutes or if price moved significantly
                            entry_price = position['entry_price']
                            current_price = market_data.price
                            price_change_pct = abs(current_price - entry_price) / entry_price * 100
                            
                            should_exit = hold_time >= 300 or price_change_pct >= 10
                            
                            if should_exit:
                                exit_result = await self.execute_exit(position)
                                if exit_result:
                                    # Record close
                                    self.reporter.record_trade_close(
                                        trade_id=position['trade_id'],
                                        exit_price=exit_result['exit_price'],
                                        pnl_pct=exit_result['pnl_pct'],
                                        exit_reason='time_exit' if hold_time >= 300 else 'profit_taking',
                                        duration_minutes=hold_time / 60
                                    )
                                    
                                    del self.open_positions[strategy_name]
                                    self.trades_executed += 1
                                    
                                    logger.info(f"🔒 Trade #{position['trade_id']} closed | {strategy_name} | P&L: ${exit_result['pnl_amount']:+.4f} ({exit_result['pnl_pct']:+.1f}%)")
                        except Exception as e:
                            logger.error(f"Error checking exit for {strategy_name}: {e}")
                
                # Get entry signals
                signals = self.evaluate_strategies(market_data)
                
                for signal in signals:
                    # Execute entry
                    result = await self.execute_entry(signal)
                    if not result:
                        continue
                    
                    # Record open
                    self.trade_counter += 1
                    trade_id = self.trade_counter
                    
                    open_record = self.reporter.record_trade_open(
                        strategy_name=signal.strategy,
                        signal=signal,
                        entry_price=result['entry_price'],
                        entry_reason=signal.reason
                    )
                    
                    if not open_record:
                        continue
                    
                    self.open_positions[signal.strategy] = {
                        'trade_id': trade_id,
                        'entry_time': current_time,
                        'market_window': result['market_window'],
                        'entry_price': result['entry_price'],
                        'side': result['side'],
                    }
                    
                    logger.info(f"🔓 Trade #{trade_id} opened | {signal.strategy} | Price: {result['entry_price']:.4f}")
                
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
