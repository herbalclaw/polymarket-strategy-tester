#!/usr/bin/env python3
"""
Auto-integrator: Automatically adds discovered strategies to paper trading.
Runs continuously alongside the main paper trading bot.
"""

import asyncio
import json
import logging
import sqlite3
import sys
import importlib.util
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Type

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.base_strategy import BaseStrategy
from core.strategy_engine import StrategyEngine

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('auto_integrator.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('auto_integrator')


class StrategyAutoIntegrator:
    """Automatically integrates discovered strategies into paper trading."""
    
    def __init__(self, discovery_db_path: str = "discovery_data/strategies.db"):
        self.discovery_db = Path(discovery_db_path)
        self.discovered_dir = Path("strategies/discovered")
        self.integrated_strategies: Dict[str, Type[BaseStrategy]] = {}
        self.last_check = None
        
    def get_new_strategies(self) -> List[Dict]:
        """Get strategies discovered since last check."""
        if not self.discovery_db.exists():
            logger.warning("Discovery database not found")
            return []
        
        conn = sqlite3.connect(self.discovery_db)
        cursor = conn.cursor()
        
        if self.last_check:
            cursor.execute('''
                SELECT strategy_name, wallet_source, strategy_code, description
                FROM deciphered_strategies
                WHERE active = 1 AND created_at > ? OR updated_at > ?
            ''', (self.last_check, self.last_check))
        else:
            cursor.execute('''
                SELECT strategy_name, wallet_source, strategy_code, description
                FROM deciphered_strategies
                WHERE active = 1
            ''')
        
        strategies = []
        for row in cursor.fetchall():
            strategies.append({
                'name': row[0],
                'wallet': row[1],
                'code': row[2],
                'description': json.loads(row[3]) if row[3] else {}
            })
        
        conn.close()
        self.last_check = datetime.now().isoformat()
        
        return strategies
    
    def load_strategy_class(self, strategy_file: Path) -> Type[BaseStrategy]:
        """Dynamically load a strategy class from file."""
        try:
            module_name = strategy_file.stem
            spec = importlib.util.spec_from_file_location(module_name, strategy_file)
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            
            # Find the strategy class
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type) and 
                    issubclass(attr, BaseStrategy) and 
                    attr != BaseStrategy):
                    return attr
            
            logger.error(f"No strategy class found in {strategy_file}")
            return None
            
        except Exception as e:
            logger.error(f"Error loading strategy from {strategy_file}: {e}")
            return None
    
    def integrate_strategy(self, strategy_info: Dict) -> bool:
        """Integrate a discovered strategy into the engine."""
        name = strategy_info['name']
        
        if name in self.integrated_strategies:
            logger.info(f"Strategy {name} already integrated")
            return False
        
        # Find the strategy file
        strategy_file = self.discovered_dir / f"{name.lower()}.py"
        if not strategy_file.exists():
            logger.error(f"Strategy file not found: {strategy_file}")
            return False
        
        # Load the class
        strategy_class = self.load_strategy_class(strategy_file)
        if not strategy_class:
            return False
        
        # Store for later integration
        self.integrated_strategies[name] = strategy_class
        
        desc = strategy_info.get('description', {})
        logger.info(f"✅ Integrated strategy: {name}")
        logger.info(f"   Type: {desc.get('type', 'unknown')}")
        logger.info(f"   Confidence: {desc.get('confidence', 0):.2%}")
        logger.info(f"   Signals: {len(desc.get('key_signals', []))}")
        
        return True
    
    def get_integrated_instances(self) -> List[BaseStrategy]:
        """Get instances of all integrated strategies."""
        instances = []
        for name, strategy_class in self.integrated_strategies.items():
            try:
                instance = strategy_class()
                instances.append(instance)
            except Exception as e:
                logger.error(f"Error instantiating {name}: {e}")
        return instances
    
    async def run_continuous(self, engine: StrategyEngine, check_interval: int = 300):
        """Continuously check for and integrate new strategies."""
        logger.info("Starting auto-integrator...")
        
        while True:
            try:
                # Check for new strategies
                new_strategies = self.get_new_strategies()
                
                integrated_count = 0
                for strat in new_strategies:
                    if self.integrate_strategy(strat):
                        integrated_count += 1
                
                if integrated_count > 0:
                    # Get fresh instances and update engine
                    new_instances = self.get_integrated_instances()
                    
                    # Add to engine
                    for instance in new_instances:
                        if instance.name not in [s.name for s in engine.strategies]:
                            engine.strategies.append(instance)
                            logger.info(f"🚀 Added {instance.name} to active trading")
                
                # Wait before next check
                await asyncio.sleep(check_interval)
                
            except Exception as e:
                logger.error(f"Error in auto-integrator: {e}")
                await asyncio.sleep(60)


