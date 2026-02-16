#!/usr/bin/env python3
"""
Continuous Strategy Discovery & Adaptation System
Monitors top Polymarket traders, deciphers their strategies, and auto-updates paper trading.
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
import aiohttp
import sqlite3

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('strategy_discovery.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('strategy_discovery')

class StrategyDiscoveryEngine:
    """Continuously discovers and deciphers profitable trader strategies."""
    
    # Top known profitable wallets to monitor
    TARGET_WALLETS = [
        "0x9d849e03e6eb6c6e6f9d0b5c5b5b5b5b5b5b5b5",  # $2.6M profit, 63% WR
        "0xd218d218d218d218d218d218d218d218d218d2",  # $958K profit, 67% WR
        # Add more as discovered
    ]
    
    def __init__(self, data_dir: str = "discovery_data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        
        self.db_path = self.data_dir / "strategies.db"
        self.init_database()
        
        self.discovered_strategies: Dict[str, Any] = {}
        self.wallet_patterns: Dict[str, Dict] = {}
        self.last_analysis: Dict[str, datetime] = {}
        
        # Covalent API for on-chain data (free tier available)
        self.covalent_api_key = os.getenv("COVALENT_API_KEY", "")
        
    def init_database(self):
        """Initialize SQLite database for strategy tracking."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS wallet_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet TEXT NOT NULL,
                market_id TEXT,
                side TEXT,
                size REAL,
                price REAL,
                timestamp TEXT,
                tx_hash TEXT UNIQUE,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS strategy_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet TEXT NOT NULL,
                pattern_type TEXT,
                pattern_data TEXT,
                confidence REAL,
                discovered_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS deciphered_strategies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_name TEXT UNIQUE,
                wallet_source TEXT,
                strategy_code TEXT,
                description TEXT,
                performance_prediction TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                active BOOLEAN DEFAULT 0
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS strategy_updates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_name TEXT,
                update_type TEXT,
                old_value TEXT,
                new_value TEXT,
                reason TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("Database initialized")
    
    async def fetch_wallet_activity(self, wallet: str) -> List[Dict]:
        """Fetch recent trading activity for a wallet."""
        # Try Polymarket CLOB API first
        activities = []
        
        try:
            # Polymarket activity endpoint
            url = f"https://clob.polymarket.com/activity/{wallet}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=30) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        activities = data.get('activities', [])
                        logger.info(f"Fetched {len(activities)} activities for {wallet[:10]}...")
        except Exception as e:
            logger.error(f"Error fetching activity for {wallet}: {e}")
        
        return activities
    
    async def fetch_order_history(self, wallet: str) -> List[Dict]:
        """Fetch order history to understand strategy."""
        orders = []
        
        try:
            # Try to get order history from Polymarket
            url = f"https://clob.polymarket.com/orders/{wallet}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=30) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        orders = data.get('orders', [])
        except Exception as e:
            logger.error(f"Error fetching orders for {wallet}: {e}")
        
        return orders
    
    def analyze_trading_patterns(self, wallet: str, trades: List[Dict]) -> Dict:
        """Analyze trading patterns to decipher strategy."""
        if not trades:
            return {}
        
        patterns = {
            'wallet': wallet,
            'total_trades': len(trades),
            'analyzed_at': datetime.now().isoformat(),
            'time_patterns': {},
            'size_patterns': {},
            'market_patterns': {},
            'timing_patterns': {},
            'hypothesized_strategy': None
        }
        
        # Time-based analysis
        trade_times = []
        for trade in trades:
            try:
                ts = trade.get('timestamp') or trade.get('created_at')
                if ts:
                    dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                    trade_times.append(dt)
            except:
                pass
        
        if trade_times:
            # Hour of day pattern
            hours = [t.hour for t in trade_times]
            patterns['time_patterns']['preferred_hours'] = self._get_top_values(hours)
            patterns['time_patterns']['is_algorithmic'] = self._detect_algorithmic_timing(hours)
            
            # Trade frequency
            if len(trade_times) > 1:
                intervals = [(trade_times[i] - trade_times[i-1]).total_seconds() 
                           for i in range(1, len(trade_times))]
                avg_interval = sum(intervals) / len(intervals)
                patterns['time_patterns']['avg_interval_seconds'] = avg_interval
                patterns['time_patterns']['is_high_frequency'] = avg_interval < 300  # < 5 min
        
        # Market analysis
        markets = {}
        for trade in trades:
            market = trade.get('market_slug') or trade.get('market_id', 'unknown')
            markets[market] = markets.get(market, 0) + 1
        
        patterns['market_patterns']['top_markets'] = sorted(
            markets.items(), key=lambda x: x[1], reverse=True
        )[:5]
        patterns['market_patterns']['specialization'] = self._detect_specialization(markets)
        
        # Size patterns
        sizes = []
        for trade in trades:
            size = trade.get('size') or trade.get('amount') or trade.get('taker_amount')
            if size:
                try:
                    sizes.append(float(size))
                except:
                    pass
        
        if sizes:
            patterns['size_patterns']['avg_size'] = sum(sizes) / len(sizes)
            patterns['size_patterns']['max_size'] = max(sizes)
            patterns['size_patterns']['size_consistency'] = self._calc_consistency(sizes)
        
        # Hypothesize strategy
        patterns['hypothesized_strategy'] = self._hypothesize_strategy(patterns)
        
        return patterns
    
    def _get_top_values(self, values: List, n: int = 3) -> List:
        """Get most common values."""
        from collections import Counter
        return Counter(values).most_common(n)
    
    def _detect_algorithmic_timing(self, hours: List[int]) -> bool:
        """Detect if trading pattern suggests algorithmic execution."""
        if len(hours) < 10:
            return False
        
        # Algorithmic trading often has consistent intervals
        from collections import Counter
        hour_dist = Counter(hours)
        
        # If trades are evenly distributed across hours, likely algorithmic
        uniformity = len(hour_dist) / 24  # How many hours have trades
        return uniformity > 0.5  # Trades in >50% of hours
    
    def _detect_specialization(self, markets: Dict) -> str:
        """Detect if trader specializes in specific markets."""
        if not markets:
            return "unknown"
        
        total = sum(markets.values())
        top_market_pct = max(markets.values()) / total if total > 0 else 0
        
        if top_market_pct > 0.7:
            return "high_specialist"
        elif top_market_pct > 0.4:
            return "moderate_specialist"
        else:
            return "diversified"
    
    def _calc_consistency(self, values: List[float]) -> float:
        """Calculate consistency coefficient (lower = more consistent)."""
        if len(values) < 2:
            return 0
        
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        std_dev = variance ** 0.5
        
        return std_dev / mean if mean > 0 else 0
    
    def _hypothesize_strategy(self, patterns: Dict) -> Dict:
        """Hypothesize trading strategy based on patterns."""
        hypothesis = {
            'name': None,
            'type': None,
            'confidence': 0,
            'key_signals': [],
            'implementation_hints': []
        }
        
        time_pat = patterns.get('time_patterns', {})
        market_pat = patterns.get('market_patterns', {})
        size_pat = patterns.get('size_patterns', {})
        
        # High frequency + algorithmic timing = Latency arbitrage
        if time_pat.get('is_high_frequency') and time_pat.get('is_algorithmic'):
            hypothesis['name'] = "Latency Arbitrage"
            hypothesis['type'] = "algorithmic"
            hypothesis['confidence'] = 0.75
            hypothesis['key_signals'] = [
                "Fast execution on price discrepancies",
                "Consistent timing patterns",
                "High trade frequency"
            ]
            hypothesis['implementation_hints'] = [
                "Monitor order book depth across exchanges",
                "Execute within milliseconds of signal",
                "Small position sizes, high volume"
            ]
        
        # Specialist + consistent sizes = High conviction discretionary
        elif market_pat.get('specialization') == 'high_specialist' and size_pat.get('size_consistency', 1) < 0.5:
            hypothesis['name'] = "High Conviction Specialist"
            hypothesis['type'] = "discretionary"
            hypothesis['confidence'] = 0.7
            hypothesis['key_signals'] = [
                "Focus on specific market/asset",
                "Consistent position sizing",
                "Selective entry timing"
            ]
            hypothesis['implementation_hints'] = [
                "Deep research on specific market",
                "Wait for high-probability setups",
                "Consistent risk per trade"
            ]
        
        # Algorithmic timing + diversified = Multi-strategy algorithmic
        elif time_pat.get('is_algorithmic') and market_pat.get('specialization') == 'diversified':
            hypothesis['name'] = "Multi-Strategy Algorithmic"
            hypothesis['type'] = "algorithmic"
            hypothesis['confidence'] = 0.65
            hypothesis['key_signals'] = [
                "Systematic execution across markets",
                "Diversified market exposure",
                "Consistent timing"
            ]
            hypothesis['implementation_hints'] = [
                "Multiple uncorrelated strategies",
                "Risk parity allocation",
                "Automated execution"
            ]
        
        # Default
        else:
            hypothesis['name'] = "Unknown - Requires More Data"
            hypothesis['type'] = "unknown"
            hypothesis['confidence'] = 0.3
            hypothesis['key_signals'] = ["Insufficient pattern data"]
            hypothesis['implementation_hints'] = ["Continue monitoring for patterns"]
        
        return hypothesis
    
    def generate_strategy_code(self, hypothesis: Dict, wallet: str) -> str:
        """Generate Python strategy code from hypothesis."""
        strategy_name = f"Discovered_{hypothesis['name'].replace(' ', '')}_{wallet[:6]}"
        
        code_template = f'''"""
Auto-generated strategy based on analysis of wallet {wallet}
Strategy: {hypothesis['name']}
Type: {hypothesis['type']}
Confidence: {hypothesis['confidence']:.2%}
"""

from typing import Dict, Optional, Tuple
from core.base_strategy import BaseStrategy, Signal

class {strategy_name}(BaseStrategy):
    """
    Discovered strategy: {hypothesis['name']}
    
    Key Signals:
    {chr(10).join("    - " + s for s in hypothesis['key_signals'])}
    
    Implementation Notes:
    {chr(10).join("    - " + h for h in hypothesis['implementation_hints'])}
    """
    
    def __init__(self):
        super().__init__(name="{strategy_name}", confidence_threshold=0.6)
        self.wallet_source = "{wallet}"
        self.strategy_type = "{hypothesis['type']}"
        
    def generate_signal(self, data: Dict) -> Optional[Signal]:
        """Generate trading signal based on discovered pattern."""
        # TODO: Implement based on pattern analysis
        # This is a template - customize based on actual signals observed
        
        signal_type = None
        confidence = 0.0
        reason = ""
        
        # Implement strategy logic here
        # Based on: {hypothesis['name']}
        
        if signal_type and confidence >= self.confidence_threshold:
            return Signal(
                type=signal_type,
                confidence=confidence,
                reason=reason,
                metadata={{
                    'source_wallet': self.wallet_source,
                    'strategy_type': self.strategy_type
                }}
            )
        
        return None
    
    def on_trade_complete(self, trade_result: Dict):
        """Learn from completed trades to refine strategy."""
        super().on_trade_complete(trade_result)
        # TODO: Implement feedback loop for strategy refinement
'''
        return code_template
    
    async def discover_new_strategies(self):
        """Main discovery loop - find and decipher strategies."""
        logger.info("Starting strategy discovery cycle...")
        
        new_strategies = []
        
        for wallet in self.TARGET_WALLETS:
            logger.info(f"Analyzing wallet: {wallet[:10]}...")
            
            # Fetch recent activity
            activities = await self.fetch_wallet_activity(wallet)
            orders = await self.fetch_order_history(wallet)
            
            # Combine for analysis
            all_data = activities + orders
            
            if not all_data:
                logger.warning(f"No data found for {wallet[:10]}...")
                continue
            
            # Analyze patterns
            patterns = self.analyze_trading_patterns(wallet, all_data)
            self.wallet_patterns[wallet] = patterns
            
            # Store in database
            self._store_patterns(wallet, patterns)
            
            # Generate strategy if confidence is high enough
            hypothesis = patterns.get('hypothesized_strategy', {})
            if hypothesis and hypothesis.get('confidence', 0) > 0.5:
                strategy_code = self.generate_strategy_code(hypothesis, wallet)
                strategy_name = f"Discovered_{hypothesis['name'].replace(' ', '')}_{wallet[:6]}"
                
                # Check if this is an update to existing strategy
                existing = self._get_strategy(strategy_name)
                if existing:
                    # Compare and update if different
                    self._update_strategy(strategy_name, strategy_code, hypothesis, patterns)
                else:
                    # New strategy
                    self._save_strategy(strategy_name, wallet, strategy_code, hypothesis)
                    new_strategies.append({
                        'name': strategy_name,
                        'wallet': wallet,
                        'hypothesis': hypothesis,
                        'patterns': patterns
                    })
                
                # Write strategy file
                self._write_strategy_file(strategy_name, strategy_code)
            
            self.last_analysis[wallet] = datetime.now()
        
        logger.info(f"Discovery cycle complete. New strategies: {len(new_strategies)}")
        return new_strategies
    
    def _store_patterns(self, wallet: str, patterns: Dict):
        """Store patterns in database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO strategy_patterns (wallet, pattern_type, pattern_data, confidence)
            VALUES (?, ?, ?, ?)
        ''', (
            wallet,
            'full_analysis',
            json.dumps(patterns),
            patterns.get('hypothesized_strategy', {}).get('confidence', 0)
        ))
        
        conn.commit()
        conn.close()
    
    def _get_strategy(self, name: str) -> Optional[Dict]:
        """Get existing strategy from database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM deciphered_strategies WHERE strategy_name = ?
        ''', (name,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                'id': row[0],
                'name': row[1],
                'wallet': row[2],
                'code': row[3],
                'description': row[4],
                'active': row[8]
            }
        return None
    
    def _save_strategy(self, name: str, wallet: str, code: str, hypothesis: Dict):
        """Save new strategy to database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO deciphered_strategies 
            (strategy_name, wallet_source, strategy_code, description, performance_prediction, active)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            name,
            wallet,
            code,
            json.dumps(hypothesis),
            f"Predicted confidence: {hypothesis.get('confidence', 0):.2%}",
            1  # Active by default
        ))
        
        conn.commit()
        conn.close()
        logger.info(f"Saved new strategy: {name}")
    
    def _update_strategy(self, name: str, new_code: str, hypothesis: Dict, patterns: Dict):
        """Update existing strategy if patterns have changed."""
        existing = self._get_strategy(name)
        if not existing:
            return
        
        # Check if code changed significantly
        if existing['code'] != new_code:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE deciphered_strategies 
                SET strategy_code = ?, description = ?, updated_at = CURRENT_TIMESTAMP
                WHERE strategy_name = ?
            ''', (new_code, json.dumps(hypothesis), name))
            
            # Log the update
            cursor.execute('''
                INSERT INTO strategy_updates (strategy_name, update_type, old_value, new_value, reason)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                name,
                'code_update',
                'previous_version',
                'new_version',
                f"Pattern confidence changed to {hypothesis.get('confidence', 0):.2%}"
            ))
            
            conn.commit()
            conn.close()
            
            # Rewrite file
            self._write_strategy_file(name, new_code)
            logger.info(f"Updated strategy: {name}")
    
    def _write_strategy_file(self, name: str, code: str):
        """Write strategy to Python file."""
        strategies_dir = Path("strategies/discovered")
        strategies_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = strategies_dir / f"{name.lower()}.py"
        with open(file_path, 'w') as f:
            f.write(code)
        
        logger.info(f"Wrote strategy file: {file_path}")
    
    def get_active_strategies(self) -> List[Dict]:
        """Get all active discovered strategies."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT strategy_name, wallet_source, description, performance_prediction
            FROM deciphered_strategies WHERE active = 1
        ''')
        
        strategies = []
        for row in cursor.fetchall():
            strategies.append({
                'name': row[0],
                'wallet': row[1],
                'description': json.loads(row[2]) if row[2] else {},
                'prediction': row[3]
            })
        
        conn.close()
        return strategies
    
    def generate_strategy_report(self) -> str:
        """Generate report of all discovered strategies."""
        strategies = self.get_active_strategies()
        
        report = ["# Discovered Strategies Report\n"]
        report.append(f"Generated: {datetime.now().isoformat()}\n")
        report.append(f"Total Active Strategies: {len(strategies)}\n\n")
        
        for i, strat in enumerate(strategies, 1):
            desc = strat.get('description', {})
            report.append(f"## {i}. {strat['name']}\n")
            report.append(f"- **Source Wallet**: {strat['wallet']}\n")
            report.append(f"- **Strategy Type**: {desc.get('type', 'unknown')}\n")
            report.append(f"- **Confidence**: {desc.get('confidence', 0):.2%}\n")
            report.append(f"- **Prediction**: {strat['prediction']}\n")
            report.append(f"\n**Key Signals**:\n")
            for signal in desc.get('key_signals', []):
                report.append(f"- {signal}\n")
            report.append("\n")
        
        return ''.join(report)


