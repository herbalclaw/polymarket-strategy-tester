"""
ContrarianExtreme Strategy

Exploits retail overreaction at price extremes (behavioral bias).
Research shows 79.6% of Polymarket markets resolve as "NO" - 
retail traders overpay for "exciting" YES outcomes.

Key insight: Extreme prices (>0.92 or <0.08) often reverse due to:
1. Overreaction to recent news
2. Behavioral bias toward exciting outcomes
3. Time decay working against expensive positions
4. Mean reversion in probabilities

This is a high-conviction, low-frequency strategy that only
trades at extremes with strong expected value.

Reference: Polymarket accuracy analysis - 79.6% NO resolution rate
"""

from typing import Optional
from collections import deque
from statistics import mean

from core.base_strategy import BaseStrategy, Signal, MarketData


class ContrarianExtremeStrategy(BaseStrategy):
    """
    Fade price extremes based on behavioral bias.
    
    When prices reach extremes (>0.92 or <0.08), retail traders
    have typically overreacted. The contrarian position offers:
    1. Better risk/reward (buying cheap, selling expensive)
    2. Time decay working in favor
    3. Mean reversion edge
    4. Asymmetric payoff
    """
    
    name = "ContrarianExtreme"
    description = "Fade price extremes exploiting retail overreaction"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        config = config or {}
        
        # Price history
        self.price_history: deque = deque(maxlen=50)
        
        # Extreme thresholds
        self.high_extreme = self.config.get('high_extreme', 0.92)  # Sell YES above this
        self.low_extreme = self.config.get('low_extreme', 0.08)    # Buy YES below this
        
        # Safety bounds (don't trade beyond these)
        self.max_price = self.config.get('max_price', 0.98)
        self.min_price = self.config.get('min_price', 0.02)
        
        # Time to expiry consideration (in periods)
        self.min_time_remaining = self.config.get('min_time_remaining', 10)  # ~50 min
        self.max_time_remaining = self.config.get('max_time_remaining', 200)  # ~16 hours
        
        # Confirmation requirements
        self.require_reversal_candle = self.config.get('require_reversal_candle', True)
        self.reversal_threshold = self.config.get('reversal_threshold', 0.005)  # 0.5% move
        
        # Position sizing (this strategy uses larger sizes due to high conviction)
        self.confidence_boost = self.config.get('confidence_boost', 0.1)
        
        # Minimum confidence
        self.min_confidence = self.config.get('min_confidence', 0.65)
        
        # Cooldown (longer due to low frequency nature)
        self.cooldown_periods = self.config.get('cooldown_periods', 15)
        self.last_signal_period = -self.cooldown_periods
        self.period_count = 0
        
        # Track extreme duration
        self.extreme_duration = 0
        self.in_extreme_zone = False
        self.extreme_zone_type = None  # 'high' or 'low'
    
    def get_price_momentum(self) -> float:
        """Calculate price momentum over recent periods."""
        if len(self.price_history) < 5:
            return 0
        
        prices = list(self.price_history)
        recent = prices[-3:]
        earlier = prices[-8:-3] if len(prices) >= 8 else prices[:len(prices)//2]
        
        if not earlier:
            return 0
        
        recent_avg = mean(recent)
        earlier_avg = mean(earlier)
        
        if earlier_avg == 0:
            return 0
        
        return (recent_avg - earlier_avg) / earlier_avg
    
    def detect_reversal_candle(self, current_price: float) -> tuple:
        """
        Detect if price is showing reversal signs.
        Returns (is_reversal, direction)
        """
        if len(self.price_history) < 3:
            return False, "none"
        
        prices = list(self.price_history)
        
        # Check for momentum shift
        momentum = self.get_price_momentum()
        
        # At high extreme, look for downward momentum
        if current_price > self.high_extreme:
            if momentum < -self.reversal_threshold:
                return True, "down"
        
        # At low extreme, look for upward momentum
        if current_price < self.low_extreme:
            if momentum > self.reversal_threshold:
                return True, "up"
        
        return False, "none"
    
    def calculate_expected_value(self, price: float, is_yes: bool) -> float:
        """
        Calculate expected value of contrarian position.
        
        Based on research showing 79.6% NO resolution rate.
        """
        # Base rate from research
        base_no_rate = 0.796
        
        if is_yes:
            # Buying YES at low extreme
            # Potential gain: (1 - price)
            # Potential loss: price
            # Win probability: 1 - base_no_rate = 0.204 (base) + mean reversion boost
            win_prob = (1 - base_no_rate) + 0.15  # Add mean reversion boost
            win_prob = min(win_prob, 0.35)  # Cap at 35%
            
            ev = (win_prob * (1 - price)) - ((1 - win_prob) * price)
        else:
            # Buying NO at high extreme (equivalent to selling YES)
            # Potential gain: price
            # Potential loss: (1 - price)
            # Win probability: base_no_rate + mean reversion boost
            win_prob = base_no_rate + 0.1
            win_prob = min(win_prob, 0.90)  # Cap at 90%
            
            ev = (win_prob * price) - ((1 - win_prob) * (1 - price))
        
        return ev
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_price = data.price
        self.period_count += 1
        
        # Update history
        self.price_history.append(current_price)
        
        # Check cooldown
        if self.period_count - self.last_signal_period < self.cooldown_periods:
            return None
        
        # Need enough data
        if len(self.price_history) < 10:
            return None
        
        # Check if we're in an extreme zone
        is_high_extreme = current_price > self.high_extreme and current_price < self.max_price
        is_low_extreme = current_price < self.low_extreme and current_price > self.min_price
        
        # Track extreme duration
        if is_high_extreme or is_low_extreme:
            if not self.in_extreme_zone:
                self.in_extreme_zone = True
                self.extreme_zone_type = 'high' if is_high_extreme else 'low'
                self.extreme_duration = 1
            else:
                self.extreme_duration += 1
        else:
            self.in_extreme_zone = False
            self.extreme_duration = 0
            return None
        
        # Need minimum time in extreme zone for confirmation
        if self.extreme_duration < 3:
            return None
        
        signal = None
        confidence = 0.0
        reason = ""
        metadata = {}
        
        # HIGH EXTREME: Fade the YES (buy NO / sell YES)
        if is_high_extreme:
            # Calculate expected value of contrarian position
            ev = self.calculate_expected_value(current_price, is_yes=False)
            
            # Check for reversal confirmation
            is_reversal, rev_dir = self.detect_reversal_candle(current_price)
            
            if self.require_reversal_candle and not is_reversal:
                return None
            
            # Calculate confidence based on:
            # 1. How extreme the price is
            # 2. Expected value
            # 3. Reversal confirmation
            extreme_factor = (current_price - self.high_extreme) / (self.max_price - self.high_extreme)
            confidence = 0.65 + (extreme_factor * 0.15) + (ev * 0.2)
            
            if is_reversal and rev_dir == "down":
                confidence += 0.05
            
            confidence = min(confidence, 0.9)
            
            if confidence >= self.min_confidence:
                signal = "down"  # Bet against the expensive YES
                reason = f"Fade extreme YES at {current_price:.3f} (EV: {ev:.3f}, extreme duration: {self.extreme_duration})"
                metadata = {
                    'extreme_type': 'high',
                    'price': current_price,
                    'expected_value': ev,
                    'extreme_duration': self.extreme_duration,
                    'is_reversal': is_reversal,
                    'extreme_factor': extreme_factor
                }
        
        # LOW EXTREME: Fade the NO (buy YES / sell NO)
        elif is_low_extreme:
            # Calculate expected value of contrarian position
            ev = self.calculate_expected_value(current_price, is_yes=True)
            
            # Check for reversal confirmation
            is_reversal, rev_dir = self.detect_reversal_candle(current_price)
            
            if self.require_reversal_candle and not is_reversal:
                return None
            
            # Calculate confidence
            extreme_factor = (self.low_extreme - current_price) / (self.low_extreme - self.min_price)
            confidence = 0.65 + (extreme_factor * 0.15) + (ev * 0.2)
            
            if is_reversal and rev_dir == "up":
                confidence += 0.05
            
            confidence = min(confidence, 0.9)
            
            if confidence >= self.min_confidence:
                signal = "up"  # Bet on the cheap YES
                reason = f"Fade extreme NO at {current_price:.3f} (EV: {ev:.3f}, extreme duration: {self.extreme_duration})"
                metadata = {
                    'extreme_type': 'low',
                    'price': current_price,
                    'expected_value': ev,
                    'extreme_duration': self.extreme_duration,
                    'is_reversal': is_reversal,
                    'extreme_factor': extreme_factor
                }
        
        if signal:
            self.last_signal_period = self.period_count
            self.in_extreme_zone = False
            self.extreme_duration = 0
            
            return Signal(
                strategy=self.name,
                signal=signal,
                confidence=confidence,
                reason=reason,
                metadata=metadata
            )
        
        return None
