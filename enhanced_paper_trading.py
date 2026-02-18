"""
Enhanced Paper Trading Bot with Risk Management and Rate Limiting
Integrates new modules: rate_limiter, risk_manager, whale_tracker
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

# Core components
from core.base_strategy import Signal
from core.excel_reporter import ExcelReporter
from core.github_pusher import GitHubAutoPusher
from data.polymarket_feed import PolymarketDataFeed

# New risk and rate limiting modules
from rate_limiter import get_rate_limiter, EndpointCategory
from risk_manager import RiskManager, RiskLimits
from whale_tracker import WhaleTracker, WhaleCopyStrategy

# Strategies
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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('paper_trading.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('enhanced_paper_trader')


class EnhancedPaperTrader:
    """
    Enhanced paper trading bot with:
    - Token bucket rate limiting
    - Risk management with configurable limits
    - Whale tracking and copy-trading
    - Better async HTTP handling
    """
    
    def __init__(self):
        self.running = False
        self.cycle = 0
        self.trades_executed = 0
        self.trade_counter = 0
        
        # Rate limiter
        self.rate_limiter = get_rate_limiter()
        
        # Risk manager with default limits
        risk_limits = RiskLimits(
            max_order_size=100.0,
            max_position_size=500.0,
            max_total_exposure=1000.0,
            max_daily_loss=100.0,
            max_drawdown_pct=0.20,
            max_trades_per_hour=20,
            min_spread_pct=0.005,
            max_spread_pct=0.10
        )
        self.risk_manager = RiskManager(risk_limits)
        
        # Whale tracker (optional - can be enabled later)
        self.whale_tracker = WhaleTracker()
        self.whale_strategy = WhaleCopyStrategy(
            self.whale_tracker,
            min_confidence=70.0,
            position_size_pct=0.1,
            max_positions=3
        )
        
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
            EMAArbitrageStrategy(),
            LongshotBiasStrategy(),
            HighProbabilityBondStrategy(),
        ]
        
        # Register all strategies
        strategy_names = [s.name for s in self.strategies]
        self.reporter.register_strategies(strategy_names)
        
        # Track open positions
        self.open_positions: Dict[str, Dict] = {}
    
    def get_current_market_window(self) -> int:
        """Get current 5-minute market window timestamp."""
        return (int(time.time()) // 300) * 300

    def get_next_market_window(self) -> int:
        """Get next 5-minute market window timestamp."""
        return self.get_current_market_window() + 300

    def evaluate_strategies(self, market_data) -> List[Signal]:
        """Get signals from active (non-bankrupt) strategies with risk checks."""
        signals = []
        
        for strategy in self.strategies:
            if not self.reporter.is_strategy_active(strategy.name):
                continue
            
            # Check strategy-specific risk limits
            strategy_capital = self.reporter.get_strategy_capital(strategy.name)
            allowed, reason = self.risk_manager.check_strategy_limits(
                strategy.name, strategy_capital
            )
            
            if not allowed:
                logger.debug(f"Strategy {strategy.name} blocked: {reason}")
                continue
            
            try:
                signal = strategy.generate_signal(market_data)
                if signal and signal.confidence >= 0.6:
                    signals.append(signal)
            except Exception as e:
                logger.error(f"Strategy {strategy.name} error: {e}")
        
        return signals
    
    def calculate_early_exit_pnl(self, entry_price: float, exit_price: float, side: str) -> Tuple[float, float]:
        """Calculate P&L for early exit. Returns DOLLAR PnL."""
        trade_size = 5.0
        
        if side.lower() == 'down':
            pnl_per_share = entry_price - exit_price
        else:
            pnl_per_share = exit_price - entry_price
        
        pnl_dollars = pnl_per_share * trade_size
        pnl_pct = (pnl_per_share / entry_price) * 100 if entry_price > 0 else 0
        
        return pnl_dollars, pnl_pct
    
    async def execute_entry(self, signal: Signal) -> Optional[Dict]:
        """Open a new position with risk checks."""
        strategy_name = signal.strategy
        
        # Check if strategy already has open position
        if strategy_name in self.open_positions:
            logger.debug(f"{strategy_name} already has open position, skipping entry")
            return None
        
        # EDGE CASE: Don't enter in last 15 seconds of window
        time_in_window = time.time() % 300
        if time_in_window > 285:
            logger.debug(f"Too close to expiry ({time_in_window:.0f}s), skipping entry")
            return None
        
        # Get market data for risk checks
        market_data = self.feed.fetch_data()
        if not market_data:
            return None
        
        # Calculate spread for risk check
        spread_pct = 0.02  # Default 2% spread
        if hasattr(market_data, 'spread') and market_data.spread:
            mid = (market_data.best_bid + market_data.best_ask) / 2
            if mid > 0:
                spread_pct = market_data.spread / mid
        
        # Risk check
        strategy_capital = self.reporter.get_strategy_capital(strategy_name)
        allowed, reason = self.risk_manager.check_order_allowed(
            strategy_name=strategy_name,
            order_size=5.0,
            spread_pct=spread_pct,
            current_capital=strategy_capital
        )
        
        if not allowed:
            logger.warning(f"Risk check failed for {strategy_name}: {reason}")
            return None
        
        # Rate limit before API call
        await self.rate_limiter.acquire(EndpointCategory.MARKET_DATA, tokens=1)
        
        # Get entry fill
        entry_price, entry_slippage, entry_status = self.feed.simulate_fill(
            side=signal.signal,
            size_dollars=5.0
        )
        
        # Validate price
        if entry_price < 0.01 or entry_price > 0.99 or entry_price == 0.5:
            logger.warning(f"Invalid entry price: {entry_price}, skipping")
            return None
        
        if entry_status == "high_slippage":
            logger.warning(f"High slippage: {entry_slippage} bps, skipping")
            return None
        
        if entry_status == "no_fill":
            logger.warning(f"No fill available, skipping")
            return None
        
        market_window = self.get_next_market_window()
        strike_price = self.feed.get_strike_price()
        
        if strike_price is None:
            logger.warning(f"No strike price available, skipping")
            return None
        
        logger.info(f"Entry: {entry_price:.4f} | Strategy: {strategy_name} | Window: {market_window}")
        
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
        
        # Rate limit before API call
        await self.rate_limiter.acquire(EndpointCategory.MARKET_DATA, tokens=1)
        
        exit_price, exit_slippage, exit_status = self.feed.simulate_fill(
            side=side,
            size_dollars=5.0
        )
        
        if exit_price == 0 or exit_price == 0.5:
            logger.warning(f"No fill for exit: {exit_status}, using entry price")
            exit_price = entry_price
            exit_slippage = 0
        
        pnl_amount, pnl_pct = self.calculate_early_exit_pnl(entry_price, exit_price, side)
        
        return {
            'exit_price': exit_price,
            'exit_slippage_bps': exit_slippage,
            'pnl_amount': pnl_amount,
            'pnl_pct': pnl_pct,
            'settled': False,
        }
    
    def check_expiry_settlement(self, position: Dict) -> Optional[Dict]:
        """Check if position has reached expiry and settle it."""
        market_window = position['market_window']
        current_window = self.get_current_market_window()
        
        if current_window <= market_window:
            return None
        
        if current_window > market_window + 300:
            logger.warning(f"Position from window {market_window} is stale")
            entry_price = position['entry_price']
            side = position['side']
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
        
        settlement_result = self.feed.get_settlement_result(market_window)
        
        if settlement_result is None:
            logger.debug(f"Settlement not available for window {market_window}, retrying...")
            return None
        
        outcome, (up_price, down_price) = settlement_result
        
        if outcome == 'pending':
            logger.debug(f"Market {market_window} closed but not resolved yet, waiting...")
            return None
        
        entry_price = position['entry_price']
        side = position['side']
        
        won = (side == outcome)
        exit_price = up_price if side == 'up' else down_price
        
        result = "WIN" if won else "LOSE"
        
        if won:
            pnl_amount = 1.0 - entry_price
        else:
            pnl_amount = -entry_price
        
        pnl_pct = (pnl_amount / entry_price) * 100 if entry_price > 0 else 0
        
        return {
            'exit_price': exit_price,
            'pnl_amount': pnl_amount,
            'pnl_pct': pnl_pct,
            'settled': True,
            'result': result,
        }
    
    async def run(self):
        """Main trading loop with enhanced monitoring."""
        self.running = True
        
        logger.info("=" * 70)
        logger.info("🚀 ENHANCED PAPER TRADING BOT - BTC 5-min Markets")
        logger.info("=" * 70)
        logger.info(f"Strategies: {len(self.strategies)}")
        logger.info("Risk Limits:")
        limits = self.risk_manager.limits
        logger.info(f"  Max Order: ${limits.max_order_size}")
        logger.info(f"  Max Exposure: ${limits.max_total_exposure}")
        logger.info(f"  Max Daily Loss: ${limits.max_daily_loss}")
        logger.info(f"  Max Drawdown: {limits.max_drawdown_pct:.0%}")
        logger.info("=" * 70)
        
        while self.running:
            try:
                self.cycle += 1
                current_time = datetime.now()
                
                # Get market data with rate limiting
                await self.rate_limiter.acquire(EndpointCategory.GAMMA_API, tokens=1)
                
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
                
                # Process open positions
                await self._process_positions(current_time)
                
                # Get entry signals
                signals = self.evaluate_strategies(market_data)
                
                for signal in signals:
                    result = await self.execute_entry(signal)
                    if not result:
                        continue
                    
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
                    
                    # Record trade in risk manager
                    self.risk_manager.record_trade(
                        strategy_name=signal.strategy,
                        market_id=str(result['market_window']),
                        side=signal.signal.upper(),
                        size=5.0,
                        price=result['entry_price']
                    )
                    
                    self.open_positions[signal.strategy] = {
                        'trade_id': trade_id,
                        'entry_time': current_time,
                        'market_window': result['market_window'],
                        'strike_price': result['strike_price'],
                        'entry_price': result['entry_price'],
                        'side': result['side'],
                    }
                    
                    logger.info(f"🔓 Trade #{trade_id} opened | {signal.strategy} | Price: {result['entry_price']:.4f}")
                
                # Periodic status with risk report
                if self.cycle % 10 == 0:
                    risk_report = self.risk_manager.get_risk_report()
                    logger.info(f"📊 Cycle {self.cycle} | Open: {len(self.open_positions)} | Closed: {self.trades_executed}")
                    logger.info(f"   Daily P&L: ${risk_report['daily_pnl']:+.2f} | Exposure: ${risk_report['current_exposure']:.2f}")
                
                # Rate limiter status every 5 minutes
                if self.cycle % 60 == 0:
                    status = self.rate_limiter.get_status()
                    for category, info in status.items():
                        if info['is_throttled']:
                            logger.warning(f"Rate limiter throttled: {category}")
                
                await asyncio.sleep(5)
                
            except asyncio.TimeoutError:
                logger.error("Cycle timeout!")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Error: {e}")
                import traceback
                logger.error(traceback.format_exc())
                await asyncio.sleep(5)
    
    async def _process_positions(self, current_time: datetime):
        """Process all open positions."""
        for strategy_name, position in list(self.open_positions.items()):
            try:
                # Check expiry settlement
                settlement = self.check_expiry_settlement(position)
                
                if settlement:
                    del self.open_positions[strategy_name]
                    self.trades_executed += 1
                    
                    # Record in risk manager
                    self.risk_manager.record_trade(
                        strategy_name=strategy_name,
                        market_id=str(position['market_window']),
                        side="EXIT",
                        size=5.0,
                        price=settlement['exit_price'],
                        pnl=settlement['pnl_amount']
                    )
                    
                    # Record close
                    closed_trade = self.reporter.record_trade_close(
                        trade_id=position['trade_id'],
                        exit_price=settlement['exit_price'],
                        pnl_pct=settlement['pnl_pct'],
                        exit_reason=f"expiry_{settlement['result'].lower()}",
                        duration_minutes=5.0,
                        pnl_amount=settlement['pnl_amount']
                    )
                    
                    logger.info(f"🔒 Trade #{position['trade_id']} SETTLED | {strategy_name} | {settlement['result']} | P&L: ${settlement['pnl_amount']:+.4f}")
                    continue
                
                # Check for early exit
                entry_time = position.get('entry_time', current_time)
                hold_time = (current_time - entry_time).total_seconds()
                
                entry_price = position['entry_price']
                current_price_data = self.feed.fetch_data()
                if current_price_data and hasattr(current_price_data, 'price'):
                    current_price = current_price_data.price
                    price_change_pct = abs(current_price - entry_price) / entry_price * 100
                else:
                    price_change_pct = 0
                
                should_exit_early = hold_time >= 300 or price_change_pct >= 10
                
                if should_exit_early:
                    exit_result = await self.execute_early_exit(position)
                    if exit_result:
                        del self.open_positions[strategy_name]
                        self.trades_executed += 1
                        
                        # Record in risk manager
                        self.risk_manager.record_trade(
                            strategy_name=strategy_name,
                            market_id=str(position['market_window']),
                            side="EXIT",
                            size=5.0,
                            price=exit_result['exit_price'],
                            pnl=exit_result['pnl_amount']
                        )
                        
                        closed_trade = self.reporter.record_trade_close(
                            trade_id=position['trade_id'],
                            exit_price=exit_result['exit_price'],
                            pnl_pct=exit_result['pnl_pct'],
                            exit_reason='early_exit',
                            duration_minutes=hold_time / 60,
                            pnl_amount=exit_result['pnl_amount']
                        )
                        
                        logger.info(f"🔒 Trade #{position['trade_id']} EARLY EXIT | {strategy_name} | P&L: ${exit_result['pnl_amount']:+.4f}")
                        
            except Exception as e:
                logger.error(f"Error processing position {strategy_name}: {e}")
                import traceback
                logger.error(traceback.format_exc())

    def shutdown(self):
        """Graceful shutdown."""
        logger.info("Shutting down enhanced paper trader...")
        self.running = False


async def main():
    trader = EnhancedPaperTrader()
    
    def signal_handler(sig, frame):
        trader.shutdown()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        await trader.run()
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        logger.error(traceback.format_exc())


if __name__ == "__main__":
    asyncio.run(main())
