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
    
    def calculate_early_exit_pnl(self, entry_price: float, exit_price: float, side: str) -> Tuple[float, float]:
        """
        Calculate P&L for early exit (selling before expiry).
        P&L = (exit_price - entry_price)
        """
        pnl_amount = exit_price - entry_price
        pnl_pct = (pnl_amount / entry_price) * 100 if entry_price > 0 else 0
        return pnl_amount, pnl_pct
    
    def calculate_expiry_settlement(self, entry_price: float, side: str, won: bool) -> Tuple[float, float]:
        """
        Calculate P&L for holding to expiry.
        
        Args:
            entry_price: Price paid for token
            side: 'up' or 'down'
            won: True if prediction was correct
        
        Returns:
            (pnl_amount, pnl_pct)
        """
        if won:
            # Winner: token settles to $1.00
            # Profit = $1.00 - entry_price
            exit_price = 1.0
            pnl_amount = 1.0 - entry_price
        else:
            # Loser: token settles to $0.00
            # Loss = -entry_price
            exit_price = 0.0
            pnl_amount = -entry_price
        
        pnl_pct = (pnl_amount / entry_price) * 100 if entry_price > 0 else 0
        return exit_price, pnl_amount, pnl_pct
    
    async def execute_entry(self, signal: Signal) -> Optional[Dict]:
        """Open a new position."""
        strategy_name = signal.strategy
        
        # Check if strategy already has open position
        if strategy_name in self.open_positions:
            logger.debug(f"{strategy_name} already has open position, skipping entry")
            return None
        
        # EDGE CASE: Don't enter in last 15 seconds of window (too close to expiry)
        time_in_window = time.time() % 300
        if time_in_window > 285:
            logger.debug(f"Too close to expiry ({time_in_window:.0f}s), skipping entry")
            return None
        
        # Get entry fill from Polymarket
        entry_price, entry_slippage, entry_status = self.feed.simulate_fill(
            side=signal.signal,
            size_dollars=5.0
        )
        
        # EDGE CASE: Invalid price (allow 0.01 and 0.99, reject 0.50 default)
        if entry_price < 0.01 or entry_price > 0.99 or entry_price == 0.5:
            logger.warning(f"Invalid entry price: {entry_price}, skipping")
            return None
        
        # EDGE CASE: High slippage indicates low liquidity
        if entry_status == "high_slippage":
            logger.warning(f"High slippage: {entry_slippage} bps, skipping")
            return None
        
        # EDGE CASE: No fill
        if entry_status == "no_fill":
            logger.warning(f"No fill available, skipping")
            return None
        
        market_window = self.get_current_market_window()
        strike_price = self.feed.get_strike_price()
        
        # EDGE CASE: No strike price available
        if strike_price is None:
            logger.warning(f"No strike price available, skipping")
            return None
        
        logger.info(f"Entry: {entry_price:.4f} | Strategy: {strategy_name} | Window: {market_window} | Strike: {strike_price}")
        
        return {
            'signal': signal,
            'entry_price': entry_price,
            'entry_slippage_bps': entry_slippage,
            'market_window': market_window,
            'strike_price': strike_price,
            'side': signal.signal,
        }
    
    async def execute_early_exit(self, position: Dict) -> Optional[Dict]:
        """Close position early at market price."""
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
        
        # Calculate P&L for early exit
        pnl_amount, pnl_pct = self.calculate_early_exit_pnl(entry_price, exit_price, side)
        
        return {
            'exit_price': exit_price,
            'exit_slippage_bps': exit_slippage,
            'pnl_amount': pnl_amount,
            'pnl_pct': pnl_pct,
            'settled': False,
        }
    
    def check_expiry_settlement(self, position: Dict) -> Optional[Dict]:
        """
        Check if position has reached expiry and settle it.
        
        Returns:
            Settlement dict if settled, None if not yet
        """
        market_window = position['market_window']
        current_window = self.get_current_market_window()
        
        # Window hasn't closed yet
        if current_window <= market_window:
            return None
        
        # EDGE CASE: Window closed but we're more than 1 window behind
        # This shouldn't happen, but handle it gracefully
        if current_window > market_window + 300:
            logger.warning(f"Position from window {market_window} is stale (current: {current_window})")
            # Force settlement as loss (conservative)
            entry_price = position['entry_price']
            side = position['side']
            exit_price, pnl_amount, pnl_pct = self.calculate_expiry_settlement(entry_price, side, won=False)
            return {
                'exit_price': exit_price,
                'pnl_amount': pnl_amount,
                'pnl_pct': pnl_pct,
                'settled': True,
                'result': 'STALE_LOSS',
                'settlement_price': None,
                'strike_price': position['strike_price'],
            }
        
        # Window closed - get settlement price
        settlement_price = self.feed.get_settlement_price(market_window)
        
        # EDGE CASE: Can't get settlement price, retry next cycle
        if settlement_price is None:
            logger.debug(f"Settlement price not available for window {market_window}, retrying...")
            return None
        
        strike_price = position['strike_price']
        entry_price = position['entry_price']
        side = position['side']
        
        # EDGE CASE: Missing strike price - use settlement as fallback
        if strike_price is None:
            logger.warning(f"Missing strike price for position, using settlement price comparison")
            # Can't determine winner without strike, mark as push (loss)
            won = False
            result = "PUSH"
        else:
            # Determine winner
            # UP wins if settlement > strike
            # DOWN wins if settlement < strike
            # Push (exact match) = both lose (rare)
            up_wins = settlement_price > strike_price
            down_wins = settlement_price < strike_price
            is_push = abs(settlement_price - strike_price) < 0.01  # Within 1 cent = push
            
            if is_push:
                # Push - both sides lose (edge case)
                won = False
                result = "PUSH"
            elif side == 'up':
                won = up_wins
                result = "WIN" if won else "LOSE"
            else:  # side == 'down'
                won = down_wins
                result = "WIN" if won else "LOSE"
        
        # Calculate settlement P&L
        exit_price, pnl_amount, pnl_pct = self.calculate_expiry_settlement(entry_price, side, won)
        
        return {
            'exit_price': exit_price,
            'pnl_amount': pnl_amount,
            'pnl_pct': pnl_pct,
            'settled': True,
            'result': result,
            'settlement_price': settlement_price,
            'strike_price': strike_price,
        }
    
    async def run(self):
        """Main trading loop."""
        self.running = True
        
        logger.info("=" * 70)
        logger.info("🚀 PAPER TRADING BOT - BTC 5-min Markets")
        logger.info("=" * 70)
        logger.info(f"Strategies: {len(self.strategies)}")
        logger.info("Capital: $100 per strategy, $5 per trade")
        logger.info("Settlement: Early exit OR hold to expiry ($1.00/$0.00)")
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
                
                # Process open positions - check for expiry settlement first
                for strategy_name, position in list(self.open_positions.items()):
                    try:
                        # First check if window expired (settlement)
                        settlement = self.check_expiry_settlement(position)
                        
                        if settlement:
                            # Window closed - settle at expiry
                            del self.open_positions[strategy_name]
                            self.trades_executed += 1
                            
                            # Record close
                            self.reporter.record_trade_close(
                                trade_id=position['trade_id'],
                                exit_price=settlement['exit_price'],
                                pnl_pct=settlement['pnl_pct'],
                                exit_reason=f"expiry_{settlement['result'].lower()}",
                                duration_minutes=5.0
                            )
                            
                            logger.info(f"🔒 Trade #{position['trade_id']} SETTLED | {strategy_name} | {settlement['result']} | P&L: ${settlement['pnl_amount']:+.4f} ({settlement['pnl_pct']:+.1f}%)")
                            continue
                        
                        # No expiry yet - check for early exit conditions
                        entry_time = position.get('entry_time', current_time)
                        hold_time = (current_time - entry_time).total_seconds()
                        
                        # Exit after 5 minutes wall time OR if price moved significantly
                        entry_price = position['entry_price']
                        current_price = market_data.price
                        price_change_pct = abs(current_price - entry_price) / entry_price * 100
                        
                        should_exit_early = hold_time >= 300 or price_change_pct >= 10
                        
                        if should_exit_early:
                            exit_result = await self.execute_early_exit(position)
                            if exit_result:
                                del self.open_positions[strategy_name]
                                self.trades_executed += 1
                                
                                # Record close
                                self.reporter.record_trade_close(
                                    trade_id=position['trade_id'],
                                    exit_price=exit_result['exit_price'],
                                    pnl_pct=exit_result['pnl_pct'],
                                    exit_reason='early_exit',
                                    duration_minutes=hold_time / 60
                                )
                                
                                logger.info(f"🔒 Trade #{position['trade_id']} EARLY EXIT | {strategy_name} | P&L: ${exit_result['pnl_amount']:+.4f} ({exit_result['pnl_pct']:+.1f}%)")
                                
                    except Exception as e:
                        logger.error(f"Error processing position {strategy_name}: {e}")
                
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
                        'strike_price': result['strike_price'],
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
