"""
TimeDecayScalping Strategy

Exploits time decay in short-term prediction markets.
In BTC 5-minute markets, as the window approaches expiration,
time decay accelerates non-linearly. This creates predictable
patterns where:

1. Prices near 0.50 experience maximum uncertainty (high gamma)
2. Prices near extremes (0.05, 0.95) have minimal time decay
3. Theta decay is highest when time remaining is low

Strategy trades the time decay curve by:
- Shorting positions near 0.50 when time remaining is low
- Buying near extremes when time decay is minimal
- Capturing the convergence to $0 or $1 at settlement

Reference: Black-Scholes for binary options - Gamma ∝ 1/√(T_remaining)
"""

from typing import Optional
from collections import deque
import math
import statistics

from core.base_strategy import BaseStrategy, Signal, MarketData


class TimeDecayScalpingStrategy(BaseStrategy):
    """
    Exploit time decay in short-term prediction markets.
    
    Key insight: Binary options have gamma that increases as
    expiration approaches. Near 0.50, small time changes cause
    large price swings. Near extremes, time decay is minimal.
    
    Strategy:
    - When price ≈ 0.50 and time < 2 min: Expect volatility, fade extremes
    - When price near 0.05/0.95: Low time decay, hold for settlement
    - Capture the "theta" of the option
    """
    
    name = "TimeDecayScalper"
    description = "Exploits time decay in short-term prediction markets"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        config = config or {}
        
        # Time thresholds (in seconds from window end)
        self.early_phase = self.config.get('early_phase', 180)      # >3 min
        self.mid_phase = self.config.get('mid_phase', 90)           # 1.5-3 min
        self.late_phase = self.config.get('late_phase', 45)         # <45 sec
        
        # Price zones
        self.uncertainty_zone = self.config.get('uncertainty_zone', 0.15)  # 0.50 ± 0.15
        self.extreme_zone = self.config.get('extreme_zone', 0.10)          # <0.10 or >0.90
        
        # Window tracking
        self.current_window = None
        self.window_start = None
        self.window_end = None
        
        # Price history for volatility calc
        self.price_history = deque(maxlen=20)
        
        # Cooldown
        self.last_signal_time = 0
        self.cooldown_seconds = self.config.get('cooldown_seconds', 30)
        
        # Minimum edge required
        self.min_edge_bps = self.config.get('min_edge_bps', 30)
    
    def get_time_to_expiry(self, current_time: float) -> float:
        """Calculate seconds remaining in current window."""
        if not self.window_end:
            return 300  # Default to full window
        return max(0, self.window_end - current_time)
    
    def get_phase(self, time_remaining: float) -> str:
        """Determine which phase of the window we're in."""
        if time_remaining > self.early_phase:
            return "early"
        elif time_remaining > self.mid_phase:
            return "mid"
        elif time_remaining > self.late_phase:
            return "late"
        else:
            return "terminal"
    
    def calculate_gamma(self, price: float, time_remaining: float) -> float:
        """
        Approximate gamma for binary option.
        Gamma is highest near 0.50 and near expiration.
        """
        if time_remaining <= 0:
            return 0
        
        # Distance from 0.50 (max uncertainty point)
        distance_from_center = abs(price - 0.50)
        
        # Gamma decreases as we move away from center
        center_factor = max(0, 0.50 - distance_from_center) / 0.50
        
        # Gamma increases as time decreases
        time_factor = 1 / math.sqrt(max(time_remaining, 1))
        
        return center_factor * time_factor
    
    def calculate_theta(self, price: float, time_remaining: float) -> float:
        """
        Approximate time decay (theta).
        Returns expected price change per second due to time decay.
        """
        if time_remaining <= 0:
            return 0
        
        # Theta is highest near 0.50 and near expiration
        distance_from_center = abs(price - 0.50)
        center_factor = max(0, 0.50 - distance_from_center) / 0.50
        
        # Time decay accelerates near expiration
        time_factor = 1 / max(time_remaining, 1)
        
        return center_factor * time_factor * 0.001  # Scale factor
    
    def calculate_volatility(self) -> float:
        """Calculate recent price volatility."""
        if len(self.price_history) < 5:
            return 0
        
        prices = list(self.price_history)
        try:
            return statistics.stdev(prices) / statistics.mean(prices) if len(prices) > 1 else 0
        except:
            return 0
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_time = data.timestamp
        price = data.price
        
        # Update price history
        self.price_history.append(price)
        
        # Track window
        window = int(current_time // 300) * 300
        if window != self.current_window:
            self.current_window = window
            self.window_start = window
            self.window_end = window + 300
        
        # Cooldown check
        if current_time - self.last_signal_time < self.cooldown_seconds:
            return None
        
        # Calculate time metrics
        time_remaining = self.get_time_to_expiry(current_time)
        phase = self.get_phase(time_remaining)
        
        # Calculate Greeks
        gamma = self.calculate_gamma(price, time_remaining)
        theta = self.calculate_theta(price, time_remaining)
        
        # Distance from center
        distance_from_center = abs(price - 0.50)
        in_uncertainty_zone = distance_from_center < self.uncertainty_zone
        in_extreme_zone = price < self.extreme_zone or price > (1 - self.extreme_zone)
        
        signal = None
        confidence = 0.0
        reason = ""
        
        # TERMINAL PHASE: < 45 seconds remaining
        if phase == "terminal":
            if in_uncertainty_zone and gamma > 2.0:
                # High gamma near expiration - expect rapid moves
                # Fade the direction of recent momentum
                if len(self.price_history) >= 5:
                    recent_prices = list(self.price_history)[-5:]
                    momentum = recent_prices[-1] - recent_prices[0]
                    
                    if momentum > 0.01:  # Upward momentum
                        # Expect pullback due to high gamma
                        confidence = min(0.65 + gamma * 0.05, 0.80)
                        signal = "down"
                        reason = f"Terminal fade: momentum {momentum:.3f}, gamma {gamma:.2f}"
                    elif momentum < -0.01:  # Downward momentum
                        confidence = min(0.65 + gamma * 0.05, 0.80)
                        signal = "up"
                        reason = f"Terminal fade: momentum {momentum:.3f}, gamma {gamma:.2f}"
            
            elif in_extreme_zone and not in_uncertainty_zone:
                # Near extremes with little time - high probability of settlement
                if price > 0.90:
                    confidence = min(0.70 + (price - 0.90) * 2, 0.85)
                    signal = "up"
                    reason = f"Terminal extreme: price {price:.3f}, likely settle YES"
                elif price < 0.10:
                    confidence = min(0.70 + (0.10 - price) * 2, 0.85)
                    signal = "down"
                    reason = f"Terminal extreme: price {price:.3f}, likely settle NO"
        
        # LATE PHASE: 45-90 seconds
        elif phase == "late":
            if in_uncertainty_zone and gamma > 1.5:
                # High gamma, reduce exposure
                volatility = self.calculate_volatility()
                
                if volatility > 0.02:  # High volatility
                    # Fade the move
                    if len(self.price_history) >= 5:
                        recent = list(self.price_history)[-5:]
                        if recent[-1] > recent[0] + 0.02:
                            confidence = 0.65
                            signal = "down"
                            reason = f"Late phase fade: vol {volatility:.3f}, gamma {gamma:.2f}"
                        elif recent[-1] < recent[0] - 0.02:
                            confidence = 0.65
                            signal = "up"
                            reason = f"Late phase fade: vol {volatility:.3f}, gamma {gamma:.2f}"
        
        # MID PHASE: 90-180 seconds
        elif phase == "mid":
            if in_extreme_zone:
                # Near extremes with moderate time - capture low theta
                if price > 0.90:
                    confidence = 0.60
                    signal = "up"
                    reason = f"Mid phase extreme: price {price:.3f}, low theta {theta:.5f}"
                elif price < 0.10:
                    confidence = 0.60
                    signal = "down"
                    reason = f"Mid phase extreme: price {price:.3f}, low theta {theta:.5f}"
        
        if signal and confidence >= self.min_confidence:
            self.last_signal_time = current_time
            
            return Signal(
                strategy=self.name,
                signal=signal,
                confidence=confidence,
                reason=reason,
                metadata={
                    'price': price,
                    'time_remaining': time_remaining,
                    'phase': phase,
                    'gamma': gamma,
                    'theta': theta,
                    'in_uncertainty_zone': in_uncertainty_zone,
                    'in_extreme_zone': in_extreme_zone
                }
            )
        
        return None
