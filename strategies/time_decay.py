"""
Time Decay Harvesting Strategy

Based on theta decay concepts from options trading, adapted for prediction markets.
In BTC 5-min markets, time decay accelerates as the window approaches expiry.

Edge: Markets often overprice uncertainty early in the window, creating
opportunities to harvest time premium as expiry approaches.

Reference: Options theta decay strategies, prediction market time premium
"""

from typing import Optional
from collections import deque
import time

from core.base_strategy import BaseStrategy, Signal, MarketData


class TimeDecayStrategy(BaseStrategy):
    """
    Harvest time premium decay in prediction markets.
    
    Key insight: Early in a 5-min window, prices reflect more uncertainty
    than near expiry. This strategy identifies overpriced uncertainty
    and captures the decay as resolution approaches.
    """
    
    name = "TimeDecay"
    description = "Harvest time premium decay as window approaches expiry"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        config = config or {}
        
        # Window timing (5 minute = 300 seconds)
        self.window_seconds = 300
        
        # Entry zones - early in window when uncertainty is highest
        self.entry_start = self.config.get('entry_start', 0.70)  # 70% into window = 210s
        self.entry_end = self.config.get('entry_end', 0.85)      # 85% into window = 255s
        
        # Price stability threshold - need stable price to establish fair value
        self.stability_threshold = self.config.get('stability_threshold', 0.005)  # 0.5%
        self.stability_window = self.config.get('stability_window', 10)
        
        # Minimum edge required
        self.min_edge = self.config.get('min_edge', 0.02)  # 2%
        
        # Price history for stability calculation
        self.price_history: deque = deque(maxlen=50)
        self.last_window = None
        self.entry_made_this_window = False
        
    def get_time_in_window(self, timestamp: float) -> float:
        """Get progress through current 5-minute window (0.0 to 1.0)."""
        window_start = (int(timestamp) // self.window_seconds) * self.window_seconds
        elapsed = timestamp - window_start
        return elapsed / self.window_seconds
    
    def is_price_stable(self) -> bool:
        """Check if price has been stable recently."""
        if len(self.price_history) < self.stability_window:
            return False
        
        recent = list(self.price_history)[-self.stability_window:]
        price_range = max(recent) - min(recent)
        avg_price = sum(recent) / len(recent)
        
        if avg_price == 0:
            return False
        
        return (price_range / avg_price) < self.stability_threshold
    
    def calculate_fair_value(self) -> float:
        """Estimate fair value based on recent price action."""
        if len(self.price_history) < 5:
            return 0.5
        
        # Use median of recent prices as fair value estimate
        recent = list(self.price_history)[-self.stability_window:]
        sorted_prices = sorted(recent)
        mid = len(sorted_prices) // 2
        
        if len(sorted_prices) % 2 == 0:
            return (sorted_prices[mid - 1] + sorted_prices[mid]) / 2
        return sorted_prices[mid]
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_time = data.timestamp
        current_price = data.price
        
        # Store price history
        self.price_history.append(current_price)
        
        # Check if we're in a new window
        current_window = int(current_time) // self.window_seconds
        if current_window != self.last_window:
            self.last_window = current_window
            self.entry_made_this_window = False
        
        # Only one entry per window
        if self.entry_made_this_window:
            return None
        
        # Check timing - must be in entry zone
        time_progress = self.get_time_in_window(current_time)
        if not (self.entry_start <= time_progress <= self.entry_end):
            return None
        
        # Need price stability to establish fair value
        if not self.is_price_stable():
            return None
        
        # Calculate fair value and edge
        fair_value = self.calculate_fair_value()
        
        # Edge calculation: how far is current price from fair value?
        # If price is above fair value, uncertainty is overpriced -> bet on NO
        # If price is below fair value, uncertainty is overpriced -> bet on YES
        edge = abs(current_price - fair_value)
        
        if edge < self.min_edge:
            return None
        
        # Generate signal
        if current_price > fair_value:
            signal = "down"  # Price too high, bet on NO
            reason = f"Time decay: Price {current_price:.3f} > fair {fair_value:.3f}, edge {edge:.1%}"
        else:
            signal = "up"  # Price too low, bet on YES
            reason = f"Time decay: Price {current_price:.3f} < fair {fair_value:.3f}, edge {edge:.1%}"
        
        # Confidence based on edge size and time remaining
        time_remaining = 1.0 - time_progress
        confidence = min(0.60 + edge * 3 + time_remaining * 0.2, 0.85)
        
        self.entry_made_this_window = True
        
        return Signal(
            strategy=self.name,
            signal=signal,
            confidence=confidence,
            reason=reason,
            metadata={
                'fair_value': fair_value,
                'current_price': current_price,
                'edge': edge,
                'time_progress': time_progress,
                'time_remaining': time_remaining
            }
        )
