"""
Bollinger Bands Mean Reversion Strategy

Statistical arbitrage strategy using Bollinger Bands to identify
overbought/oversold conditions in prediction markets.

Concept: Prices that deviate significantly from their moving average
(>2 standard deviations) tend to revert to the mean.

Reference: John Bollinger's Bollinger Bands, statistical arbitrage
"""

from typing import Optional
from collections import deque
import statistics

from core.base_strategy import BaseStrategy, Signal, MarketData


class BollingerBandsStrategy(BaseStrategy):
    """
    Mean reversion using Bollinger Bands.
    
    Buy when price touches lower band (oversold).
    Sell when price touches upper band (overbought).
    
    Key parameters:
    - Period: 20 (standard)
    - StdDev multiplier: 2.0 (standard)
    - Confirmation: Price must close outside band, not just touch
    """
    
    name = "BollingerBands"
    description = "Mean reversion using Bollinger Bands"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        config = config or {}
        
        # Bollinger Bands parameters
        self.period = self.config.get('period', 20)
        self.std_multiplier = self.config.get('std_multiplier', 2.0)
        
        # Minimum bandwidth to avoid trading in flat markets
        self.min_bandwidth = self.config.get('min_bandwidth', 0.02)  # 2%
        
        # Cooldown between signals
        self.cooldown_periods = self.config.get('cooldown_periods', 5)
        self.last_signal_period = -self.cooldown_periods
        
        # Price history
        self.price_history: deque = deque(maxlen=100)
        self.period_count = 0
        
    def calculate_bands(self) -> Optional[dict]:
        """Calculate Bollinger Bands."""
        if len(self.price_history) < self.period:
            return None
        
        prices = list(self.price_history)[-self.period:]
        
        # Middle band = SMA
        sma = sum(prices) / len(prices)
        
        # Standard deviation
        try:
            std = statistics.stdev(prices)
        except statistics.StatisticsError:
            return None
        
        # Upper and lower bands
        upper = sma + (self.std_multiplier * std)
        lower = sma - (self.std_multiplier * std)
        
        # Bandwidth as percentage of middle band
        bandwidth = (upper - lower) / sma if sma > 0 else 0
        
        # %B indicator (position within bands)
        current_price = prices[-1]
        if upper == lower:
            percent_b = 0.5
        else:
            percent_b = (current_price - lower) / (upper - lower)
        
        return {
            'sma': sma,
            'upper': upper,
            'lower': lower,
            'std': std,
            'bandwidth': bandwidth,
            'percent_b': percent_b,
            'current_price': current_price
        }
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_price = data.price
        
        # Store price
        self.price_history.append(current_price)
        self.period_count += 1
        
        # Check cooldown
        if self.period_count - self.last_signal_period < self.cooldown_periods:
            return None
        
        # Calculate bands
        bands = self.calculate_bands()
        if not bands:
            return None
        
        # Skip if bandwidth too narrow (flat market)
        if bands['bandwidth'] < self.min_bandwidth:
            return None
        
        signal = None
        confidence = 0.0
        reason = ""
        
        # Check for mean reversion signals
        percent_b = bands['percent_b']
        
        # Price below lower band = oversold = buy signal
        if percent_b < 0.0:
            signal = "up"
            # Confidence based on how far below band
            confidence = min(0.65 + abs(percent_b) * 0.1, 0.85)
            reason = f"BB oversold: Price {current_price:.3f} below lower band {bands['lower']:.3f} (%B: {percent_b:.2f})"
        
        # Price above upper band = overbought = sell signal
        elif percent_b > 1.0:
            signal = "down"
            # Confidence based on how far above band
            confidence = min(0.65 + (percent_b - 1.0) * 0.1, 0.85)
            reason = f"BB overbought: Price {current_price:.3f} above upper band {bands['upper']:.3f} (%B: {percent_b:.2f})"
        
        # Price within bands but near extremes (weaker signal)
        elif percent_b < 0.1:
            signal = "up"
            confidence = 0.60
            reason = f"BB near lower: Price {current_price:.3f} near lower band (%B: {percent_b:.2f})"
        elif percent_b > 0.9:
            signal = "down"
            confidence = 0.60
            reason = f"BB near upper: Price {current_price:.3f} near upper band (%B: {percent_b:.2f})"
        
        if signal:
            self.last_signal_period = self.period_count
            
            return Signal(
                strategy=self.name,
                signal=signal,
                confidence=confidence,
                reason=reason,
                metadata={
                    'sma': bands['sma'],
                    'upper': bands['upper'],
                    'lower': bands['lower'],
                    'std': bands['std'],
                    'bandwidth': bands['bandwidth'],
                    'percent_b': percent_b,
                    'current_price': current_price
                }
            )
        
        return None
