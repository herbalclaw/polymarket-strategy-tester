"""
AsymmetricMomentum Strategy

Exploits the asymmetric payoff structure of prediction markets.
In binary outcomes, upside is capped at $1.00 but probability of 
moving toward certainty is non-linear. This creates asymmetric
momentum patterns where:
- Prices near 0.50 have highest volatility and directional potential
- Prices near extremes (0.05, 0.95) have mean-reversion tendencies
- Momentum is stronger when moving toward 0.50 than away from it

Key insight: The "gamma" of prediction markets is highest at 0.50
and approaches zero at extremes. This creates exploitable dynamics
where momentum strategies should be more aggressive near mid prices
and fade moves near extremes.

Reference: Prediction market microstructure research
"""

from typing import Optional
from collections import deque
import statistics
import math

from core.base_strategy import BaseStrategy, Signal, MarketData


class AsymmetricMomentumStrategy(BaseStrategy):
    """
    Exploit asymmetric momentum patterns in prediction markets.
    
    Strategy logic:
    1. Calculate "market gamma" - sensitivity to price changes
       Gamma is highest at 0.50, lowest at extremes
    2. Adjust momentum thresholds based on current gamma
    3. Near 0.50: More aggressive momentum following
    4. Near extremes: Fade momentum (mean reversion)
    5. Use price velocity and acceleration for timing
    
    Mathematical basis:
    - Binary option gamma: Γ = 1 / (σ * sqrt(T) * price * (1-price))
    - Higher gamma = more explosive moves possible
    - Lower gamma = moves slow down near bounds
    """
    
    name = "AsymmetricMomentum"
    description = "Exploit asymmetric momentum patterns based on market gamma"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        config = config or {}
        
        # Price history
        self.price_history = deque(maxlen=30)
        self.velocity_history = deque(maxlen=20)
        self.acceleration_history = deque(maxlen=10)
        
        # Gamma calculation
        self.time_to_expiry_hours = self.config.get('time_to_expiry_hours', 0.08)  # 5 min = 0.08 hours
        self.implied_vol = self.config.get('implied_vol', 0.80)  # 80% annual vol for crypto
        
        # Thresholds (adjusted by gamma)
        self.base_momentum_threshold = self.config.get('base_momentum_threshold', 0.005)  # 0.5%
        self.extreme_threshold = self.config.get('extreme_threshold', 0.15)  # 15% from bounds
        
        # Position in price spectrum
        self.mid_zone = self.config.get('mid_zone', (0.35, 0.65))  # High gamma zone
        self.extreme_zone = self.config.get('extreme_zone', (0.05, 0.95))  # Low gamma zone
        
        # Cooldown
        self.last_signal_time = 0
        self.cooldown_seconds = self.config.get('cooldown_seconds', 45)
        
        # Minimum data requirements
        self.min_history = self.config.get('min_history', 5)
        
        # Confirmation
        self.confirmation_periods = self.config.get('confirmation_periods', 2)
        self.consecutive_signals = 0
        self.last_signal_type = None
    
    def calculate_gamma(self, price: float) -> float:
        """
        Calculate approximate gamma for binary option.
        Gamma ∝ 1 / (price * (1-price))
        Max at 0.50, approaches infinity near bounds
        """
        if price <= 0.01 or price >= 0.99:
            return 0.0
        
        # Simplified gamma (proportional)
        gamma = 1.0 / (price * (1.0 - price))
        
        # Normalize: at 0.50, gamma = 4.0
        return gamma
    
    def get_price_zone(self, price: float) -> str:
        """Determine which price zone we're in."""
        if price < self.extreme_zone[0] or price > self.extreme_zone[1]:
            return "extreme"
        elif price < self.mid_zone[0] or price > self.mid_zone[1]:
            return "transition"
        else:
            return "mid"
    
    def calculate_velocity_and_acceleration(self) -> tuple:
        """Calculate price velocity and acceleration."""
        if len(self.price_history) < self.min_history:
            return 0.0, 0.0
        
        prices = list(self.price_history)
        
        # Velocity: rate of change
        velocity = (prices[-1] - prices[-self.min_history]) / prices[-self.min_history]
        self.velocity_history.append(velocity)
        
        # Acceleration: change in velocity
        if len(self.velocity_history) >= 3:
            velocities = list(self.velocity_history)
            acceleration = velocities[-1] - velocities[-3]
            self.acceleration_history.append(acceleration)
        else:
            acceleration = 0.0
        
        return velocity, acceleration
    
    def adjust_threshold_by_zone(self, base_threshold: float, zone: str) -> float:
        """Adjust momentum threshold based on price zone."""
        if zone == "mid":
            # Mid zone: lower threshold = more sensitive
            return base_threshold * 0.7
        elif zone == "transition":
            return base_threshold * 1.0
        else:  # extreme
            # Extreme zone: higher threshold = less sensitive (fade moves)
            return base_threshold * 1.5
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_time = data.timestamp
        price = data.price
        
        # Cooldown check
        if current_time - self.last_signal_time < self.cooldown_seconds:
            return None
        
        # Update history
        self.price_history.append(price)
        
        if len(self.price_history) < self.min_history:
            return None
        
        # Calculate metrics
        gamma = self.calculate_gamma(price)
        zone = self.get_price_zone(price)
        velocity, acceleration = self.calculate_velocity_and_acceleration()
        
        # Adjust threshold by zone
        threshold = self.adjust_threshold_by_zone(self.base_momentum_threshold, zone)
        
        signal = None
        confidence = 0.0
        reason = ""
        
        if zone == "mid":
            # Mid zone: Follow momentum (high gamma = explosive moves)
            if velocity > threshold and acceleration >= 0:
                signal = "up"
                confidence = min(0.60 + abs(velocity) * 10 + gamma * 0.05, 0.85)
                reason = f"Mid-zone momentum: vel={velocity:.2%}, gamma={gamma:.1f}"
            elif velocity < -threshold and acceleration <= 0:
                signal = "down"
                confidence = min(0.60 + abs(velocity) * 10 + gamma * 0.05, 0.85)
                reason = f"Mid-zone momentum: vel={velocity:.2%}, gamma={gamma:.1f}"
        
        elif zone == "extreme":
            # Extreme zone: Fade momentum (mean reversion)
            # But only if move is against the dominant side
            if price < self.extreme_zone[0]:
                # Near 0 - fade further down moves
                if velocity < -threshold * 0.5:
                    signal = "up"
                    confidence = min(0.60 + abs(velocity) * 15, 0.80)
                    reason = f"Extreme fade: price={price:.2f}, fading down move"
            elif price > self.extreme_zone[1]:
                # Near 1 - fade further up moves
                if velocity > threshold * 0.5:
                    signal = "down"
                    confidence = min(0.60 + abs(velocity) * 15, 0.80)
                    reason = f"Extreme fade: price={price:.2f}, fading up move"
        
        else:  # transition zone
            # Transition: Moderate momentum following
            if velocity > threshold and acceleration > 0:
                signal = "up"
                confidence = min(0.60 + abs(velocity) * 8, 0.75)
                reason = f"Transition momentum: vel={velocity:.2%}, accel={acceleration:.2%}"
            elif velocity < -threshold and acceleration < 0:
                signal = "down"
                confidence = min(0.60 + abs(velocity) * 8, 0.75)
                reason = f"Transition momentum: vel={velocity:.2%}, accel={acceleration:.2%}"
        
        # Confirmation logic
        if signal:
            if signal == self.last_signal_type:
                self.consecutive_signals += 1
            else:
                self.consecutive_signals = 1
                self.last_signal_type = signal
            
            # Require confirmation in extreme zones
            if zone == "extreme" and self.consecutive_signals < self.confirmation_periods:
                return None
            
            if confidence >= self.min_confidence:
                self.last_signal_time = current_time
                
                return Signal(
                    strategy=self.name,
                    signal=signal,
                    confidence=confidence,
                    reason=reason,
                    metadata={
                        'price': price,
                        'zone': zone,
                        'gamma': gamma,
                        'velocity': velocity,
                        'acceleration': acceleration,
                        'threshold': threshold
                    }
                )
        
        return None
