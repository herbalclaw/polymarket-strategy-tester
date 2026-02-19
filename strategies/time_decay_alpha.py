"""
TimeDecayAlpha Strategy

Exploits time decay in short-term prediction markets.
As settlement approaches, binary options exhibit increasing gamma -
small probability shifts cause exponential price volatility.

Key insight: Professional traders reduce exposure as settlement approaches
to avoid terminal volatility. This creates opportunities for those who
understand the time-decay dynamics.

Time-to-Settlement Effect:
Gamma(T) ∝ 1/√(T_remaining)

Strategy reduces position sizing as settlement approaches and looks for
mean-reversion opportunities in the final minutes when retail traders
panic or overreact.

Reference: "Mathematical Execution Behind Prediction Market Alpha" - Bawa (2025)
"""

import time
import math
from typing import Optional
from collections import deque
from statistics import mean, stdev

from core.base_strategy import BaseStrategy, Signal, MarketData


class TimeDecayAlphaStrategy(BaseStrategy):
    """
    Exploit time decay dynamics in short-term prediction markets.
    
    Key principles:
    1. Gamma increases as settlement approaches (price more sensitive to prob changes)
    2. Retail traders often panic in final minutes, creating mean-reversion opportunities
    3. Reduce exposure as T → 0 to avoid terminal volatility
    
    Strategy:
    - In early window (>3 min remaining): Trade momentum/trend normally
    - In mid window (1-3 min): Look for mean reversion after large moves
    - In late window (<1 min): Only fade extreme overreactions
    """
    
    name = "TimeDecayAlpha"
    description = "Exploit time decay and terminal volatility patterns"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        
        # Window timing (5-minute windows)
        self.window_seconds = self.config.get('window_seconds', 300)
        
        # Time thresholds
        self.early_threshold = self.config.get('early_threshold', 180)  # >3 min
        self.mid_threshold = self.config.get('mid_threshold', 60)  # 1-3 min
        # <1 min = late
        
        # Price history for volatility calculation
        self.price_history: deque = deque(maxlen=100)
        self.returns_history: deque = deque(maxlen=50)
        
        # Mean reversion parameters
        self.reversion_lookback = self.config.get('reversion_lookback', 10)
        self.reversion_threshold = self.config.get('reversion_threshold', 0.015)  # 1.5% move
        
        # Late window extreme move threshold
        self.extreme_move_threshold = self.config.get('extreme_move_threshold', 0.03)  # 3%
        
        # Volatility tracking
        self.volatility_window = self.config.get('volatility_window', 20)
        
        # Confidence scaling by time phase
        self.early_confidence_boost = self.config.get('early_confidence_boost', 0.0)
        self.mid_confidence_boost = self.config.get('mid_confidence_boost', 0.05)
        self.late_confidence_boost = self.config.get('late_confidence_boost', 0.10)
        
        # Cooldown
        self.cooldown_periods = self.config.get('cooldown_periods', 5)
        self.last_signal_period = -self.cooldown_periods
        self.period_count = 0
        
        # Track window start
        self.current_window = None
        self.window_start_time = None
    
    def get_time_in_window(self) -> float:
        """Get seconds elapsed in current 5-minute window."""
        now = time.time()
        return now % self.window_seconds
    
    def get_time_remaining(self) -> float:
        """Get seconds remaining in current window."""
        return self.window_seconds - self.get_time_in_window()
    
    def get_time_phase(self) -> str:
        """
        Determine which phase of the window we're in.
        
        Returns: 'early', 'mid', or 'late'
        """
        remaining = self.get_time_remaining()
        
        if remaining > self.early_threshold:
            return 'early'
        elif remaining > self.mid_threshold:
            return 'mid'
        else:
            return 'late'
    
    def calculate_gamma_exposure(self) -> float:
        """
        Estimate gamma exposure based on time remaining.
        Gamma ∝ 1/√(T_remaining)
        """
        remaining = self.get_time_remaining()
        if remaining <= 0:
            return float('inf')
        
        # Normalize: at 300s, gamma = 1; at 1s, gamma = ~17
        gamma = math.sqrt(self.window_seconds / remaining)
        return gamma
    
    def calculate_position_scale(self) -> float:
        """
        Calculate position size scaling based on time.
        Reduce exposure as settlement approaches.
        """
        remaining = self.get_time_remaining()
        
        # Linear scaling: full size at 300s, 30% at 0s
        scale = max(0.3, remaining / self.window_seconds)
        return scale
    
    def detect_mean_reversion_opportunity(self, current_price: float) -> tuple:
        """
        Detect if current price presents mean reversion opportunity.
        
        Returns: (is_opportunity, direction, strength)
        """
        if len(self.price_history) < self.reversion_lookback:
            return False, "neutral", 0
        
        prices = list(self.price_history)
        
        # Calculate short-term moving average
        ma = mean(prices[-self.reversion_lookback:])
        
        # Calculate deviation from mean
        deviation = (current_price - ma) / ma if ma > 0 else 0
        
        # Check if move is significant
        if abs(deviation) < self.reversion_threshold:
            return False, "neutral", 0
        
        # Direction: if price is above mean, expect reversion down (fade the move)
        # But for binary options, we need to think about this differently
        # If price spiked UP (deviation > 0), probability may be overestimated
        # Signal should be DOWN (bet against the spike)
        direction = "down" if deviation > 0 else "up"
        
        # Strength based on deviation magnitude
        strength = min(abs(deviation) / self.reversion_threshold, 2.0)
        
        return True, direction, strength
    
    def detect_extreme_overreaction(self, current_price: float) -> tuple:
        """
        Detect extreme overreaction in late window.
        
        Returns: (is_extreme, direction, strength)
        """
        if len(self.price_history) < 5:
            return False, "neutral", 0
        
        prices = list(self.price_history)
        
        # Calculate very short-term change
        recent_change = (current_price - prices[-5]) / prices[-5] if prices[-5] > 0 else 0
        
        if abs(recent_change) < self.extreme_move_threshold:
            return False, "neutral", 0
        
        # Fade the extreme move
        direction = "down" if recent_change > 0 else "up"
        strength = min(abs(recent_change) / self.extreme_move_threshold, 3.0)
        
        return True, direction, strength
    
    def calculate_volatility_regime(self) -> tuple:
        """
        Calculate current volatility regime.
        
        Returns: (current_vol, avg_vol, regime)
        regime: 'low', 'normal', 'high'
        """
        if len(self.returns_history) < self.volatility_window:
            return 0, 0, 'normal'
        
        returns = list(self.returns_history)[-self.volatility_window:]
        
        try:
            current_vol = stdev(returns[-5:]) if len(returns) >= 5 else stdev(returns)
            avg_vol = stdev(returns)
        except:
            return 0, 0, 'normal'
        
        if avg_vol == 0:
            return current_vol, avg_vol, 'normal'
        
        vol_ratio = current_vol / avg_vol
        
        if vol_ratio < 0.7:
            regime = 'low'
        elif vol_ratio > 1.3:
            regime = 'high'
        else:
            regime = 'normal'
        
        return current_vol, avg_vol, regime
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_price = data.price
        self.period_count += 1
        
        # Update history
        self.price_history.append(current_price)
        
        if len(self.price_history) >= 2:
            prev = list(self.price_history)[-2]
            if prev > 0:
                ret = (current_price - prev) / prev
                self.returns_history.append(ret)
        
        # Check cooldown
        if self.period_count - self.last_signal_period < self.cooldown_periods:
            return None
        
        # Need minimum data
        if len(self.price_history) < 20:
            return None
        
        # Get time phase
        phase = self.get_time_phase()
        remaining = self.get_time_remaining()
        gamma = self.calculate_gamma_exposure()
        
        # Get volatility regime
        current_vol, avg_vol, vol_regime = self.calculate_volatility_regime()
        
        signal = None
        confidence = 0.0
        reason = ""
        metadata = {}
        
        if phase == 'early':
            # Early window: trade trend/momentum normally
            # Look for sustained directional movement
            if len(self.price_history) >= 10:
                early_mean = mean(list(self.price_history)[:10])
                recent_mean = mean(list(self.price_history)[-10:])
                
                if early_mean > 0:
                    trend = (recent_mean - early_mean) / early_mean
                    
                    if abs(trend) > 0.01:  # 1% trend
                        signal = "up" if trend > 0 else "down"
                        confidence = 0.60 + min(abs(trend) * 10, 0.15)
                        reason = f"Early trend: {trend:.2%} (remaining: {remaining:.0f}s)"
                        metadata = {
                            'phase': phase,
                            'trend': trend,
                            'remaining': remaining,
                            'gamma': gamma
                        }
        
        elif phase == 'mid':
            # Mid window: look for mean reversion after significant moves
            is_reversion, direction, strength = self.detect_mean_reversion_opportunity(current_price)
            
            if is_reversion and strength > 1.0:
                signal = direction
                base_conf = 0.62
                strength_boost = min((strength - 1) * 0.08, 0.12)
                phase_boost = self.mid_confidence_boost
                
                confidence = base_conf + strength_boost + phase_boost
                confidence = min(confidence, 0.85)
                
                reason = f"Mid-window mean reversion: {direction} (strength: {strength:.2f}, remaining: {remaining:.0f}s)"
                metadata = {
                    'phase': phase,
                    'reversion_strength': strength,
                    'remaining': remaining,
                    'gamma': gamma,
                    'vol_regime': vol_regime
                }
        
        else:  # late
            # Late window: only fade extreme overreactions
            is_extreme, direction, strength = self.detect_extreme_overreaction(current_price)
            
            if is_extreme and strength > 1.5:
                signal = direction
                base_conf = 0.65  # Higher base for late window (stronger conviction needed)
                strength_boost = min((strength - 1.5) * 0.1, 0.15)
                phase_boost = self.late_confidence_boost
                
                confidence = base_conf + strength_boost + phase_boost
                confidence = min(confidence, 0.88)
                
                reason = f"Late fade extreme: {direction} (strength: {strength:.2f}, remaining: {remaining:.0f}s)"
                metadata = {
                    'phase': phase,
                    'extreme_strength': strength,
                    'remaining': remaining,
                    'gamma': gamma,
                    'position_scale': self.calculate_position_scale()
                }
        
        if signal and confidence >= self.min_confidence:
            self.last_signal_period = self.period_count
            
            return Signal(
                strategy=self.name,
                signal=signal,
                confidence=confidence,
                reason=reason,
                metadata=metadata
            )
        
        return None
