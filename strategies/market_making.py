"""
Market Making Strategy
Captures bid-ask spread by providing liquidity on both sides.
Source: dylanpersonguy/Polymarket-Trading-Bot
"""

from typing import Optional, Dict, List
from dataclasses import dataclass
from datetime import datetime, timedelta
import numpy as np

from core.base_strategy import BaseStrategy, Signal, MarketData


@dataclass
class Quote:
    """Market making quote."""
    side: str  # 'bid' or 'ask'
    price: float
    size: float
    timestamp: datetime


class MarketMakingStrategy(BaseStrategy):
    """
    Market making strategy for BTC 5-minute markets.
    
    Concept:
    - Quote both sides of the order book
    - Capture the bid-ask spread
    - Plus potential liquidity rewards from Polymarket
    
    For BTC 5-min markets:
    - 0% taker fees
    - Maker rebates possible
    - High frequency suitable
    
    Key parameters:
    - Spread capture target: 40 bps minimum
    - Inventory management: keep neutral
    - Quote size: small to avoid adverse selection
    """
    
    def __init__(self, 
                 min_spread_bps: float = 40,
                 max_position: float = 100,  # Max $ exposure
                 quote_size: float = 10,  # $ per quote
                 inventory_skew: float = 0.1):  # Adjust quotes based on inventory
        super().__init__("MarketMaking")
        self.min_spread_bps = min_spread_bps
        self.max_position = max_position
        self.quote_size = quote_size
        self.inventory_skew = inventory_skew
        
        self.current_position = 0.0  # Positive = long, Negative = short
        self.spread_history: List[float] = []
        self.max_history = 50
        
    def on_market_data(self, data: MarketData) -> Optional[Signal]:
        """Generate market making signal based on spread."""
        if not data.order_book:
            return None
        
        best_bid = data.order_book.get('best_bid', 0)
        best_ask = data.order_book.get('best_ask', 0)
        
        if best_bid == 0 or best_ask == 0:
            return None
        
        # Calculate spread
        mid_price = (best_bid + best_ask) / 2
        spread = best_ask - best_bid
        spread_bps = (spread / mid_price) * 10000 if mid_price > 0 else 0
        
        # Track spread history
        self.spread_history.append(spread_bps)
        if len(self.spread_history) > self.max_history:
            self.spread_history.pop(0)
        
        # Only trade if spread is attractive
        if spread_bps < self.min_spread_bps:
            return None
        
        # Check inventory limits
        if abs(self.current_position) >= self.max_position:
            # Need to reduce position, favor opposite side
            if self.current_position > 0:
                # Long too much, favor selling (ask side)
                signal_type = "down"
                confidence = 0.75
                reason = f"Inventory reduction: long {self.current_position:.0f}, capturing {spread_bps:.0f} bps spread"
            else:
                # Short too much, favor buying (bid side)
                signal_type = "up"
                confidence = 0.75
                reason = f"Inventory reduction: short {abs(self.current_position):.0f}, capturing {spread_bps:.0f} bps spread"
        else:
            # Normal market making - pick side with better edge
            avg_spread = np.mean(self.spread_history) if self.spread_history else spread_bps
            
            # If current spread > average, good opportunity
            if spread_bps > avg_spread * 1.2:
                # Wide spread - capture it
                # Pick direction based on recent price action
                if data.vwap and data.price > data.vwap:
                    # Price above VWAP, slight upward bias
                    signal_type = "up"
                    confidence = 0.65
                else:
                    signal_type = "down"
                    confidence = 0.65
                
                reason = f"Wide spread capture: {spread_bps:.0f} bps vs avg {avg_spread:.0f} bps"
            else:
                # Normal spread - only trade if high confidence
                if spread_bps > self.min_spread_bps * 1.5:
                    signal_type = "up" if np.random.random() > 0.5 else "down"
                    confidence = 0.6
                    reason = f"Normal spread capture: {spread_bps:.0f} bps"
                else:
                    return None
        
        if confidence >= 0.6:
            return Signal(
                signal=signal_type,
                confidence=confidence,
                strategy=self.name,
                reason=reason,
                metadata={
                    'spread_bps': spread_bps,
                    'best_bid': best_bid,
                    'best_ask': best_ask,
                    'current_position': self.current_position,
                    'quote_size': self.quote_size
                }
            )
        
        return None
    
    def on_trade_complete(self, trade_result: Dict):
        """Update position tracking."""
        side = trade_result.get('side', '').upper()
        pnl = trade_result.get('pnl_pct', 0)
        
        # Update position
        if side == 'UP':
            self.current_position += self.quote_size
        elif side == 'DOWN':
            self.current_position -= self.quote_size
        
        # Keep position bounded
        self.current_position = max(-self.max_position, min(self.max_position, self.current_position))
