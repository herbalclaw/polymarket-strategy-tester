"""
MomentumIgnition Strategy

Exploits momentum ignition patterns in prediction markets where initial price moves
trigger algorithmic and retail follow-through, creating self-reinforcing trends.

Key insight: In short-term prediction markets (BTC 5-min), momentum tends to
persist for 30-60 seconds after ignition due to:
1. Algorithmic trend followers reacting to price moves
2. Retail traders FOMO-ing into moves
3. Market makers adjusting quotes in direction of move

Strategy detects momentum ignition and rides the wave for short duration.

Reference: "High Frequency Trading and Market Microstructure" - Menkveld (2016)
"""

from typing import Optional
from collections import deque
import statistics

from core.base_strategy import BaseStrategy, Signal, MarketData


class MomentumIgnitionStrategy(BaseStrategy):
    """
    Detect and trade momentum ignition patterns.
    
    Momentum ignition occurs when:
    1. Price breaks recent range with volume
    2. Order book imbalance confirms direction
    3. Short-term trend accelerates
    
    Strategy enters on ignition confirmation and holds for
    momentum continuation (typically 30-90 seconds).
    """
    
    name = "MomentumIgnition"
    description = "Trade momentum ignition and follow-through"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        
        # Price tracking
        self.price_history = deque(maxlen=30)
        self.return_history = deque(maxlen=20)
        
        # Momentum detection parameters
        self.lookback_periods = self.config.get('lookback_periods', 10)
        self.momentum_threshold = self.config.get('momentum_threshold', 0.008)  # 0.8%
        self.acceleration_threshold = self.config.get('acceleration_threshold', 0.005)
        
        # Volume confirmation
        self.volume_history = deque(maxlen=20)
        self.volume_threshold = self.config.get('volume_threshold', 1.5)  # 1.5x avg
        
        # Order book confirmation
        self.obi_threshold = self.config.get('obi_threshold', 0.55)
        
        # Range breakout detection
        self.range_lookback = self.config.get('range_lookback', 15)
        self.breakout_threshold = self.config.get('breakout_threshold', 0.006)
        
        # Cooldown
        self.last_signal_time = 0
        self.cooldown_seconds = self.config.get('cooldown_seconds', 90)
        
        # Signal tracking
        self.active_momentum = None
        self.momentum_start_time = 0
    
    def calculate_returns(self) -> list:
        """Calculate recent returns."""
        if len(self.price_history) < 2:
            return []
        
        prices = list(self.price_history)
        returns = []
        for i in range(1, len(prices)):
            if prices[i-1] > 0:
                ret = (prices[i] - prices[i-1]) / prices[i-1]
                returns.append(ret)
        return returns
    
    def calculate_momentum(self) -> float:
        """Calculate momentum over lookback period."""
        if len(self.price_history) < self.lookback_periods:
            return 0.0
        
        prices = list(self.price_history)
        early = prices[-self.lookback_periods]
        late = prices[-1]
        
        if early == 0:
            return 0.0
        
        return (late - early) / early
    
    def calculate_acceleration(self) -> float:
        """Calculate price acceleration (change in momentum)."""
        returns = self.calculate_returns()
        if len(returns) < 5:
            return 0.0
        
        # Compare recent momentum to earlier momentum
        recent = sum(returns[-3:]) / 3 if len(returns) >= 3 else 0
        earlier = sum(returns[-6:-3]) / 3 if len(returns) >= 6 else recent
        
        return recent - earlier
    
    def detect_breakout(self, current_price: float) -> tuple:
        """
        Detect if price has broken out of recent range.
        Returns (is_breakout, direction, strength)
        """
        if len(self.price_history) < self.range_lookback:
            return False, "none", 0.0
        
        prices = list(self.price_history)[-self.range_lookback:]
        price_range = max(prices) - min(prices)
        mid = (max(prices) + min(prices)) / 2
        
        if mid == 0 or price_range == 0:
            return False, "none", 0.0
        
        # Normalize range
        range_pct = price_range / mid
        
        # Check for breakout
        upper_bound = max(prices)
        lower_bound = min(prices)
        
        if current_price > upper_bound * (1 + self.breakout_threshold):
            strength = (current_price - upper_bound) / upper_bound if upper_bound > 0 else 0
            return True, "up", strength
        elif current_price < lower_bound * (1 - self.breakout_threshold):
            strength = (lower_bound - current_price) / lower_bound if lower_bound > 0 else 0
            return True, "down", strength
        
        return False, "none", 0.0
    
    def calculate_obi(self, data: MarketData) -> float:
        """Calculate order book imbalance."""
        if not data.order_book:
            return 0.0
        
        bids = data.order_book.get('bids', [])
        asks = data.order_book.get('asks', [])
        
        if not bids or not asks:
            return 0.0
        
        bid_vol = sum(float(b.get('size', 0)) for b in bids[:5])
        ask_vol = sum(float(a.get('size', 0)) for a in asks[:5])
        
        total = bid_vol + ask_vol
        if total == 0:
            return 0.0
        
        return (bid_vol - ask_vol) / total
    
    def check_volume_confirmation(self) -> bool:
        """Check if volume confirms the move."""
        if len(self.volume_history) < 10:
            return True  # Assume confirmed if no data
        
        current_vol = self.volume_history[-1] if self.volume_history else 0
        avg_vol = statistics.mean(list(self.volume_history)[-10:])
        
        if avg_vol == 0:
            return True
        
        return current_vol / avg_vol >= self.volume_threshold
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_time = data.timestamp
        current_price = data.price
        
        # Update history
        self.price_history.append(current_price)
        self.volume_history.append(data.volume_24h)
        
        # Cooldown check
        if current_time - self.last_signal_time < self.cooldown_seconds:
            return None
        
        # Need enough data
        if len(self.price_history) < self.lookback_periods + 5:
            return None
        
        # Calculate metrics
        momentum = self.calculate_momentum()
        acceleration = self.calculate_acceleration()
        is_breakout, breakout_dir, breakout_strength = self.detect_breakout(current_price)
        obi = self.calculate_obi(data)
        volume_confirmed = self.check_volume_confirmation()
        
        signal = None
        confidence = 0.0
        reason = ""
        
        # Momentum ignition detection
        # Requires: momentum + acceleration + breakout + OB confirmation
        
        if abs(momentum) > self.momentum_threshold and acceleration > self.acceleration_threshold:
            if is_breakout and volume_confirmed:
                if momentum > 0 and breakout_dir == "up":
                    # Upward momentum ignition
                    # Confirm with order book
                    if obi > self.obi_threshold:
                        confidence = min(0.65 + abs(momentum) * 5 + breakout_strength * 5 + obi * 0.1, 0.85)
                        signal = "up"
                        reason = f"Momentum ignition UP: mom={momentum:.2%}, accel={acceleration:.2%}, OBI={obi:.2f}"
                    elif obi > 0:  # Weak confirmation but still positive
                        confidence = min(0.60 + abs(momentum) * 5 + breakout_strength * 5, 0.75)
                        signal = "up"
                        reason = f"Momentum ignition UP (weak OB): mom={momentum:.2%}, accel={acceleration:.2%}"
                
                elif momentum < 0 and breakout_dir == "down":
                    # Downward momentum ignition
                    if obi < -self.obi_threshold:
                        confidence = min(0.65 + abs(momentum) * 5 + breakout_strength * 5 + abs(obi) * 0.1, 0.85)
                        signal = "down"
                        reason = f"Momentum ignition DOWN: mom={momentum:.2%}, accel={acceleration:.2%}, OBI={obi:.2f}"
                    elif obi < 0:
                        confidence = min(0.60 + abs(momentum) * 5 + breakout_strength * 5, 0.75)
                        signal = "down"
                        reason = f"Momentum ignition DOWN (weak OB): mom={momentum:.2%}, accel={acceleration:.2%}"
        
        if signal and confidence >= self.min_confidence:
            self.last_signal_time = current_time
            self.active_momentum = signal
            self.momentum_start_time = current_time
            
            return Signal(
                strategy=self.name,
                signal=signal,
                confidence=confidence,
                reason=reason,
                metadata={
                    'momentum': momentum,
                    'acceleration': acceleration,
                    'breakout_strength': breakout_strength,
                    'obi': obi,
                    'volume_confirmed': volume_confirmed
                }
            )
        
        return None
