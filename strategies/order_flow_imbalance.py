"""
Order Flow Imbalance (OFI) Strategy

Based on academic research showing that order flow imbalance predicts
short-term price movements. OFI measures the net buying/selling pressure
from the limit order book.

Key insight: Aggressive buying (hitting asks) vs aggressive selling
(hitting bids) creates directional pressure. Persistent imbalance
predicts future price movement.

Reference: "Order Flow and the Formation of Prices" - Cao et al.
"""

from typing import Optional, Dict
from collections import deque
from statistics import mean

from core.base_strategy import BaseStrategy, Signal, MarketData


class OrderFlowImbalanceStrategy(BaseStrategy):
    """
    Trade based on order flow imbalance from the limit order book.
    
    OFI = (Bid volume at best bid - Ask volume at best ask) / Total volume
    
    Positive OFI = buying pressure = bullish
    Negative OFI = selling pressure = bearish
    """
    
    name = "OrderFlowImbalance"
    description = "Trade on order flow imbalance signals"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        
        # OFI calculation parameters
        self.ofi_window = self.config.get('ofi_window', 10)  # Periods for smoothing
        self.ofi_threshold = self.config.get('ofi_threshold', 0.15)  # 15% imbalance
        
        # Volume depth levels to consider
        self.depth_levels = self.config.get('depth_levels', 3)
        
        # Minimum book depth required
        self.min_depth = self.config.get('min_depth', 1000)  # Minimum $1000 depth
        
        # OFI history
        self.ofi_history: deque = deque(maxlen=50)
        self.price_history: deque = deque(maxlen=50)
        
        # Trend confirmation
        self.trend_confirmation = self.config.get('trend_confirmation', True)
        
        # Cooldown
        self.cooldown_periods = self.config.get('cooldown_periods', 3)
        self.last_signal_period = -self.cooldown_periods
        self.period_count = 0
        
    def calculate_ofi(self, order_book: Dict) -> Optional[float]:
        """
        Calculate Order Flow Imbalance from order book.
        
        OFI = (Bid depth - Ask depth) / (Bid depth + Ask depth)
        
        Returns value between -1 (all selling) and +1 (all buying).
        """
        if not order_book:
            return None
        
        bids = order_book.get('bids', [])
        asks = order_book.get('asks', [])
        
        if not bids or not asks:
            return None
        
        # Calculate depth at top N levels
        bid_depth = sum(float(b.get('size', 0)) for b in bids[:self.depth_levels])
        ask_depth = sum(float(a.get('size', 0)) for a in asks[:self.depth_levels])
        
        total_depth = bid_depth + ask_depth
        
        # Check minimum depth
        if total_depth < self.min_depth:
            return None
        
        # Calculate OFI
        ofi = (bid_depth - ask_depth) / total_depth
        
        return ofi
    
    def get_price_trend(self) -> float:
        """Calculate recent price trend (-1 to 1)."""
        if len(self.price_history) < 5:
            return 0
        
        prices = list(self.price_history)
        early = mean(prices[:len(prices)//2])
        late = mean(prices[len(prices)//2:])
        
        if early == 0:
            return 0
        
        trend = (late - early) / early
        return max(-1, min(1, trend * 10))  # Scale and clamp
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_price = data.price
        
        # Update history
        self.price_history.append(current_price)
        self.period_count += 1
        
        # Check cooldown
        if self.period_count - self.last_signal_period < self.cooldown_periods:
            return None
        
        # Calculate OFI
        ofi = self.calculate_ofi(data.order_book)
        if ofi is None:
            return None
        
        # Store OFI
        self.ofi_history.append(ofi)
        
        # Need enough history for smoothing
        if len(self.ofi_history) < self.ofi_window:
            return None
        
        # Calculate smoothed OFI
        recent_ofi = list(self.ofi_history)[-self.ofi_window:]
        smoothed_ofi = mean(recent_ofi)
        
        # Check if OFI exceeds threshold
        if abs(smoothed_ofi) < self.ofi_threshold:
            return None
        
        # Optional: confirm with price trend
        if self.trend_confirmation:
            trend = self.get_price_trend()
            
            # OFI and trend should align
            if smoothed_ofi > 0 and trend < -0.1:
                # Bullish OFI but bearish trend - skip
                return None
            if smoothed_ofi < 0 and trend > 0.1:
                # Bearish OFI but bullish trend - skip
                return None
        
        # Generate signal
        if smoothed_ofi > 0:
            # Buying pressure
            confidence = min(0.6 + abs(smoothed_ofi) * 0.4, 0.9)
            signal = Signal(
                strategy=self.name,
                signal="up",
                confidence=confidence,
                reason=f"OFI bullish: {smoothed_ofi:.2f} imbalance (bid depth > ask)",
                metadata={
                    'ofi': smoothed_ofi,
                    'ofi_raw': ofi,
                    'current_price': current_price,
                    'trend': self.get_price_trend() if self.trend_confirmation else None
                }
            )
        else:
            # Selling pressure
            confidence = min(0.6 + abs(smoothed_ofi) * 0.4, 0.9)
            signal = Signal(
                strategy=self.name,
                signal="down",
                confidence=confidence,
                reason=f"OFI bearish: {smoothed_ofi:.2f} imbalance (ask depth > bid)",
                metadata={
                    'ofi': smoothed_ofi,
                    'ofi_raw': ofi,
                    'current_price': current_price,
                    'trend': self.get_price_trend() if self.trend_confirmation else None
                }
            )
        
        self.last_signal_period = self.period_count
        return signal
