"""
OrderFlowImbalanceStrategy - Predict price moves from order book imbalance

Mathematical framework:
IR = Bid_volume / (Bid_volume + Ask_volume)
IR > 0.65 predicts price increase within 15-30 minutes

Source: navnoorbawa.substack.com - Mathematical Execution Behind Prediction Market Alpha
"""

from typing import Optional, Dict, List
import numpy as np
from collections import deque
from core.base_strategy import BaseStrategy, Signal, MarketData


class OrderFlowImbalanceStrategy(BaseStrategy):
    """
    Trade based on order book imbalance.
    
    Imbalance Ratio (IR) = Bid_volume / (Bid_volume + Ask_volume)
    - IR > 0.65: Predict price increase (buy pressure)
    - IR < 0.35: Predict price decrease (sell pressure)
    """
    
    def __init__(self,
                 imbalance_threshold: float = 0.65,
                 lookback_periods: int = 5):
        super().__init__()
        self.name = "OrderFlowImbalance"
        self.imbalance_threshold = imbalance_threshold
        self.lookback_periods = lookback_periods
        
        # Track imbalance history
        self.imbalance_history = deque(maxlen=lookback_periods)
        self.price_history = deque(maxlen=lookback_periods)
        
    def calculate_imbalance_ratio(self, data: MarketData) -> Optional[float]:
        """
        Calculate order book imbalance ratio.
        IR = Bid_depth / (Bid_depth + Ask_depth)
        """
        if not data.order_book:
            return None
        
        bid_depth = data.order_book.get('bid_depth', 0)
        ask_depth = data.order_book.get('ask_depth', 0)
        
        total_depth = bid_depth + ask_depth
        if total_depth == 0:
            return None
        
        return bid_depth / total_depth
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        """Generate signal based on order flow imbalance."""
        # Calculate current imbalance
        imbalance = self.calculate_imbalance_ratio(data)
        if imbalance is None:
            return None
        
        # Store history
        self.imbalance_history.append(imbalance)
        self.price_history.append(data.price)
        
        # Need enough history
        if len(self.imbalance_history) < self.lookback_periods:
            return None
        
        # Calculate average imbalance
        avg_imbalance = np.mean(self.imbalance_history)
        
        # Skip if price is extreme
        if data.price < 0.05 or data.price > 0.95:
            return None
        
        # Generate signal based on imbalance
        if avg_imbalance > self.imbalance_threshold:
            # Strong buy pressure - go long
            confidence = 0.6 + (avg_imbalance - self.imbalance_threshold) * 0.5
            confidence = min(0.9, confidence)
            
            return Signal(
                signal="up",
                confidence=confidence,
                strategy=self.name,
                metadata={
                    'imbalance_ratio': avg_imbalance,
                    'threshold': self.imbalance_threshold,
                    'pressure': 'buy'
                }
            )
        
        elif avg_imbalance < (1 - self.imbalance_threshold):
            # Strong sell pressure - go short
            confidence = 0.6 + ((1 - self.imbalance_threshold) - avg_imbalance) * 0.5
            confidence = min(0.9, confidence)
            
            return Signal(
                signal="down",
                confidence=confidence,
                strategy=self.name,
                metadata={
                    'imbalance_ratio': avg_imbalance,
                    'threshold': 1 - self.imbalance_threshold,
                    'pressure': 'sell'
                }
            )
        
        return None
