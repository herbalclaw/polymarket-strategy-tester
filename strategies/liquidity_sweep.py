"""
LiquiditySweep Strategy

Detects and trades liquidity sweeps - rapid price moves that trigger
stop losses or liquidations, followed by quick reversals.

Key insight: In prediction markets, liquidity sweeps occur when:
1. Large orders exhaust liquidity on one side of the book
2. Price overshoots fair value due to thin order books
3. Smart money absorbs the liquidity and reverses the move

Strategy detects sweep patterns and fades the move, capturing
reversion as liquidity returns.

Reference: "The Microstructure of Financial Markets" - O'Hara (1995)
"""

from typing import Optional
from collections import deque
import statistics

from core.base_strategy import BaseStrategy, Signal, MarketData


class LiquiditySweepStrategy(BaseStrategy):
    """
    Detect liquidity sweeps and trade the reversal.
    
    Sweep pattern:
    1. Rapid price move in one direction (2-3x normal speed)
    2. Volume spike (absorption)
    3. Wicks/rejection at extremes
    4. Quick reversal as liquidity returns
    
    Strategy enters on reversal confirmation after sweep.
    """
    
    name = "LiquiditySweep"
    description = "Fade liquidity sweeps and capture reversals"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        config = config or {}
        
        # Price tracking
        self.price_history = deque(maxlen=30)
        self.high_history = deque(maxlen=20)  # Track highs for upper sweep
        self.low_history = deque(maxlen=20)   # Track lows for lower sweep
        
        # Sweep detection parameters
        self.sweep_speed_threshold = self.config.get('sweep_speed_threshold', 3.0)  # 3x normal
        self.sweep_return_threshold = self.config.get('sweep_return_threshold', 0.005)  # 0.5% return
        
        # Volume tracking
        self.volume_history = deque(maxlen=20)
        self.volume_threshold = self.config.get('volume_threshold', 2.0)  # 2x avg
        
        # Wick detection
        self.wick_threshold = self.config.get('wick_threshold', 0.003)  # 0.3% wick
        
        # Recent sweep tracking
        self.recent_sweep = None  # 'up' or 'down'
        self.sweep_time = 0
        self.sweep_extreme = 0
        
        # Cooldown
        self.last_signal_time = 0
        self.cooldown_seconds = self.config.get('cooldown_seconds', 120)
        
        # Minimum data
        self.min_history = self.config.get('min_history', 10)
    
    def calculate_price_velocity(self) -> float:
        """Calculate recent price velocity (absolute change per period)."""
        if len(self.price_history) < 5:
            return 0.0
        
        prices = list(self.price_history)
        returns = []
        
        for i in range(1, min(5, len(prices))):
            if prices[i-1] > 0:
                ret = abs((prices[i] - prices[i-1]) / prices[i-1])
                returns.append(ret)
        
        if not returns:
            return 0.0
        
        return sum(returns) / len(returns)
    
    def calculate_normal_velocity(self) -> float:
        """Calculate normal (baseline) price velocity."""
        if len(self.price_history) < self.min_history:
            return 0.001  # Default 0.1%
        
        prices = list(self.price_history)
        returns = []
        
        for i in range(1, len(prices)):
            if prices[i-1] > 0:
                ret = abs((prices[i] - prices[i-1]) / prices[i-1])
                returns.append(ret)
        
        if not returns:
            return 0.001
        
        # Use median to avoid outlier influence
        return statistics.median(returns)
    
    def detect_sweep(self, current_price: float) -> tuple:
        """
        Detect if a liquidity sweep just occurred.
        Returns (is_sweep, direction, strength)
        """
        if len(self.price_history) < self.min_history:
            return False, "none", 0.0
        
        normal_velocity = self.calculate_normal_velocity()
        recent_velocity = self.calculate_price_velocity()
        
        if normal_velocity == 0:
            return False, "none", 0.0
        
        velocity_ratio = recent_velocity / normal_velocity
        
        # Check for velocity spike (sweep)
        if velocity_ratio < self.sweep_speed_threshold:
            return False, "none", 0.0
        
        # Determine direction from recent price action
        prices = list(self.price_history)
        if len(prices) < 5:
            return False, "none", 0.0
        
        recent_move = (prices[-1] - prices[-5]) / prices[-5] if prices[-5] > 0 else 0
        
        if recent_move > 0:
            return True, "up", velocity_ratio
        elif recent_move < 0:
            return True, "down", velocity_ratio
        
        return False, "none", 0.0
    
    def detect_reversal(self, sweep_direction: str) -> tuple:
        """
        Detect if price is reversing after a sweep.
        Returns (is_reversing, strength)
        """
        if len(self.price_history) < 5:
            return False, 0.0
        
        prices = list(self.price_history)
        
        # Check for reversal pattern
        if sweep_direction == "up":
            # After up sweep, look for down move
            if prices[-1] < prices[-2] < prices[-3]:
                # Three consecutive down candles
                reversal_size = (prices[-3] - prices[-1]) / prices[-3] if prices[-3] > 0 else 0
                return reversal_size > self.sweep_return_threshold, reversal_size
        
        elif sweep_direction == "down":
            # After down sweep, look for up move
            if prices[-1] > prices[-2] > prices[-3]:
                # Three consecutive up candles
                reversal_size = (prices[-1] - prices[-3]) / prices[-3] if prices[-3] > 0 else 0
                return reversal_size > self.sweep_return_threshold, reversal_size
        
        return False, 0.0
    
    def check_volume_confirmation(self) -> bool:
        """Check if volume confirms the sweep."""
        if len(self.volume_history) < 10:
            return True
        
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
        
        # Track highs/lows for sweep detection
        if self.price_history:
            self.high_history.append(max(list(self.price_history)[-3:]) if len(self.price_history) >= 3 else current_price)
            self.low_history.append(min(list(self.price_history)[-3:]) if len(self.price_history) >= 3 else current_price)
        
        # Cooldown check
        if current_time - self.last_signal_time < self.cooldown_seconds:
            return None
        
        # Need enough data
        if len(self.price_history) < self.min_history:
            return None
        
        # Check for active sweep
        is_sweep, sweep_direction, sweep_strength = self.detect_sweep(current_price)
        
        if is_sweep:
            # Record the sweep
            self.recent_sweep = sweep_direction
            self.sweep_time = current_time
            self.sweep_extreme = current_price
            return None  # Don't trade yet, wait for reversal
        
        # Check if we have a recent sweep and it's reversing
        if self.recent_sweep and (current_time - self.sweep_time) < 60:  # Within 60 seconds
            is_reversing, reversal_strength = self.detect_reversal(self.recent_sweep)
            volume_confirmed = self.check_volume_confirmation()
            
            if is_reversing:
                # Generate fade signal
                if self.recent_sweep == "up":
                    signal = "down"
                    reason = f"Fade liquidity sweep UP: reversal={reversal_strength:.2%}, strength={sweep_strength:.1f}x"
                else:
                    signal = "up"
                    reason = f"Fade liquidity sweep DOWN: reversal={reversal_strength:.2%}, strength={sweep_strength:.1f}x"
                
                # Calculate confidence
                base_confidence = 0.65
                strength_boost = min((sweep_strength - self.sweep_speed_threshold) * 0.05, 0.1)
                reversal_boost = min(reversal_strength * 10, 0.1)
                volume_boost = 0.05 if volume_confirmed else 0
                
                confidence = min(base_confidence + strength_boost + reversal_boost + volume_boost, 0.85)
                
                if confidence >= self.min_confidence:
                    self.last_signal_time = current_time
                    self.recent_sweep = None  # Reset
                    
                    return Signal(
                        strategy=self.name,
                        signal=signal,
                        confidence=confidence,
                        reason=reason,
                        metadata={
                            'sweep_direction': self.recent_sweep,
                            'sweep_strength': sweep_strength,
                            'reversal_strength': reversal_strength,
                            'volume_confirmed': volume_confirmed,
                            'time_since_sweep': current_time - self.sweep_time
                        }
                    )
        
        # Reset old sweeps
        if self.recent_sweep and (current_time - self.sweep_time) >= 60:
            self.recent_sweep = None
        
        return None
