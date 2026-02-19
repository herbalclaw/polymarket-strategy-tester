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
from strategies.microstructure_scalper import MicrostructureScalperStrategy
from strategies.ema_arbitrage import EMAArbitrageStrategy
from strategies.longshot_bias import LongshotBiasStrategy
from strategies.high_probability_bond import HighProbabilityBondStrategy
from strategies.time_decay import TimeDecayStrategy
from strategies.bollinger_bands import BollingerBandsStrategy
from strategies.spread_capture import SpreadCaptureStrategy
from strategies.vpin import VPINStrategy
from strategies.time_weighted_momentum import TimeWeightedMomentumStrategy
from strategies.price_skew import PriceSkewStrategy
from strategies.serial_correlation import SerialCorrelationStrategy
from strategies.liquidity_shock import LiquidityShockStrategy
from strategies.order_flow_imbalance import OrderFlowImbalanceStrategy
from strategies.volatility_expansion import VolatilityExpansionStrategy
from strategies.informed_trader_flow import InformedTraderFlowStrategy
from strategies.contrarian_extreme import ContrarianExtremeStrategy
from strategies.fee_optimized_scalper import FeeOptimizedScalperStrategy
from strategies.tick_size_arbitrage import TickSizeArbitrageStrategy
from strategies.ivmr import IVMRStrategy
from strategies.orderbook_imbalance import OrderBookImbalanceStrategy
from strategies.time_decay_scalper import TimeDecayScalpingStrategy
from strategies.spread_capture import SpreadCaptureStrategy
from strategies.momentum_ignition import MomentumIgnitionStrategy
from strategies.range_bound_mr import RangeBoundMeanReversionStrategy
from strategies.liquidity_sweep import LiquiditySweepStrategy
from strategies.volume_weighted_microprice import VolumeWeightedMicropriceStrategy
from strategies.bid_ask_bounce import BidAskBounceStrategy
from strategies.gamma_scalp import GammaScalpStrategy
from strategies.adverse_selection_filter import AdverseSelectionFilterStrategy
from strategies.orderbook_slope import OrderBookSlopeStrategy
from strategies.quote_stuffing_detector import QuoteStuffingDetectorStrategy
from strategies.microprice_reversion import MicroPriceReversionStrategy
from strategies.late_entry_momentum import LateEntryMomentumStrategy
from strategies.smart_money_flow import SmartMoneyFlowStrategy
from strategies.kelly_criterion import KellyCriterionStrategy
from strategies.time_decay_alpha import TimeDecayAlphaStrategy
from strategies.toxic_flow_detector import ToxicFlowDetectorStrategy
from strategies.dual_class_arbitrage import DualClassArbitrageStrategy
from strategies.no_farming import NoFarmingStrategy
from strategies.high_probability_compounding import HighProbabilityCompoundingStrategy
from strategies.inventory_skew import InventorySkewStrategy
from strategies.adverse_selection_flow import AdverseSelectionFilterStrategy
from strategies.spread_capture import SpreadCaptureStrategy

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
            MicrostructureScalperStrategy(),
            EMAArbitrageStrategy(),  # NEW: $427K PNL strategy from Twitter
            LongshotBiasStrategy(),  # NEW: Behavioral bias exploitation
            HighProbabilityBondStrategy(),  # NEW: 96% win rate strategy
            TimeDecayStrategy(),  # NEW: Time premium harvesting
            BollingerBandsStrategy(),  # NEW: Mean reversion with BB
            SpreadCaptureStrategy(),  # NEW: Market making spread capture
            VPINStrategy(),  # NEW: Volume-synchronized informed trading detection
            TimeWeightedMomentumStrategy(),  # NEW: Time-weighted momentum for 5-min windows
            PriceSkewStrategy(),  # NEW: YES/NO price skew sentiment detection
            SerialCorrelationStrategy(),  # NEW: Mean reversion from serial correlation
            LiquidityShockStrategy(),  # NEW: Fade liquidity shocks
            OrderFlowImbalanceStrategy(),  # NEW: Order flow imbalance from LOB
            VolatilityExpansionStrategy(),  # NEW: Trade volatility expansion after compression
            InformedTraderFlowStrategy(),  # NEW: Detect smart money through volume-price patterns
            ContrarianExtremeStrategy(),  # NEW: Fade price extremes exploiting retail overreaction
            FeeOptimizedScalperStrategy(),  # NEW: Fee-optimized scalping near price extremes
            TickSizeArbitrageStrategy(),  # NEW: Exploit tick-size regime changes
            IVMRStrategy(),  # NEW: Implied Volatility Mean Reversion
            OrderBookImbalanceStrategy(),  # NEW: Order book imbalance microstructure alpha
            TimeDecayScalpingStrategy(),  # NEW: Exploits time decay in short-term prediction markets
            SpreadCaptureStrategy(),  # NEW: Capture bid-ask spread micro-inefficiencies
            MomentumIgnitionStrategy(),  # NEW: Trade momentum ignition and follow-through
            RangeBoundMeanReversionStrategy(),  # NEW: Mean reversion within identified price ranges
            LiquiditySweepStrategy(),  # NEW: Fade liquidity sweeps and capture reversals
            VolumeWeightedMicropriceStrategy(),  # NEW: Volume-weighted microprice divergence alpha
            BidAskBounceStrategy(),  # NEW: Trade bid-ask level bounces in CLOB
            GammaScalpStrategy(),  # NEW: Gamma scalping near 50-cent high-sensitivity zone
            AdverseSelectionFilterStrategy(),  # NEW: Filter based on adverse selection risk
            OrderBookSlopeStrategy(),  # NEW: Order book slope and depth analysis
            QuoteStuffingDetectorStrategy(),  # NEW: Detect and exploit quote stuffing manipulation
            MicroPriceReversionStrategy(),  # NEW: Microprice deviation reversion alpha
            LateEntryMomentumStrategy(),  # NEW: Late-window momentum continuation
            SmartMoneyFlowStrategy(),  # NEW: Smart money flow detection
            KellyCriterionStrategy(),  # NEW: Kelly criterion optimal bet sizing
            TimeDecayAlphaStrategy(),  # NEW: Exploit time decay in short-term markets
            ToxicFlowDetectorStrategy(),  # NEW: Detect and fade toxic order flow
            DualClassArbitrageStrategy(),  # NEW: YES+NO parity arbitrage
            NoFarmingStrategy(),  # NEW: Systematic NO farming exploiting long-shot bias
            HighProbabilityCompoundingStrategy(),  # NEW: High-probability auto-compounding
            InventorySkewStrategy(),  # NEW: Exploit market maker inventory skewing
            AdverseSelectionFilterStrategy(),  # NEW: Trade alongside informed flow
            SpreadCaptureStrategy(),  # NEW: Capture spread compression profits
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

    def get_next_market_window(self) -> int:
        """Get next 5-minute market window timestamp - like streak bot."""
        return self.get_current_market_window() + 300

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
        Returns DOLLAR PnL (per-share PnL * trade_size)
        """
        trade_size = 5.0  # $5 per trade
        
        if side.lower() == 'down':
            # For DOWN positions, we profit when price goes down
            pnl_per_share = entry_price - exit_price
        else:
            # For UP positions, we profit when price goes up
            pnl_per_share = exit_price - entry_price
        
        # Convert to dollar PnL
        pnl_dollars = pnl_per_share * trade_size
        pnl_pct = (pnl_per_share / entry_price) * 100 if entry_price > 0 else 0
        
        return pnl_dollars, pnl_pct
    
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
        
        market_window = self.get_next_market_window()
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
        Check if position has reached expiry and settle it using Polymarket's official result.
        Uses streak bot logic: checks umaResolutionStatus for reliable settlement detection.
        """
        market_window = position['market_window']
        current_window = self.get_current_market_window()
        
        # Window hasn't closed yet
        if current_window <= market_window:
            return None
        
        # EDGE CASE: Window closed but we're more than 1 window behind
        if current_window > market_window + 300:
            logger.warning(f"Position from window {market_window} is stale (current: {current_window})")
            entry_price = position['entry_price']
            side = position['side']
            # Force settlement as loss
            exit_price = 0.0
            pnl_amount = -entry_price
            pnl_pct = -100.0
            return {
                'exit_price': exit_price,
                'pnl_amount': pnl_amount,
                'pnl_pct': pnl_pct,
                'settled': True,
                'result': 'STALE_LOSS',
            }
        
        # Window closed - get settlement result from Polymarket using streak bot logic
        settlement_result = self.feed.get_settlement_result(market_window)
        
        # Can't get settlement, retry next cycle
        if settlement_result is None:
            logger.debug(f"Settlement not available for window {market_window}, retrying...")
            return None
        
        outcome, (up_price, down_price) = settlement_result
        
        # Market closed but not resolved yet (umaResolutionStatus pending)
        if outcome == 'pending':
            logger.debug(f"Market {market_window} closed but not resolved yet, waiting...")
            return None
        
        entry_price = position['entry_price']
        side = position['side']
        
        # Determine winner based on Polymarket's official settlement
        # Using streak bot logic: outcome is 'up' or 'down'
        won = (side == outcome)
        exit_price = up_price if side == 'up' else down_price
        
        result = "WIN" if won else "LOSE"
        
        # Calculate settlement P&L
        if won:
            pnl_amount = 1.0 - entry_price  # Paid entry, get $1.00
        else:
            pnl_amount = -entry_price  # Paid entry, get $0.00
        
        pnl_pct = (pnl_amount / entry_price) * 100 if entry_price > 0 else 0
        
        return {
            'exit_price': exit_price,
            'pnl_amount': pnl_amount,
            'pnl_pct': pnl_pct,
            'settled': True,
            'result': result,
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
                logger.debug(f"Processing {len(self.open_positions)} open positions...")
                for strategy_name, position in list(self.open_positions.items()):
                    try:
                        logger.debug(f"Checking position: {strategy_name}")
                        # First check if window expired (settlement)
                        settlement = self.check_expiry_settlement(position)
                        
                        if settlement:
                            # Window closed - settle at expiry
                            del self.open_positions[strategy_name]
                            self.trades_executed += 1
                            
                            # Record close
                            closed_trade = self.reporter.record_trade_close(
                                trade_id=position['trade_id'],
                                exit_price=settlement['exit_price'],
                                pnl_pct=settlement['pnl_pct'],
                                exit_reason=f"expiry_{settlement['result'].lower()}",
                                duration_minutes=5.0,
                                pnl_amount=settlement['pnl_amount']
                            )
                            
                            # Push to GitHub (disabled for debugging)
                            # if closed_trade:
                            #     asyncio.create_task(self._push_trade_update(
                            #         len(self.reporter.closed_trades),
                            #         closed_trade
                            #     ))
                            
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
                        
                        logger.debug(f"Position {strategy_name}: hold_time={hold_time:.1f}s, price_change={price_change_pct:.2f}%, should_exit={should_exit_early}")
                        
                        if should_exit_early:
                            logger.info(f"Exiting {strategy_name} early: hold={hold_time:.1f}s, change={price_change_pct:.2f}%")
                            logger.debug(f"Calling execute_early_exit for {strategy_name}...")
                            exit_result = await self.execute_early_exit(position)
                            logger.debug(f"execute_early_exit returned: {exit_result}")
                            if exit_result:
                                del self.open_positions[strategy_name]
                                self.trades_executed += 1
                                
                                # Record close
                                logger.debug(f"Recording trade close for {position['trade_id']}...")
                                closed_trade = self.reporter.record_trade_close(
                                    trade_id=position['trade_id'],
                                    exit_price=exit_result['exit_price'],
                                    pnl_pct=exit_result['pnl_pct'],
                                    exit_reason='early_exit',
                                    duration_minutes=hold_time / 60,
                                    pnl_amount=exit_result['pnl_amount']
                                )
                                logger.debug(f"record_trade_close returned: {closed_trade}")
                                
                                # Push to GitHub (disabled for debugging)
                                # if closed_trade:
                                #     asyncio.create_task(self._push_trade_update(
                                #         len(self.reporter.closed_trades),
                                #         closed_trade
                                #     ))
                                
                                logger.info(f"🔒 Trade #{position['trade_id']} EARLY EXIT | {strategy_name} | P&L: ${exit_result['pnl_amount']:+.4f} ({exit_result['pnl_pct']:+.1f}%)")
                                
                    except Exception as e:
                        logger.error(f"Error processing position {strategy_name}: {e}")
                        import traceback
                        logger.error(traceback.format_exc())
                
                # Get entry signals
                logger.debug("Evaluating strategies...")
                signals = self.evaluate_strategies(market_data)
                logger.debug(f"Got {len(signals)} signals")
                
                for signal in signals:
                    logger.debug(f"Processing signal: {signal.strategy}")
                    # Execute entry
                    result = await self.execute_entry(signal)
                    if not result:
                        logger.debug(f"execute_entry returned None for {signal.strategy}")
                        continue
                    
                    logger.debug(f"Entry executed: {result}")
                    
                    # Record open
                    self.trade_counter += 1
                    trade_id = self.trade_counter
                    
                    logger.debug(f"Recording trade open: {trade_id}")
                    open_record = self.reporter.record_trade_open(
                        strategy_name=signal.strategy,
                        signal=signal,
                        entry_price=result['entry_price'],
                        entry_reason=signal.reason
                    )
                    
                    if not open_record:
                        logger.warning(f"Failed to record trade open for {signal.strategy}")
                        continue
                    
                    logger.debug(f"Trade recorded: {open_record}")
                    
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
                
                # Keep-alive log every minute
                if self.cycle % 12 == 0:
                    logger.info(f"💓 Keep-alive | Cycle {self.cycle} | Running normally")
                
                logger.debug("Sleeping 5 seconds...")
                await asyncio.sleep(5)
                logger.debug("Woke up")
                
            except asyncio.TimeoutError:
                logger.error("Cycle timeout!")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Error: {e}")
                import traceback
                logger.error(traceback.format_exc())
                await asyncio.sleep(5)
    
    async def _push_trade_update(self, trade_count: int, trade_data: dict):
        """Async wrapper for GitHub push."""
        try:
            await asyncio.to_thread(self.pusher.push_on_trade_close, trade_count, trade_data)
        except Exception as e:
            logger.error(f"GitHub push error: {e}")
    
    def stop(self):
        """Stop gracefully."""
        self.running = False
        logger.info("Stopping...")
        # Flush Excel before exiting
        try:
            self.reporter._write_excel()
            logger.info("Excel saved")
        except Exception as e:
            logger.error(f"Error saving Excel: {e}")


async def main():
    trader = PaperTrader()
    
    def handle_signal(sig, frame):
        logger.info(f"Received signal {sig}, stopping...")
        trader.stop()
    
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    
    try:
        await trader.run()
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        logger.info("Bot exiting")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Fatal error in main: {e}")
        import traceback
        traceback.print_exc()
