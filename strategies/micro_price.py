"""
MicroPriceStrategy - High frequency estimator of future prices

Uses Volume Adjusted Mid Price (VAMP) to estimate fair value:
VAMP = (P_bid * Q_ask + P_ask * Q_bid) / (Q_bid + Q_ask)

Cross-multiplies price and quantity between bid/ask sides.
Source: hftbacktest.readthedocs.io - Market Making with Alpha
"""

from typing import Optional, Dict
import numpy as np
from collections import deque
from core.base_strategy import BaseStrategy, Signal, MarketData


class MicroPriceStrategy(BaseStrategy):
    """
    Trade based on micro-price deviation from mid.
    
    Micro-price (VAMP) is a better predictor of short-term price movement
    than simple mid-price because it accounts for order book depth.
    """
    
    def __init__(self, 
                 lookback_periods: int = 10,
                 threshold_bps: float = 5.0):
        super().__init__()
        self.name = "MicroPrice"
        self.lookback_periods = lookback_periods
        self.threshold_bps = threshold_bps
        
        # Track VAMP history
        self.vamp_history = deque(maxlen=lookback_periods)
        self.mid_history = deque(maxlen=lookback_periods)
        
    def calculate_vamp(self, data: MarketData) -> Optional[float]:
        """
        Calculate Volume Adjusted Mid Price.
        VAMP = (P_bid * Q_ask + P_ask * Q_bid) / (Q_bid + Q_ask)
        """
        if not data.order_book:
            return None
        
        best_bid = data.order_book.get('best_bid', data.price)
        best_ask = data.order_book.get('best_ask', data.price)
        bid_depth = data.order_book.get('bid_depth', 1)
        ask_depth = data.order_book.get('ask_depth', 1)
        
        # Cross-multiply: bid price weighted by ask depth, ask price weighted by bid depth
        vamp = (best_bid * ask_depth + best_ask * bid_depth) / (bid_depth + ask_depth)
        
        return vamp
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        """Generate signal based on micro-price deviation."""
        vamp = self.calculate_vamp(data)
        if vamp is None:
            return None
        
        mid = data.price
        
        # Avoid division by zero
        if mid == 0:
            return None
        
        # Calculate deviation in bps
        deviation_bps = (vamp - mid) / mid * 10000
        
        # Store history
        self.vamp_history.append(vamp)
        self.mid_history.append(mid)
        
        if len(self.vamp_history) < self.lookback_periods:
            return None
        
        # Calculate average deviation
        avg_vamp = np.mean(self.vamp_history)
        avg_mid = np.mean(self.mid_history)
        
        # Avoid division by zero
        if avg_mid == 0:
            return None
            
        avg_deviation_bps = (avg_vamp - avg_mid) / avg_mid * 10000
        
        # Skip if price is extreme
        if data.price < 0.05 or data.price > 0.95:
            return None
        
        # Generate signal based on micro-price deviation
        if avg_deviation_bps > self.threshold_bps:
            # VAMP > Mid = buy pressure, go long
            confidence = 0.6 + min(0.3, avg_deviation_bps / 20)
            return Signal(
                signal="up",
                confidence=min(0.95, confidence),
                strategy=self.name,
                metadata={
                    'vamp': avg_vamp,
                    'mid': avg_mid,
                    'deviation_bps': avg_deviation_bps
                }
            )
        elif avg_deviation_bps < -self.threshold_bps:
            # VAMP < Mid = sell pressure, go short
            confidence = 0.6 + min(0.3, -avg_deviation_bps / 20)
            return Signal(
                signal="down",
                confidence=min(0.95, confidence),
                strategy=self.name,
                metadata={
                    'vamp': avg_vamp,
                    'mid': avg_mid,
                    'deviation_bps': avg_deviation_bps
                }
            )
        
        return None
