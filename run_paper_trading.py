#!/usr/bin/env python3
"""
Paper Trading Runner

Run multiple strategies in paper trading mode.
"""

import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.strategy_engine import StrategyEngine, StrategyRegistry
from strategies import (
    MomentumStrategy,
    ArbitrageStrategy,
    VWAPStrategy,
    LeadLagStrategy,
    SentimentStrategy
)

from data.price_feed import MultiExchangeFeed
from data.sentiment_feed import SentimentFeed


class PaperTrader:
    """Paper trading system using modular strategies."""
    
    def __init__(self):
        self.engine = StrategyEngine()
        self.price_feed = MultiExchangeFeed()
        self.sentiment_feed = SentimentFeed()
        
        # Track trades
        self.active_trade = None
        self.trade_history = []
        
    def register_strategies(self):
        """Register all available strategies."""
        # Register strategies
        StrategyRegistry.register(MomentumStrategy)
        StrategyRegistry.register(ArbitrageStrategy)
        StrategyRegistry.register(VWAPStrategy)
        StrategyRegistry.register(LeadLagStrategy)
        StrategyRegistry.register(SentimentStrategy)
        
        # Add to engine
        self.engine.add_strategy('momentum', {'window': 10})
        self.engine.add_strategy('arbitrage', {'min_arb_pct': 0.1})
        self.engine.add_strategy('vwap', {'deviation_threshold': 0.1})
        self.engine.add_strategy('leadlag', {'min_move_pct': 0.05})
        self.engine.add_strategy('sentiment', {'min_sentiment_confidence': 0.7})
    
    async def run(self):
        """Main paper trading loop."""
        print("="*70, flush=True)
        print("MODULAR PAPER TRADING BOT", flush=True)
        print("Strategies: Momentum, Arbitrage, VWAP, Lead/Lag, Sentiment", flush=True)
        print("="*70, flush=True)
        
        self.register_strategies()
        
        cycle = 0
        
        while True:
            cycle += 1
            print(f"\n{'='*70}", flush=True)
            print(f"Cycle {cycle}", flush=True)
            print(f"{'='*70}", flush=True)
            
            # Fetch market data
            market_data = await self.price_feed.fetch_data()
            
            # Fetch sentiment
            sentiment_data = await self.sentiment_feed.fetch_data()
            market_data.sentiment = sentiment_data['sentiment']
            market_data.sentiment_confidence = sentiment_data['confidence']
            
            print(f"\nBTC Price: ${market_data.price:,.2f}", flush=True)
            print(f"VWAP: ${market_data.vwap:,.2f}", flush=True)
            print(f"Exchanges: {len(market_data.exchange_prices)}", flush=True)
            print(f"Sentiment: {market_data.sentiment.upper()} ({market_data.sentiment_confidence:.1%})", flush=True)
            
            # Run strategies
            signals = self.engine.run_all(market_data)
            
            if signals:
                print(f"\n🎯 SIGNALS ({len(signals)}):", flush=True)
                for sig in signals:
                    print(f"   [{sig.strategy}] {sig.signal.upper()} @ {sig.confidence:.1%}", flush=True)
                
                # Get best signal
                best = self.engine.get_best_signal(market_data)
                if best:
                    print(f"\n⭐ BEST: [{best.strategy}] {best.signal.upper()} @ {best.confidence:.1%}", flush=True)
                    print(f"   Reason: {best.reason}", flush=True)
            
            # Print performance every 10 cycles
            if cycle % 10 == 0:
                self.print_performance()
            
            await asyncio.sleep(5)
    
    def print_performance(self):
        """Print strategy performance."""
        report = self.engine.get_performance_report()
        
        print("\n" + "="*70, flush=True)
        print("PERFORMANCE REPORT", flush=True)
        print("="*70, flush=True)
        
        for name, perf in report.items():
            if perf['total_trades'] > 0:
                print(f"\n{name}:", flush=True)
                print(f"  Trades: {perf['total_trades']}", flush=True)
                print(f"  Win Rate: {perf['win_rate']:.1%}", flush=True)
                print(f"  Total P&L: {perf['total_pnl']:+.3f}%", flush=True)


if __name__ == "__main__":
    trader = PaperTrader()
    try:
        asyncio.run(trader.run())
    except KeyboardInterrupt:
        print("\n\nStopping...", flush=True)
        trader.print_performance()