def create_discovered_strategy_template(wallet: str, pattern_type: str) -> str:
    """Create a strategy template based on discovered pattern type."""
    
    templates = {
        'latency_arbitrage': '''
class DiscoveredLatencyArbitrage_{wallet_short}(BaseStrategy):
    """Latency arbitrage strategy discovered from wallet analysis."""
    
    def __init__(self):
        super().__init__(name="Discovered_LatencyArb_{wallet_short}", confidence_threshold=0.7)
        self.price_history = []
        self.max_history = 100
        
    def generate_signal(self, data: dict) -> Optional[Signal]:
        prices = data.get('prices', {})
        polymarket = prices.get('polymarket', {})
        
        if not polymarket:
            return None
        
        # Track price history
        mid = (polymarket.get('bid', 0) + polymarket.get('ask', 1)) / 2
        self.price_history.append(mid)
        if len(self.price_history) > self.max_history:
            self.price_history.pop(0)
        
        # Need minimum history
        if len(self.price_history) < 10:
            return None
        
        # Detect rapid price movements (latency opportunity)
        recent = self.price_history[-5:]
        older = self.price_history[-10:-5]
        
        if not older:
            return None
        
        recent_avg = sum(recent) / len(recent)
        older_avg = sum(older) / len(older)
        
        change_pct = (recent_avg - older_avg) / older_avg if older_avg > 0 else 0
        
        # Fast momentum signal
        if abs(change_pct) > 0.01:  # 1% move
            signal_type = "UP" if change_pct > 0 else "DOWN"
            confidence = min(0.95, 0.6 + abs(change_pct) * 10)
            
            return Signal(
                type=signal_type,
                confidence=confidence,
                reason=f"Latency arb: {change_pct:.2%} price move detected",
                metadata={{'change_pct': change_pct, 'wallet_source': '{wallet}'}}
            )
        
        return None
''',
        'high_conviction': '''
class DiscoveredHighConviction_{wallet_short}(BaseStrategy):
    """High conviction selective strategy discovered from wallet analysis."""
    
    def __init__(self):
        super().__init__(name="Discovered_HighConviction_{wallet_short}", confidence_threshold=0.75)
        self.consecutive_signals = 0
        self.last_signal_type = None
        
    def generate_signal(self, data: dict) -> Optional[Signal]:
        prices = data.get('prices', {})
        sentiment = data.get('sentiment', {})
        
        polymarket = prices.get('polymarket', {})
        if not polymarket:
            return None
        
        mid = (polymarket.get('bid', 0) + polymarket.get('ask', 1)) / 2
        
        # Require multiple confirming factors
        factors = 0
        signal_type = None
        
        # Factor 1: Sentiment alignment
        fear_greed = sentiment.get('fear_greed_index', 50)
        if fear_greed > 65:
            factors += 1
            signal_type = "UP"
        elif fear_greed < 35:
            factors += 1
            signal_type = "DOWN"
        
        # Factor 2: Price momentum
        vwap = prices.get('vwap', {})
        if vwap:
            vwap_price = vwap.get('price', mid)
            if mid > vwap_price * 1.002:
                factors += 1
                signal_type = "UP"
            elif mid < vwap_price * 0.998:
                factors += 1
                signal_type = "DOWN"
        
        # Factor 3: Exchange consensus
        exchange_prices = [p for k, p in prices.items() if k not in ['polymarket', 'vwap']]
        if exchange_prices:
            avg_price = sum(ep.get('price', 0) for ep in exchange_prices) / len(exchange_prices)
            if abs(mid - avg_price) > 0.005:
                factors += 1
                signal_type = "UP" if mid > avg_price else "DOWN"
        
        # Need at least 2 factors for high conviction
        if factors >= 2 and signal_type:
            confidence = 0.7 + (factors * 0.08)
            
            return Signal(
                type=signal_type,
                confidence=min(0.95, confidence),
                reason=f"High conviction: {factors}/3 factors aligned",
                metadata={{'factors': factors, 'wallet_source': '{wallet}'}}
            )
        
        return None
''',
        'multi_strategy': '''
class DiscoveredMultiStrategy_{wallet_short}(BaseStrategy):
    """Multi-strategy algorithmic approach discovered from wallet analysis."""
    
    def __init__(self):
        super().__init__(name="Discovered_MultiStrat_{wallet_short}", confidence_threshold=0.65)
        self.sub_strategies = ['momentum', 'mean_reversion', 'breakout']
        self.strategy_scores = {{s: 0 for s in self.sub_strategies}}
        
    def generate_signal(self, data: dict) -> Optional[Signal]:
        prices = data.get('prices', {})
        polymarket = prices.get('polymarket', {})
        
        if not polymarket:
            return None
        
        mid = (polymarket.get('bid', 0) + polymarket.get('ask', 1)) / 2
        signals = []
        
        # Sub-strategy 1: Momentum
        if hasattr(self, '_momentum_signal'):
            mom = self._momentum_signal(data)
            if mom:
                signals.append(mom)
                self.strategy_scores['momentum'] += 1
        
        # Sub-strategy 2: Mean reversion
        vwap = prices.get('vwap', {})
        if vwap:
            vwap_price = vwap.get('price', mid)
            deviation = (mid - vwap_price) / vwap_price if vwap_price > 0 else 0
            
            if abs(deviation) > 0.008:
                signal_type = "DOWN" if deviation > 0 else "UP"
                signals.append({{
                    'type': signal_type,
                    'confidence': 0.65 + abs(deviation) * 5,
                    'strategy': 'mean_reversion'
                }})
                self.strategy_scores['mean_reversion'] += 1
        
        # Sub-strategy 3: Breakout
        if hasattr(self, '_breakout_signal'):
            brk = self._breakout_signal(data)
            if brk:
                signals.append(brk)
                self.strategy_scores['breakout'] += 1
        
        # Combine signals
        if signals:
            # Weight by strategy performance
            weighted_signals = []
            for s in signals:
                weight = 1 + self.strategy_scores.get(s.get('strategy', ''), 0) * 0.1
                weighted_signals.append({
                    **s,
                    'weighted_confidence': s['confidence'] * weight
                })
            
            best = max(weighted_signals, key=lambda x: x['weighted_confidence'])
            
            return Signal(
                type=best['type'],
                confidence=min(0.95, best['weighted_confidence']),
                reason=f"Multi-strat: {best.get('strategy', 'unknown')} selected",
                metadata={{
                    'sub_strategy': best.get('strategy'),
                    'wallet_source': '{wallet}',
                    'strategy_scores': self.strategy_scores.copy()
                }}
            )
        
        return None
'''
    }
    
    template = templates.get(pattern_type, templates['high_conviction'])
    return template.format(wallet=wallet, wallet_short=wallet[:6])


async def main():
    """Run auto-integrator standalone."""
    integrator = StrategyAutoIntegrator()
    
    # Create mock engine for testing
    from data.price_feed import PriceFeed
    
    feed = PriceFeed()
    engine = StrategyEngine(feed)
    
    try:
        await integrator.run_continuous(engine)
    except KeyboardInterrupt:
        logger.info("Auto-integrator stopped")


if __name__ == "__main__":
    asyncio.run(main())
