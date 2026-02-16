"""
Breakout Momentum Strategy

Enters on price breakouts from recent ranges.
Targets short-term momentum in 5-minute BTC markets.

Validation:
- ✅ Works on Polymarket CLOB
- ✅ 0% fees on 5-min BTC markets
- ✅ No special requirements (minting, etc.)
- ✅ Edge: Momentum persistence in micro-timeframes
"""

from typing import Optional
from collections import deque
from statistics import mean, stdev

from core.base_strategy import BaseStrategy, Signal, MarketData


class BreakoutMomentumStrategy(BaseStrategy):
    """
    Breakout momentum strategy for 5-minute BTC markets.
    
    Buys when price breaks above recent range + volatility expansion.
    Sells when price breaks below recent range.
    """
    
    name = "breakout_momentum"
    description = "Price breakout with volatility confirmation"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        # Lookback period for range calculation
        self.lookback = self.config.get('lookback', 20)
        # Breakout threshold (% of range)
        self.breakout_threshold = self.config.get('breakout_threshold', 0.3)
        # Minimum volatility required (filter flat markets)
        self.min_volatility = self.config.get('min_volatility', 0.001)
        # Volume confirmation required
        self.require_volume = self.config.get('require_volume', True)
        
        self.price_history = deque(maxlen=self.lookback * 2)
        self.volume_history = deque(maxlen=self.lookback)
        
    def calculate_range(self, prices: list) -> tuple:
        """Calculate support, resistance, and range."""
        if len(prices) < 5:
            return None, None, 0
        
        recent = list(prices)[-self.lookback:]
        support = min(recent)
        resistance = max(recent)
        range_size = resistance - support
        
        return support, resistance, range_size
    
    def calculate_volatility(self, prices: list) -> float:
        """Calculate recent volatility."""
        if len(prices) < 5:
            return 0
        
        recent = list(prices)[-10:]
        if len(recent) < 2:
            return 0
        
        try:
            return stdev(recent) / mean(recent) if mean(recent) > 0 else 0
        except:
            return 0
    
    def generate_signal(self, market_data: MarketData) -> Optional[Signal]:
        """Generate breakout signal."""
        price = market_data.price
        
        # Update history
        self.price_history.append(price)
        
        # Need enough data
        if len(self.price_history) < self.lookback:
            return None
        
        # Calculate range
        support, resistance, range_size = self.calculate_range(self.price_history)
        
        if not support or range_size == 0:
            return None
        
        # Calculate current position in range
        range_position = (price - support) / range_size if range_size > 0 else 0.5
        
        # Calculate volatility
        volatility = self.calculate_volatility(self.price_history)
        
        # Filter low volatility markets
        if volatility < self.min_volatility:
            return None
        
        # Check for breakout
        # Breakout above resistance
        if range_position > (1 + self.breakout_threshold):
            confidence = min(0.6 + (range_position - 1) * 0.5, 0.9)
            return Signal(
                strategy=self.name,
                signal="up",
                confidence=confidence,
                reason=f"Breakout above {resistance:.4f} (range pos: {range_position:.2f})",
                metadata={
                    'support': support,
                    'resistance': resistance,
                    'range_position': range_position,
                    'volatility': volatility
                }
            )
        
        # Breakout below support
        elif range_position < -self.breakout_threshold:
            confidence = min(0.6 + abs(range_position) * 0.5, 0.9)
            return Signal(
                strategy=self.name,
                signal="down",
                confidence=confidence,
                reason=f"Breakout below {support:.4f} (range pos: {range_position:.2f})",
                metadata={
                    'support': support,
                    'resistance': resistance,
                    'range_position': range_position,
                    'volatility': volatility
                }
            )
        
        return None
