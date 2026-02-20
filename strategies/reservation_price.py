"""
ReservationPriceStrategy - Market making with position skew

Fair price = Micro-price - skew * position
Skew adjusts quotes based on inventory to avoid one-sided exposure.

Source: hftbacktest.readthedocs.io - Market Making with Alpha
"""

from typing import Optional, Dict
import numpy as np
from collections import deque
from core.base_strategy import BaseStrategy, Signal, MarketData


class ReservationPriceStrategy(BaseStrategy):
    """
    Market making strategy with inventory-aware pricing.
    
    Adjusts fair price based on current position to:
    - Reduce position when heavily long (lower reservation price)
    - Reduce position when heavily short (raise reservation price)
    """
    
    def __init__(self,
                 skew: float = 0.1,
                 max_position: float = 50.0,
                 lookback: int = 20):
        super().__init__()
        self.name = "ReservationPrice"
        self.skew = skew
        self.max_position = max_position
        
        # Track position and P&L
        self.position = 0.0
        self.trades = deque(maxlen=lookback)
        
    def calculate_reservation_price(self, data: MarketData) -> Optional[float]:
        """
        Calculate reservation price with position skew.
        Reservation = Fair_price - skew * position
        """
        if not data.order_book:
            return None
        
        # Fair price from micro-price
        best_bid = data.order_book.get('best_bid', data.price)
        best_ask = data.order_book.get('best_ask', data.price)
        bid_depth = data.order_book.get('bid_depth', 1)
        ask_depth = data.order_book.get('ask_depth', 1)
        
        fair_price = (best_bid * ask_depth + best_ask * bid_depth) / (bid_depth + ask_depth)
        
        # Apply position skew
        normalized_position = self.position / self.max_position
        reservation_price = fair_price - self.skew * normalized_position
        
        return reservation_price
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        """Generate signal based on reservation price vs mid."""
        reservation = self.calculate_reservation_price(data)
        if reservation is None:
            return None
        
        mid = data.price
        
        # Calculate deviation
        deviation = reservation - mid
        deviation_pct = deviation / mid
        
        # Skip extreme prices
        if data.price < 0.05 or data.price > 0.95:
            return None
        
        # Generate signal
        if deviation_pct > 0.005:  # Reservation > Mid by 0.5%
            # Skewed to sell, but signal says buy (mean reversion)
            confidence = 0.6 + min(0.25, deviation_pct * 10)
            signal_type = "up"
        elif deviation_pct < -0.005:  # Reservation < Mid by 0.5%
            # Skewed to buy, but signal says sell
            confidence = 0.6 + min(0.25, -deviation_pct * 10)
            signal_type = "down"
        else:
            return None
        
        # Update position tracking (simplified)
        if signal_type == "up":
            self.position += 5  # Assume $5 trade size
        else:
            self.position -= 5
        
        # Clamp position
        self.position = max(-self.max_position, min(self.max_position, self.position))
        
        return Signal(
            signal=signal_type,
            confidence=min(0.9, confidence),
            strategy=self.name,
            metadata={
                'reservation_price': reservation,
                'mid': mid,
                'deviation_pct': deviation_pct,
                'position': self.position
            }
        )
