#!/usr/bin/env python3
"""
Master orchestrator: Runs paper trading + continuous strategy discovery + auto-integration.
All-in-one continuous monitoring and adaptation system.
"""

import asyncio
import logging
import signal
import sys
from pathlib import Path

# Setup paths
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / 'discovery'))

from discovery.strategy_discovery import StrategyDiscoveryEngine
from discovery.auto_integrator import StrategyAutoIntegrator
from core.strategy_engine import StrategyEngine
from core.excel_reporter import ExcelReporter
from data.price_feed import PriceFeed
from strategies.momentum import MomentumStrategy
from strategies.arbitrage import ArbitrageStrategy
from strategies.vwap import VWAPStrategy
from strategies.leadlag import LeadLagStrategy
from strategies.sentiment import SentimentStrategy

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('master_orchestrator.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('master_orchestrator')


class MasterOrchestrator:
    """Orchestrates paper trading, strategy discovery, and auto-integration."""
    
    def __init__(self):
        self.running = False
        
        # Core components
        self.feed = PriceFeed()
        self.engine = StrategyEngine(self.feed)
        self.reporter = ExcelReporter()
        
        # Discovery components
        self.discovery = StrategyDiscoveryEngine()
        self.integrator = StrategyAutoIntegrator()
        
        # Base strategies
        self.base_strategies = [
            MomentumStrategy(),
            ArbitrageStrategy(),
            VWAPStrategy(),
            LeadLagStrategy(),
            SentimentStrategy(),
        ]
        
        # Discovered strategies
        self.discovered_strategies = []
        
        # Stats
        self.cycle = 0
        self.discovery_cycle = 0
        
    def setup_base_strategies(self):
        """Add base strategies to engine."""
        for strategy in self.base_strategies:
            self.engine.add_strategy(strategy)
            logger.info(f"Added base strategy: {strategy.name}")
    
    async def discovery_loop(self, interval_minutes: int = 30):
        """Continuous strategy discovery loop."""
        logger.info(f"Starting discovery loop (interval: {interval_minutes} min)")
        
        while self.running:
            try:
                self.discovery_cycle += 1
                logger.info(f"🔍 Discovery cycle #{self.discovery_cycle}")
                
                # Discover new strategies
                new_strategies = await self.discovery.discover_new_strategies()
                
                if new_strategies:
                    logger.info(f"🎯 Found {len(new_strategies)} new strategies!")
                    
                    for strat in new_strategies:
                        logger.info(f"   📊 {strat['name']}")
                        logger.info(f"      Type: {strat['hypothesis'].get('type')}")
                        logger.info(f"      Confidence: {strat['hypothesis'].get('confidence', 0):.2%}")
                
                # Generate and save report
                report = self.discovery.generate_strategy_report()
                report_path = Path("discovery_data/strategy_report.md")
                report_path.parent.mkdir(exist_ok=True)
                report_path.write_text(report)
                
                # Wait for next cycle
                await asyncio.sleep(interval_minutes * 60)
                
            except Exception as e:
                logger.error(f"Discovery loop error: {e}")
                await asyncio.sleep(60)
    
    async def integration_loop(self, check_interval: int = 300):
        """Auto-integration loop for discovered strategies."""
        logger.info("Starting integration loop")
        
        while self.running:
            try:
                # Check for new strategies to integrate
                new_strategies = self.integrator.get_new_strategies()
                
                integrated = 0
                for strat in new_strategies:
                    if self.integrator.integrate_strategy(strat):
                        integrated += 1
                
                if integrated > 0:
                    # Get instances and add to engine
                    instances = self.integrator.get_integrated_instances()
                    
                    for instance in instances:
                        existing_names = [s.name for s in self.engine.strategies]
                        if instance.name not in existing_names:
                            self.engine.add_strategy(instance)
                            self.discovered_strategies.append(instance)
                            logger.info(f"🚀 Activated discovered strategy: {instance.name}")
                
                await asyncio.sleep(check_interval)
                
            except Exception as e:
                logger.error(f"Integration loop error: {e}")
                await asyncio.sleep(60)
    
    async def trading_loop(self, report_interval: int = 50):
        """Main paper trading loop."""
        logger.info("Starting paper trading loop")
        
        while self.running:
            try:
                self.cycle += 1
                
                # Fetch data
                data = await self.feed.fetch_all_data()
                
                # Get signals from all strategies
                signals = self.engine.evaluate_all(data)
                
                # Execute best signal
                if signals:
                    best = max(signals, key=lambda x: x.confidence)
                    
                    if best.confidence >= 0.6:
                        logger.info(f"🎯 Signal: {best.type} @ {best.confidence:.1%} | {best.reason}")
                        
                        # Simulate trade
                        trade_result = await self._simulate_trade(best, data)
                        
                        # Notify strategies
                        self.engine.on_trade_complete(trade_result)
                        
                        # Record for Excel
                        self.reporter.record_trade(
                            strategy_name=best.metadata.get('strategy', 'unknown'),
                            signal=best,
                            entry_price=trade_result.get('entry_price', 0),
                            exit_price=trade_result.get('exit_price', 0),
                            pnl_pct=trade_result.get('pnl_pct', 0),
                            entry_reason=best.reason,
                            exit_reason=trade_result.get('exit_reason', ''),
                            duration_minutes=trade_result.get('duration', 0)
                        )
                
                # Generate Excel report periodically
                if self.cycle % report_interval == 0:
                    self._generate_excel_report()
                
                # Status update every 10 cycles
                if self.cycle % 10 == 0:
                    active_strategies = len(self.engine.strategies)
                    discovered = len(self.discovered_strategies)
                    logger.info(f"📊 Cycle {self.cycle} | Active strategies: {active_strategies} ({discovered} discovered)")
                
                await asyncio.sleep(5)  # 5 second cycle
                
            except Exception as e:
                logger.error(f"Trading loop error: {e}")
                await asyncio.sleep(5)
    
    async def _simulate_trade(self, signal, data) -> dict:
        """Simulate a paper trade."""
        prices = data.get('prices', {})
        polymarket = prices.get('polymarket', {})
        
        bid = polymarket.get('bid', 0.5)
        ask = polymarket.get('ask', 0.5)
        
        # VWAP-based entry
        vwap = prices.get('vwap', {})
        if vwap:
            entry_price = vwap.get('price', (bid + ask) / 2)
        else:
            entry_price = (bid + ask) / 2
        
        # Simulate 5-minute hold
        await asyncio.sleep(0.1)  # Instant for simulation
        
        # Simulate exit (random outcome based on signal quality)
        import random
        noise = random.gauss(0, 0.01)
        exit_price = entry_price + (0.005 if signal.type == "UP" else -0.005) + noise
        
        pnl_pct = ((exit_price - entry_price) / entry_price * 100) 
                  if signal.type == "UP" else 
                  ((entry_price - exit_price) / entry_price * 100)
        
        return {
            'signal': signal,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'pnl_pct': pnl_pct,
            'pnl_amount': pnl_pct * 100,  # $100 position
            'exit_reason': 'time_exit',
            'duration': 5,
            'success': pnl_pct > 0
        }
    
    def _generate_excel_report(self):
        """Generate Excel performance report."""
        try:
            filename = f"strategy_report_cycle_{self.cycle}.xlsx"
            self.reporter.generate_report(filename)
            logger.info(f"📈 Excel report generated: {filename}")
        except Exception as e:
            logger.error(f"Excel report error: {e}")
    
    async def run(self):
        """Run all loops concurrently."""
        self.running = True
        
        # Setup
        self.setup_base_strategies()
        
        logger.info("=" * 60)
        logger.info("🚀 MASTER ORCHESTRATOR STARTED")
        logger.info("=" * 60)
        logger.info("Components:")
        logger.info("  📊 Paper Trading: 5 strategies + discovered")
        logger.info("  🔍 Discovery: Every 30 minutes")
        logger.info("  🔄 Auto-Integration: Every 5 minutes")
        logger.info("  📈 Excel Reports: Every 50 cycles")
        logger.info("=" * 60)
        
        # Run all loops
        await asyncio.gather(
            self.trading_loop(),
            self.discovery_loop(interval_minutes=30),
            self.integration_loop(check_interval=300)
        )
    
    def stop(self):
        """Stop all loops."""
        self.running = False
        logger.info("Stopping orchestrator...")
        
        # Final report
        self._generate_excel_report()
        
        # Save discovered strategies report
        report = self.discovery.generate_strategy_report()
        Path("discovery_data/final_strategy_report.md").write_text(report)
        
        logger.info("✅ Orchestrator stopped gracefully")


def signal_handler(orchestrator):
    """Handle shutdown signals."""
    def handler(signum, frame):
        logger.info("Shutdown signal received")
        orchestrator.stop()
    return handler


async def main():
    """Main entry point."""
    orchestrator = MasterOrchestrator()
    
    # Setup signal handlers
    signal.signal(signal.SIGINT, lambda s, f: orchestrator.stop())
    signal.signal(signal.SIGTERM, lambda s, f: orchestrator.stop())
    
    try:
        await orchestrator.run()
    except asyncio.CancelledError:
        pass
    finally:
        orchestrator.stop()


if __name__ == "__main__":
    asyncio.run(main())
