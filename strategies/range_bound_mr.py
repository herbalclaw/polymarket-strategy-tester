"""
RangeBoundMeanReversion Strategy

Exploits range-bound behavior in BTC 5-minute prediction markets.
When prices oscillate within a defined range without strong trend,
this strategy fades moves toward range extremes and captures
reversion to the mean.

Key insight: Short-term prediction markets often exhibit range-bound
behavior due to:
1. Balanced buying/selling pressure around fair value
2. Market makers keeping prices within arbitrage bounds
3. Lack of new information in short windows

Strategy identifies ranges and trades mean reversion within them.

Reference: "Mean Reversion in Stock Prices" - Poterba & Summers (1988)
"""

from typing import Optional
from collections import deque
import statistics

from core.base_strategy import BaseStrategy, Signal, MarketData


class RangeBoundMeanReversionStrategy(BaseStrategy):
    """
    Trade mean reversion within identified price ranges.
    
    Range detection:
    1. Calculate rolling high/low over lookback period
    2. Determine if price is range-bound (range < threshold)
    3. Identify position within range (0 = low, 1 = high)
    
    Trading logic:
    - Near range high (0.85-1.0): Fade longs, expect reversion down
    - Near range low (0.0-0.15): Fade shorts, expect reversion up
    - Mid-range: No trade (uncertain direction)
    """
    
    name = "RangeBoundMeanReversion"
    description = "Mean reversion within identified price ranges"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        config = config or {}
        
        # Range detection parameters
        self.lookback_periods = self.config.get('lookback_periods', 20)
        self.max_range_pct = self.config.get('max_range_pct', 0.03)  # 3% max range
        self.min_range_pct = self.config.get('min_range_pct', 0.008)  # 0.8% min range
        
        # Position within range thresholds
        self.high_threshold = self.config.get('high_threshold', 0.85)
        self.low_threshold = self.config.get('low_threshold', 0.15)
        
        # Confirmation parameters
        self.touch_count_threshold = self.config.get('touch_count_threshold', 2)
        self.confirmation_lookback = self.config.get('confirmation_lookback', 10)
        
        # Bollinger Band confirmation
        self.use_bb_confirmation = self.config.get('use_bb_confirmation', True)
        self.bb_period = self.config.get('bb_period', 15)
        self.bb_std = self.config.get('bb_std', 2.0)
        
        # History tracking
        self.price_history = deque(maxlen=50)
        self.range_history = deque(maxlen=10)
        self.position_history = deque(maxlen=20)
        
        # Touch tracking for range validation
        self.high_touches = 0
        self.low_touches = 0
        self.last_high_touch = 0
        self.last_low_touch = 0
        
        # Cooldown
        self.last_signal_time = 0
        self.cooldown_seconds = self.config.get('cooldown_seconds', 60)
        
        # Current range state
        self.current_range_low = None
        self.current_range_high = None
        self.range_mid = None
        self.is_range_bound = False
    
    def calculate_bollinger_bands(self) -> tuple:
        """Calculate Bollinger Bands. Returns (upper, middle, lower)."""
        if len(self.price_history) < self.bb_period:
            return None, None, None
        
        prices = list(self.price_history)[-self.bb_period:]
        middle = statistics.mean(prices)
        
        try:
            std = statistics.stdev(prices)
        except:
            std = 0
        
        upper = middle + self.bb_std * std
        lower = middle - self.bb_std * std
        
        return upper, middle, lower
    
    def detect_range(self) -> tuple:
        """
        Detect if price is in a range-bound regime.
        Returns (is_range_bound, range_low, range_high, range_size)
        """
        if len(self.price_history) < self.lookback_periods:
            return False, 0, 0, 0
        
        prices = list(self.price_history)[-self.lookback_periods:]
        range_low = min(prices)
        range_high = max(prices)
        range_mid = (range_low + range_high) / 2
        
        if range_mid == 0:
            return False, 0, 0, 0
        
        range_size = (range_high - range_low) / range_mid
        
        # Check if range is within bounds
        is_range_bound = self.min_range_pct <= range_size <= self.max_range_pct
        
        return is_range_bound, range_low, range_high, range_size
    
    def get_position_in_range(self, price: float, range_low: float, range_high: float) -> float:
        """
        Get position within range (0 = at low, 1 = at high, 0.5 = mid).
        """
        if range_high == range_low:
            return 0.5
        
        position = (price - range_low) / (range_high - range_low)
        return max(0, min(1, position))
    
    def count_range_touches(self, range_low: float, range_high: float) -> tuple:
        """
        Count how many times price has touched range boundaries recently.
        Returns (high_touches, low_touches).
        """
        if len(self.price_history) < self.confirmation_lookback:
            return 0, 0
        
        prices = list(self.price_history)[-self.confirmation_lookback:]
        
        high_touches = sum(1 for p in prices if p >= range_high * 0.998)
        low_touches = sum(1 for p in prices if p <= range_low * 1.002)
        
        return high_touches, low_touches
    
    def check_mean_reversion_setup(self, position: float, range_low: float, range_high: float) -> tuple:
        """
        Check if we have a valid mean reversion setup.
        Returns (has_setup, direction, confidence_boost).
        """
        high_touches, low_touches = self.count_range_touches(range_low, range_high)
        
        # Near high with multiple touches = fade longs
        if position > self.high_threshold and high_touches >= self.touch_count_threshold:
            return True, "down", min(high_touches * 0.03, 0.1)
        
        # Near low with multiple touches = fade shorts
        if position < self.low_threshold and low_touches >= self.touch_count_threshold:
            return True, "up", min(low_touches * 0.03, 0.1)
        
        return False, "none", 0.0
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_time = data.timestamp
        current_price = data.price
        
        # Update history
        self.price_history.append(current_price)
        
        # Cooldown check
        if current_time - self.last_signal_time < self.cooldown_seconds:
            return None
        
        # Need enough data
        if len(self.price_history) < self.lookback_periods:
            return None
        
        # Detect range
        is_range_bound, range_low, range_high, range_size = self.detect_range()
        self.is_range_bound = is_range_bound
        self.current_range_low = range_low
        self.current_range_high = range_high
        self.range_mid = (range_low + range_high) / 2
        
        if not is_range_bound:
            return None
        
        # Get position within range
        position = self.get_position_in_range(current_price, range_low, range_high)
        self.position_history.append(position)
        
        # Check for mean reversion setup
        has_setup, direction, confidence_boost = self.check_mean_reversion_setup(
            position, range_low, range_high
        )
        
        if not has_setup:
            return None
        
        # Calculate base confidence
        base_confidence = 0.60
        
        # Add confidence based on how extreme the position is
        if direction == "down":
            extreme_boost = (position - self.high_threshold) * 0.3
        else:
            extreme_boost = (self.low_threshold - position) * 0.3
        
        confidence = min(base_confidence + confidence_boost + extreme_boost, 0.80)
        
        # Bollinger Band confirmation
        if self.use_bb_confirmation:
            upper, middle, lower = self.calculate_bollinger_bands()
            if upper and lower:
                if direction == "down" and current_price < upper:
                    confidence -= 0.05  # Not at upper band, reduce confidence
                elif direction == "up" and current_price > lower:
                    confidence -= 0.05
        
        if confidence >= self.min_confidence:
            self.last_signal_time = current_time
            
            high_touches, low_touches = self.count_range_touches(range_low, range_high)
            
            return Signal(
                strategy=self.name,
                signal=direction,
                confidence=confidence,
                reason=f"Range reversion {direction}: pos={position:.2f} in [{range_low:.3f}, {range_high:.3f}], touches={high_touches if direction=='down' else low_touches}",
                metadata={
                    'position_in_range': position,
                    'range_low': range_low,
                    'range_high': range_high,
                    'range_size': range_size,
                    'high_touches': high_touches,
                    'low_touches': low_touches,
                    'range_mid': self.range_mid
                }
            )
        
        return None
