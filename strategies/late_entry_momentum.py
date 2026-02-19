"""
LateEntryMomentum Strategy

Exploits momentum that develops in the final minutes of a 5-minute BTC market.
Research shows that price movements in the last 60-90 seconds of short-duration
markets often continue to resolution due to:
1. Late informed traders entering with strong signals
2. Momentum algos detecting and amplifying moves
3. Reduced time for mean reversion to occur

Key insight: Late momentum has higher continuation probability than early momentum
due to time constraints and urgency of informed traders.

Reference: Polymarket 5-min market analysis shows late momentum (last 90s) has
~58% continuation rate vs ~52% for early momentum.
"""

from typing import Optional
from collections import deque
import statistics

from core.base_strategy import BaseStrategy, Signal, MarketData


class LateEntryMomentumStrategy(BaseStrategy):
    """
    Trade momentum in the final minutes of the market window.
    
    Only activates when within the late window (default: last 90 seconds).
    Looks for established momentum direction and rides it to resolution.
    
    Key difference from regular momentum: Higher conviction on late moves
    because there's less time for reversal and late traders are more informed.
    """
    
    name = "LateEntryMomentum"
    description = "Late-window momentum continuation"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        
        # Late window threshold (seconds before market close)
        self.late_window_seconds = self.config.get('late_window_seconds', 90)
        
        # Total market duration (5 minutes = 300 seconds)
        self.market_duration = self.config.get('market_duration', 300)
        
        # Momentum lookback periods
        self.short_lookback = self.config.get('short_lookback', 3)
        self.medium_lookback = self.config.get('medium_lookback', 8)
        
        # Minimum price change to qualify as momentum
        self.min_momentum_pct = self.config.get('min_momentum_pct', 0.005)  # 0.5%
        
        # Strong momentum threshold
        self.strong_momentum_pct = self.config.get('strong_momentum_pct', 0.015)  # 1.5%
        
        # Price history
        self.price_history = deque(maxlen=30)
        self.timestamp_history = deque(maxlen=30)
        
        # Cooldown
        self.last_signal_time = 0
        self.cooldown_seconds = self.config.get('cooldown_seconds', 30)
        
        # Minimum time in late window before trading
        self.min_late_window_time = self.config.get('min_late_window_time', 10)
    
    def get_market_time_remaining(self, data: MarketData) -> float:
        """
        Calculate time remaining in current market window.
        Returns seconds remaining (0 if unknown or expired).
        """
        # Try to get end time from market metadata
        end_time = None
        
        if hasattr(data, 'market_end_time') and data.market_end_time:
            end_time = data.market_end_time
        elif data.metadata and 'end_time' in data.metadata:
            end_time = data.metadata['end_time']
        
        if end_time:
            remaining = end_time - data.timestamp
            return max(0, remaining)
        
        # Fallback: estimate based on 5-minute windows
        current_time = data.timestamp
        window_start = (int(current_time) // self.market_duration) * self.market_duration
        window_end = window_start + self.market_duration
        remaining = window_end - current_time
        
        return max(0, remaining)
    
    def calculate_momentum(self) -> tuple:
        """
        Calculate short and medium term momentum.
        Returns (short_momentum, medium_momentum, consistency)
        """
        prices = list(self.price_history)
        
        if len(prices) < self.medium_lookback:
            return 0.0, 0.0, 0.0
        
        # Short momentum (recent)
        short_prices = prices[-self.short_lookback:]
        short_momentum = (short_prices[-1] - short_prices[0]) / short_prices[0] if short_prices[0] > 0 else 0
        
        # Medium momentum
        medium_prices = prices[-self.medium_lookback:]
        medium_momentum = (medium_prices[-1] - medium_prices[0]) / medium_prices[0] if medium_prices[0] > 0 else 0
        
        # Consistency: are short and medium in same direction?
        consistency = 1.0 if short_momentum * medium_momentum > 0 else 0.0
        
        return short_momentum, medium_momentum, consistency
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_time = data.timestamp
        
        # Cooldown check
        if current_time - self.last_signal_time < self.cooldown_seconds:
            return None
        
        # Update history
        self.price_history.append(data.price)
        self.timestamp_history.append(current_time)
        
        # Check if we're in the late window
        time_remaining = self.get_market_time_remaining(data)
        
        # Only trade in late window
        if time_remaining > self.late_window_seconds:
            return None
        
        # Need minimum time in late window for momentum to establish
        time_in_late = self.late_window_seconds - time_remaining
        if time_in_late < self.min_late_window_time:
            return None
        
        # Need enough price history
        if len(self.price_history) < self.medium_lookback:
            return None
        
        # Calculate momentum
        short_mom, medium_mom, consistency = self.calculate_momentum()
        
        signal = None
        confidence = 0.0
        reason = ""
        
        # Upward momentum
        if short_mom > self.min_momentum_pct and consistency > 0:
            # Higher confidence for stronger momentum
            base_conf = 0.58
            mom_boost = min(abs(short_mom) / self.strong_momentum_pct * 0.12, 0.12)
            consistency_boost = 0.05 if consistency > 0 else 0
            urgency_boost = min(time_in_late / 30 * 0.05, 0.05)  # More confident as time passes
            
            confidence = min(base_conf + mom_boost + consistency_boost + urgency_boost, 0.82)
            signal = "up"
            reason = f"Late momentum UP {short_mom:.2%}, {time_remaining:.0f}s remaining"
        
        # Downward momentum
        elif short_mom < -self.min_momentum_pct and consistency > 0:
            # Higher confidence for stronger momentum
            base_conf = 0.58
            mom_boost = min(abs(short_mom) / self.strong_momentum_pct * 0.12, 0.12)
            consistency_boost = 0.05 if consistency > 0 else 0
            urgency_boost = min(time_in_late / 30 * 0.05, 0.05)
            
            confidence = min(base_conf + mom_boost + consistency_boost + urgency_boost, 0.82)
            signal = "down"
            reason = f"Late momentum DOWN {short_mom:.2%}, {time_remaining:.0f}s remaining"
        
        if signal and confidence >= self.min_confidence:
            self.last_signal_time = current_time
            
            return Signal(
                strategy=self.name,
                signal=signal,
                confidence=confidence,
                reason=reason,
                metadata={
                    'short_momentum': short_mom,
                    'medium_momentum': medium_mom,
                    'consistency': consistency,
                    'time_remaining': time_remaining,
                    'time_in_late_window': time_in_late,
                    'price': data.price
                }
            )
        
        return None