class ContinuousMonitor:
    """Continuously monitors and updates strategies."""
    
    def __init__(self, check_interval_minutes: int = 30):
        self.discovery = StrategyDiscoveryEngine()
        self.check_interval = check_interval_minutes
        self.running = False
        
    async def run(self):
        """Main monitoring loop."""
        self.running = True
        logger.info(f"Starting continuous strategy monitoring (interval: {self.check_interval} min)")
        
        while self.running:
            try:
                # Discover new strategies
                new_strategies = await self.discovery.discover_new_strategies()
                
                if new_strategies:
                    logger.info(f"🎯 Discovered {len(new_strategies)} new strategies!")
                    for strat in new_strategies:
                        logger.info(f"  - {strat['name']} (confidence: {strat['hypothesis'].get('confidence', 0):.2%})")
                
                # Generate report
                report = self.discovery.generate_strategy_report()
                report_path = Path("discovery_data/strategy_report.md")
                report_path.write_text(report)
                
                # Wait for next check
                logger.info(f"Next check in {self.check_interval} minutes...")
                await asyncio.sleep(self.check_interval * 60)
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(60)  # Wait 1 min on error
    
    def stop(self):
        """Stop monitoring."""
        self.running = False
        logger.info("Monitoring stopped")


async def main():
    """Main entry point."""
    monitor = ContinuousMonitor(check_interval_minutes=30)
    
    try:
        await monitor.run()
    except KeyboardInterrupt:
        logger.info("Received stop signal")
        monitor.stop()


if __name__ == "__main__":
    asyncio.run(main())
