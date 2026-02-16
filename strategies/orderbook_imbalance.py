"""
Order Book Imbalance (OBI) Strategy

Based on market microstructure research - uses order book depth imbalance
to predict short-term price direction.

Reference: HFT Backtest documentation on Order Book Imbalance
"""

from typing import Optional
from collections import deque
from statistics import mean, stdev

from core.base_strategy import BaseStrategy, Signal, MarketData


class OrderBookImbalanceStrategy(BaseStrategy):
    """
    Order Book Imbalance strategy for high-frequency edge.
    
    Calculates standardized imbalance between bid and ask volumes
    to predict short-term directional moves.
    """
    
    name = "orderbook_imbalance"
    description = "Order book depth imbalance for directional edge"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        # Look at top 1% depth from mid price
        self.lookback_depth = self.config.get('lookback_depth', 0.01)  # 1%
        # Window for standardization
        self.window = self.config.get('window', 100)
        # Threshold for signal generation (z-score)
        self.threshold = self.config.get('threshold', 1.5)
        
        # Store imbalance history for standardization
        self.imbalance_history = deque(maxlen=self.window)
        
    def calculate_imbalance(self, market_data: MarketData) -> float:
        """
        Calculate order book imbalance.
        
        Returns standardized imbalance score (z-score).
        """
        # Get mid price
        mid = market_data.mid
        if mid == 0:
            return 0
        
        # Calculate price range for lookback
        lower_bound = mid * (1 - self.lookback_depth)
        upper_bound = mid * (1 + self.lookback_depth)
        
        # Get exchange prices
        exchange_prices = market_data.exchange_prices
        
        total_bid_qty = 0
        total_ask_qty = 0
        
        for exchange, data in exchange_prices.items():
            price = data.get('price', 0)
            bid = data.get('bid', 0)
            ask = data.get('ask', 0)
            bid_depth = data.get('bid_depth', 0)
            ask_depth = data.get('ask_depth', 0)
            
            # Only count if within our depth range
            if bid >= lower_bound:
                total_bid_qty += bid_depth
            if ask <= upper_bound:
                total_ask_qty += ask_depth
        
        # Calculate raw imbalance
        if total_bid_qty + total_ask_qty == 0:
            return 0
        
        raw_imbalance = (total_bid_qty - total_ask_qty) / (total_bid_qty + total_ask_qty)
        
        return raw_imbalance
    
    def generate_signal(self, market_data: MarketData) -> Optional[Signal]:
        """Generate trading signal based on order book imbalance."""
        # Calculate current imbalance
        imbalance = self.calculate_imbalance(market_data)
        
        # Store in history
        self.imbalance_history.append(imbalance)
        
        # Need enough history for standardization
        if len(self.imbalance_history) < self.window // 2:
            return None
        
        # Calculate z-score (standardized imbalance)
        hist = list(self.imbalance_history)
        avg = mean(hist)
        
        # Avoid division by zero
        try:
            std = stdev(hist)
        except:
            std = 0
        
        if std == 0:
            return None
        
        z_score = (imbalance - avg) / std
        
        # Generate signal based on threshold
        if z_score > self.threshold:
            # Strong buy imbalance - bullish
            confidence = min(0.6 + abs(z_score) * 0.05, 0.95)
            return Signal(
                strategy=self.name,
                signal="up",
                confidence=confidence,
                reason=f"OBI z-score: {z_score:.2f} (bid-heavy)",
                metadata={
                    'z_score': z_score,
                    'raw_imbalance': imbalance,
                    'threshold': self.threshold
                }
            )
        elif z_score < -self.threshold:
            # Strong sell imbalance - bearish
            confidence = min(0.6 + abs(z_score) * 0.05, 0.95)
            return Signal(
                strategy=self.name,
                signal="down",
                confidence=confidence,
                reason=f"OBI z-score: {z_score:.2f} (ask-heavy)",
                metadata={
                    'z_score': z_score,
                    'raw_imbalance': imbalance,
                    'threshold': self.threshold
                }
            )
        
        return None
