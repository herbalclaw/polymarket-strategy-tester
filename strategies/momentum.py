import statistics
from typing import Optional, List
from collections import deque

from core.base_strategy import BaseStrategy, Signal, MarketData


class MomentumStrategy(BaseStrategy):
    """
    Multi-Exchange Momentum Strategy
    
    Follows the aggregated price direction across exchanges.
    Buys when VWAP is trending up, sells when trending down.
    """
    
    name = "momentum"
    description = "Follow aggregated price momentum across exchanges"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        config = config or {}
        self.price_history: deque = deque(maxlen=self.config.get('window', 10))
        self.short_window = self.config.get('short_window', 2)  # Reduced from 3
        self.long_window = self.config.get('long_window', 5)   # Reduced from 10
        self.min_change_pct = self.config.get('min_change_pct', 0.01)  # Reduced from 0.05
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        # Store price history internally (builds up over time)
        self.price_history.append(data.vwap)
        
        if len(self.price_history) < self.long_window:
            return None
        
        prices = list(self.price_history)
        
        # Calculate moving averages
        sma_short = sum(prices[-self.short_window:]) / self.short_window
        sma_long = sum(prices) / len(prices)
        
        # Calculate price change
        price_change = (prices[-1] - prices[0]) / prices[0] * 100
        
        # Generate signal
        if sma_short > sma_long * 1.001 and price_change > self.min_change_pct:
            return Signal(
                strategy=self.name,
                signal="up",
                confidence=min(abs(price_change) * 10, 0.9),
                reason=f"Upward momentum: {price_change:.3f}% over {len(prices)} samples",
                metadata={
                    'sma_short': sma_short,
                    'sma_long': sma_long,
                    'price_change_pct': price_change
                }
            )
        elif sma_short < sma_long * 0.999 and price_change < -self.min_change_pct:
            return Signal(
                strategy=self.name,
                signal="down",
                confidence=min(abs(price_change) * 10, 0.9),
                reason=f"Downward momentum: {price_change:.3f}% over {len(prices)} samples",
                metadata={
                    'sma_short': sma_short,
                    'sma_long': sma_long,
                    'price_change_pct': price_change
                }
            )
        
        return None
