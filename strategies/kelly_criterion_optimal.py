"""
KellyCriterionStrategy - Optimal bet sizing based on edge

Mathematical framework:
f* = (P_true - P_market) / (1 - P_market)

Uses fractional Kelly (25-50%) for safety.
Source: navnoorbawa.substack.com - Mathematical Execution Behind Prediction Market Alpha
"""

from typing import Optional, Dict
import numpy as np
from core.base_strategy import BaseStrategy, Signal, MarketData


class KellyCriterionOptimalStrategy(BaseStrategy):
    """
    Kelly criterion optimal bet sizing for prediction markets.
    
    Edge calculation:
    - Estimate true probability from market data
    - Compare to market price
    - Size position using fractional Kelly
    """
    
    def __init__(self, kelly_fraction: float = 0.25, confidence_threshold: float = 0.55):
        super().__init__()
        self.name = "KellyCriterionOptimal"
        self.kelly_fraction = kelly_fraction  # 25% of full Kelly
        self.confidence_threshold = confidence_threshold
        
        # Track price history for probability estimation
        self.price_history = []
        self.max_history = 100
        
    def estimate_true_probability(self, data: MarketData) -> float:
        """
        Estimate true probability from market microstructure.
        Uses VWAP and order book imbalance.
        """
        if not data.order_book:
            return data.price
        
        best_bid = data.order_book.get('best_bid', data.price)
        best_ask = data.order_book.get('best_ask', data.price)
        
        # Microprice weighted by volume
        bid_depth = data.order_book.get('bid_depth', 1)
        ask_depth = data.order_book.get('ask_depth', 1)
        
        # Weight by opposite side liquidity
        microprice = (best_bid * ask_depth + best_ask * bid_depth) / (bid_depth + ask_depth)
        
        # Blend with current price
        p_true = 0.7 * microprice + 0.3 * data.price
        
        return p_true
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        """Generate signal using Kelly criterion sizing."""
        p_market = data.price
        
        # Skip if price is too extreme (near settlement)
        if p_market < 0.05 or p_market > 0.95:
            return None
        
        # Estimate true probability
        p_true = self.estimate_true_probability(data)
        
        # Calculate edge
        edge = abs(p_true - p_market)
        
        # Minimum edge threshold
        if edge < 0.03:  # Need at least 3% edge
            return None
        
        # Kelly fraction: f* = (P_true - P_market) / (1 - P_market)
        if p_true > p_market:
            # Long signal
            kelly = (p_true - p_market) / (1 - p_market)
            signal_type = "up"
        else:
            # Short signal
            kelly = (p_market - p_true) / p_market
            signal_type = "down"
        
        # Apply fractional Kelly (25%)
        position_size = kelly * self.kelly_fraction
        
        # Scale confidence by edge and Kelly fraction
        confidence = min(0.95, 0.6 + edge * 2 + position_size)
        
        return Signal(
            signal=signal_type,
            confidence=confidence,
            strategy=self.name,
            metadata={
                'p_true': p_true,
                'p_market': p_market,
                'edge': edge,
                'kelly_fraction': kelly,
                'position_size': position_size
            }
        )
