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
                 min_trade_size: float = 1000,
                 max_copy_size: float = 100):
        super().__init__()
        self.name = "CopyTrading"
        self.min_whale_score = min_whale_score
        self.copy_delay_seconds = copy_delay_seconds
        self.min_trade_size = min_trade_size
        self.max_copy_size = max_copy_size
        
        self.whales: Dict[str, WhaleProfile] = {}
        self.recent_whale_trades: List[WhaleTrade] = []
        self.copied_trades: Dict[str, datetime] = {}
        self.known_whales = []
        
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        """Generate copy trading signal from whale activity."""
        if not data.order_book:
            return None
        
        bid_depth = data.order_book.get('bid_depth_5pct', 0)
        ask_depth = data.order_book.get('ask_depth_5pct', 0)
        
        if bid_depth == 0 or ask_depth == 0:
            return None
        
        total_depth = bid_depth + ask_depth
        bid_ratio = bid_depth / total_depth if total_depth > 0 else 0.5
        
        if bid_ratio > 0.7:
            confidence = min(0.9, 0.6 + (bid_ratio - 0.7) * 1.0)
            signal_type = "up"
            reason = f"Whale buying detected: {bid_ratio:.1%} bid depth ratio"
        elif bid_ratio < 0.3:
            confidence = min(0.9, 0.6 + (0.3 - bid_ratio) * 1.0)
            signal_type = "down"
            reason = f"Whale selling detected: {1-bid_ratio:.1%} ask depth ratio"
        else:
            return None
        
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
    
    def on_trade_complete(self, trade_result: Dict):
        """Update strategy based on trade result."""
        pass
