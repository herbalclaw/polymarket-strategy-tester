"""
GammaScalp Strategy

Exploits realized volatility vs implied volatility dynamics in 
prediction markets. When markets exhibit high gamma (rapid price
changes near 50 cents), scalping small moves becomes profitable.

Key insight: Near 50 cents, prediction markets have maximum gamma -
small probability changes cause large price moves. By detecting
volatility expansion and contraction cycles, we can scalp the
oscillations.

Reference: "Dynamic Hedging" - Taleb (1997)
"""

from typing import Optional
from collections import deque
import statistics
import math

from core.base_strategy import BaseStrategy, Signal, MarketData


class GammaScalpStrategy(BaseStrategy):
    """
    Scalp gamma near 50-cent levels where price sensitivity is highest.
    
    Strategy logic:
    1. Monitor realized volatility over short windows
    2. Detect when price is near 50 cents (high gamma zone)
    3. Trade volatility expansion (breakout) or contraction (fade)
    4. Use tight stops due to high gamma risk
    
    Best suited for 5-minute markets with frequent price oscillations.
    """
    
    name = "GammaScalp"
    description = "Gamma scalping near 50-cent high-sensitivity zone"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        config = config or {}
        
        # Gamma zone definition (near 50 cents)
        self.gamma_center = self.config.get('gamma_center', 0.50)
        self.gamma_zone_width = self.config.get('gamma_zone_width', 0.10)  # 40-60 cents
        
        # Volatility tracking
        self.price_history = deque(maxlen=30)
        self.return_history = deque(maxlen=20)
        self.volatility_window = self.config.get('volatility_window', 10)
        
        # Volatility thresholds
        self.vol_expansion_threshold = self.config.get('vol_expansion_threshold', 1.5)  # 1.5x normal
        self.vol_contraction_threshold = self.config.get('vol_contraction_threshold', 0.6)  # 60% of normal
        
        # Minimum volatility for signal
        self.min_volatility = self.config.get('min_volatility', 0.005)  # 0.5%
        
        # Trend detection
        self.trend_window = self.config.get('trend_window', 5)
        
        # Cooldown
        self.last_signal_time = 0
        self.cooldown_seconds = self.config.get('cooldown_seconds', 90)
        
        # Volatility regime tracking
        self.vol_regime = "normal"  # "expanding", "contracting", "normal"
        self.regime_start_time = 0
        
        # Position tracking for mean reversion
        self.last_trade_price = None
    
    def in_gamma_zone(self, price: float) -> bool:
        """Check if price is in the high-gamma zone near 50 cents."""
        return abs(price - self.gamma_center) <= self.gamma_zone_width
    
    def calculate_realized_volatility(self) -> float:
        """Calculate realized volatility from recent returns."""
        if len(self.return_history) < self.volatility_window:
            return 0.0
        
        returns = list(self.return_history)[-self.volatility_window:]
        
        if len(returns) < 2:
            return 0.0
        
        # Annualized volatility (assuming 5-min periods, ~288 periods/day)
        # Using simplified calculation for short windows
        mean_return = statistics.mean(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        
        vol = math.sqrt(variance)
        return vol
    
    def calculate_average_volatility(self) -> float:
        """Calculate average volatility over longer window."""
        if len(self.return_history) < self.volatility_window * 2:
            return self.min_volatility
        
        returns = list(self.return_history)
        
        # Split into two halves
        mid = len(returns) // 2
        first_half = returns[:mid]
        
        if len(first_half) < 2:
            return self.min_volatility
        
        mean_ret = statistics.mean(first_half)
        variance = sum((r - mean_ret) ** 2 for r in first_half) / len(first_half)
        
        return math.sqrt(variance) if variance > 0 else self.min_volatility
    
    def detect_volatility_regime(self) -> str:
        """Detect current volatility regime."""
        current_vol = self.calculate_realized_volatility()
        avg_vol = self.calculate_average_volatility()
        
        if avg_vol == 0:
            return "normal"
        
        vol_ratio = current_vol / avg_vol
        
        if vol_ratio > self.vol_expansion_threshold and current_vol > self.min_volatility:
            return "expanding"
        elif vol_ratio < self.vol_contraction_threshold:
            return "contracting"
        else:
            return "normal"
    
    def get_trend_direction(self) -> float:
        """Get recent trend direction (-1 to 1)."""
        if len(self.price_history) < self.trend_window:
            return 0.0
        
        prices = list(self.price_history)[-self.trend_window:]
        
        if len(prices) < 2 or prices[0] == 0:
            return 0.0
        
        return (prices[-1] - prices[0]) / prices[0]
    
    def calculate_gamma(self, price: float) -> float:
        """
        Approximate gamma for a binary option near 50 cents.
        Gamma is highest at 50 cents and decreases toward extremes.
        Simplified calculation for prediction markets.
        """
        # Gamma is inversely proportional to distance from 50 cents
        distance = abs(price - self.gamma_center)
        if distance >= self.gamma_zone_width:
            return 0.0
        
        # Peak gamma at center, linear decrease
        gamma = 1.0 - (distance / self.gamma_zone_width)
        return gamma
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_time = data.timestamp
        current_price = data.price
        
        # Update history
        self.price_history.append(current_price)
        
        # Calculate return
        if len(self.price_history) >= 2:
            prices = list(self.price_history)
            ret = (prices[-1] - prices[-2]) / prices[-2] if prices[-2] > 0 else 0
            self.return_history.append(ret)
        
        # Cooldown check
        if current_time - self.last_signal_time < self.cooldown_seconds:
            return None
        
        # Need enough data
        if len(self.return_history) < self.volatility_window:
            return None
        
        # Only trade in gamma zone
        if not self.in_gamma_zone(current_price):
            return None
        
        # Detect volatility regime
        new_regime = self.detect_volatility_regime()
        
        # Track regime changes
        if new_regime != self.vol_regime:
            self.vol_regime = new_regime
            self.regime_start_time = current_time
        
        current_vol = self.calculate_realized_volatility()
        gamma = self.calculate_gamma(current_price)
        trend = self.get_trend_direction()
        
        signal = None
        confidence = 0.0
        reason = ""
        
        # Strategy 1: Volatility expansion breakout
        # When vol expands in gamma zone, trade the momentum direction
        if self.vol_regime == "expanding":
            # Trade in direction of recent trend
            if abs(trend) > 0.001:  # Minimum trend threshold
                base_confidence = 0.62
                vol_boost = min(current_vol * 50, 0.10)  # Cap at 0.10
                gamma_boost = gamma * 0.08
                
                confidence = base_confidence + vol_boost + gamma_boost
                confidence = min(confidence, 0.85)
                
                if trend > 0:
                    signal = "up"
                    reason = f"Gamma scalp UP: vol_expanding, trend={trend:.3f}, gamma={gamma:.2f}"
                else:
                    signal = "down"
                    reason = f"Gamma scalp DOWN: vol_expanding, trend={trend:.3f}, gamma={gamma:.2f}"
        
        # Strategy 2: Volatility contraction fade
        # After high vol, fade the move as volatility compresses
        elif self.vol_regime == "contracting":
            # Check if we've had a significant move to fade
            if len(self.price_history) >= 5:
                prices = list(self.price_history)
                recent_move = (prices[-1] - prices[-5]) / prices[-5] if prices[-5] > 0 else 0
                
                # Fade significant moves as vol contracts
                if abs(recent_move) > 0.01:  # >1% move
                    base_confidence = 0.58
                    vol_boost = min((1 - current_vol / self.min_volatility) * 0.05, 0.05)
                    gamma_boost = gamma * 0.05
                    
                    confidence = base_confidence + vol_boost + gamma_boost
                    confidence = min(confidence, 0.78)
                    
                    if recent_move > 0:
                        signal = "down"  # Fade the up move
                        reason = f"Gamma fade DOWN: vol_contracting, move={recent_move:.3f}"
                    else:
                        signal = "up"  # Fade the down move
                        reason = f"Gamma fade UP: vol_contracting, move={recent_move:.3f}"
        
        # Strategy 3: Mean reversion to 50 cents
        # In gamma zone, prices tend to oscillate around 50
        elif len(self.price_history) >= 10:
            # Check if price has deviated from center
            deviation = current_price - self.gamma_center
            
            if abs(deviation) > 0.03:  # More than 3 cents from 50
                # Check for reversal signs
                prices = list(self.price_history)
                recent_trend = (prices[-1] - prices[-3]) / prices[-3] if prices[-3] > 0 else 0
                
                # If trending away from center, expect reversion
                if (deviation > 0 and recent_trend > 0) or (deviation < 0 and recent_trend < 0):
                    # Price moving further from center - don't fight it
                    pass
                elif (deviation > 0 and recent_trend < 0) or (deviation < 0 and recent_trend > 0):
                    # Price reversing toward center
                    base_confidence = 0.55
                    deviation_boost = min(abs(deviation) * 2, 0.15)
                    
                    confidence = base_confidence + deviation_boost
                    confidence = min(confidence, 0.75)
                    
                    if deviation > 0:
                        signal = "down"  # Revert to 50 from above
                        reason = f"Gamma mean rev DOWN: deviation={deviation:.3f}, reverting"
                    else:
                        signal = "up"  # Revert to 50 from below
                        reason = f"Gamma mean rev UP: deviation={deviation:.3f}, reverting"
        
        if signal and confidence >= self.min_confidence:
            self.last_signal_time = current_time
            self.last_trade_price = current_price
            
            return Signal(
                strategy=self.name,
                signal=signal,
                confidence=confidence,
                reason=reason,
                metadata={
                    'price': current_price,
                    'gamma': gamma,
                    'volatility': current_vol,
                    'regime': self.vol_regime,
                    'trend': trend,
                    'in_gamma_zone': True
                }
            )
        
        return None
