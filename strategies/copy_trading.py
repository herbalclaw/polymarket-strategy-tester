"""
Copy Trading Strategy
Mirror trades from profitable whale wallets.
Source: dylanpersonguy/Polymarket-Trading-Bot
"""

from typing import Optional, Dict, List
from dataclasses import dataclass
from datetime import datetime, timedelta
import numpy as np

from core.base_strategy import BaseStrategy, Signal, MarketData


@dataclass
class WhaleTrade:
    """Track a whale trade."""
    wallet: str
    side: str
    size: float
    price: float
    timestamp: datetime
    market: str


@dataclass
class WhaleProfile:
    """Track whale performance."""
    wallet: str
    total_pnl: float = 0.0
    trade_count: int = 0
    win_count: int = 0
    avg_trade_size: float = 0.0
    last_trade_time: Optional[datetime] = None
    score: float = 0.0


class CopyTradingStrategy(BaseStrategy):
    """
    Copy trading strategy for BTC 5-minute markets.
    
    Concept:
    - Monitor profitable whale wallets
    - Mirror their trades with delay for risk management
    - Score whales by: profitability (30%), timing (20%), consistency (15%), etc.
    
    For BTC 5-min markets:
    - Track whales active in BTC markets
    - Copy within same 5-min window
    - Apply position sizing based on whale score
    """
    
    def __init__(self,
                 min_whale_score: float = 0.6,
                 copy_delay_seconds: float = 2.0,
                 min_trade_size: float = 1000,  # Minimum whale trade to copy
                 max_copy_size: float = 100):  # Max position size
        super().__init__("CopyTrading")
        self.min_whale_score = min_whale_score
        self.copy_delay_seconds = copy_delay_seconds
        self.min_trade_size = min_trade_size
        self.max_copy_size = max_copy_size
        
        # Whale tracking
        self.whales: Dict[str, WhaleProfile] = {}
        self.recent_whale_trades: List[WhaleTrade] = []
        self.copied_trades: Dict[str, datetime] = {}  # Track what we copied
        
        # Known profitable whales (would be discovered via scanner)
        self.known_whales = [
            # Example whale wallets - in production these come from scanner
            # "0x...",
        ]
        
    def on_market_data(self, data: MarketData) -> Optional[Signal]:
        """Generate copy trading signal from whale activity."""
        # In a real implementation, this would:
        # 1. Query recent whale trades from API/blockchain
        # 2. Score whales based on historical performance
        # 3. Mirror high-confidence whale trades
        
        # For now, simulate based on order book pressure
        if not data.order_book:
            return None
        
        # Check for unusual order flow (proxy for whale activity)
        bid_depth = data.order_book.get('bid_depth_5pct', 0)
        ask_depth = data.order_book.get('ask_depth_5pct', 0)
        
        if bid_depth == 0 or ask_depth == 0:
            return None
        
        # Imbalance indicates potential whale direction
        total_depth = bid_depth + ask_depth
        bid_ratio = bid_depth / total_depth if total_depth > 0 else 0.5
        
        # Strong imbalance = potential whale signal
        if bid_ratio > 0.7:
            # Heavy buying pressure - copy long
            confidence = min(0.9, 0.6 + (bid_ratio - 0.7) * 1.0)
            signal_type = "up"
            reason = f"Whale buying detected: {bid_ratio:.1%} bid depth ratio"
        elif bid_ratio < 0.3:
            # Heavy selling pressure - copy short
            confidence = min(0.9, 0.6 + (0.3 - bid_ratio) * 1.0)
            signal_type = "down"
            reason = f"Whale selling detected: {1-bid_ratio:.1%} ask depth ratio"
        else:
            return None
        
        # Check if we recently copied this signal (avoid duplication)
        signal_key = f"{signal_type}_{datetime.now().strftime('%H:%M')}"
        if signal_key in self.copied_trades:
            last_copy = self.copied_trades[signal_key]
            if datetime.now() - last_copy < timedelta(minutes=1):
                return None
        
        if confidence >= self.min_whale_score:
            self.copied_trades[signal_key] = datetime.now()
            
            return Signal(
                signal=signal_type,
                confidence=confidence,
                strategy=self.name,
                reason=reason,
                metadata={
                    'bid_ratio': bid_ratio,
                    'bid_depth': bid_depth,
                    'ask_depth': ask_depth,
                    'copy_delay': self.copy_delay_seconds,
                    'whale_score': confidence
                }
            )
        
        return None
    
    def update_whale_performance(self, wallet: str, trade_pnl: float):
        """Update whale performance tracking."""
        if wallet not in self.whales:
            self.whales[wallet] = WhaleProfile(wallet=wallet)
        
        whale = self.whales[wallet]
        whale.trade_count += 1
        whale.total_pnl += trade_pnl
        
        if trade_pnl > 0:
            whale.win_count += 1
        
        whale.last_trade_time = datetime.now()
        
        # Recalculate score
        if whale.trade_count > 0:
            win_rate = whale.win_count / whale.trade_count
            avg_pnl = whale.total_pnl / whale.trade_count
            
            # Composite score: win rate (30%), avg pnl (30%), consistency (20%), recency (20%)
            whale.score = (win_rate * 0.3 + 
                          min(1.0, max(0, avg_pnl / 10)) * 0.3 +
                          min(1.0, whale.trade_count / 20) * 0.2 +
                          0.2)  # Recency placeholder
    
    def on_trade_complete(self, trade_result: Dict):
        """Update strategy based on trade result."""
        pnl = trade_result.get('pnl_pct', 0)
        
        # Track our own performance as if we were a whale
        # This helps calibrate the strategy
        if pnl > 0:
            # Successful copy
            pass
        else:
            # Failed copy - might indicate stale whale or bad timing
            pass
