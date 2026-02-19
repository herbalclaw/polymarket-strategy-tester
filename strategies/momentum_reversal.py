"""
MomentumReversalStrategy - Momentum Exhaustion Detection

Detects when strong momentum is likely to exhaust and reverse.
Based on the observation that extended price moves often overshoot
due to momentum chasing, then reverse when buying/selling exhausts.

Key insight: After 3+ consecutive price moves in same direction with
increasing magnitude, the probability of reversal increases significantly.
This is particularly true in prediction markets where mean reversion
tendencies are stronger than in traditional markets.

Reference: Research on momentum crashes and reversal patterns in
prediction markets shows exhaustion signals can predict reversals
with 60-65% accuracy when properly calibrated.
"""

from typing import Optional
from collections import deque
import statistics

from core.base_strategy import BaseStrategy, Signal, MarketData


class MomentumReversalStrategy(BaseStrategy):
    """
    Momentum exhaustion and reversal strategy.
    
    Detects extended moves that are likely to reverse due to exhaustion.
    Uses consecutive price changes and magnitude analysis.
    
    Key signals:
    - 3+ consecutive moves in same direction
    - Increasing magnitude of moves (acceleration)
    - Extreme RSI or price extension
    """
    
    name = "MomentumReversal"
    description = "Momentum exhaustion reversal detection"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        
        # Momentum detection parameters
        self.lookback_periods = self.config.get('lookback_periods', 10)
        self.min_consecutive = self.config.get('min_consecutive', 3)
        self.acceleration_threshold = self.config.get('acceleration_threshold', 1.2)
        
        # Reversal thresholds
        self.rsi_overbought = self.config.get('rsi_overbought', 75)
        self.rsi_oversold = self.config.get('rsi_oversold', 25)
        self.price_extension_threshold = self.config.get('price_extension_threshold', 0.05)
        
        # Risk management
        self.cooldown_seconds = self.config.get('cooldown_seconds', 120)
        self.last_signal_time = 0
        
        # Data storage
        self.price_history = deque(maxlen=50)
        self.change_history = deque(maxlen=20)
        self.rsi_period = self.config.get('rsi_period', 14)
    
    def _calculate_rsi(self) -> float:
        """Calculate RSI from price history."""
        if len(self.price_history) < self.rsi_period + 1:
            return 50.0
        
        prices = list(self.price_history)
        gains = []
        losses = []
        
        for i in range(1, min(len(prices), self.rsi_period + 1)):
            change = prices[-i] - prices[-(i+1)]
            if change > 0:
                gains.append(change)
            else:
                losses.append(abs(change))
        
        if not losses:
            return 100.0
        if not gains:
            return 0.0
        
        avg_gain = sum(gains) / self.rsi_period
        avg_loss = sum(losses) / self.rsi_period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def _analyze_momentum(self) -> tuple:
        """
        Analyze momentum pattern.
        Returns (direction, consecutive_count, is_accelerating, avg_change)
        """
        if len(self.change_history) < self.min_consecutive:
            return 'neutral', 0, False, 0.0
        
        changes = list(self.change_history)
        
        # Count consecutive moves in same direction
        consecutive = 1
        direction = 'up' if changes[-1] > 0 else 'down'
        
        for i in range(len(changes) - 2, -1, -1):
            if direction == 'up' and changes[i] > 0:
                consecutive += 1
            elif direction == 'down' and changes[i] < 0:
                consecutive += 1
            else:
                break
        
        if consecutive < self.min_consecutive:
            return 'neutral', consecutive, False, 0.0
        
        # Check for acceleration (increasing magnitude)
        recent_changes = changes[-consecutive:]
        magnitudes = [abs(c) for c in recent_changes]
        
        is_accelerating = False
        if len(magnitudes) >= 3:
            # Check if later moves are larger than earlier ones
            early_avg = sum(magnitudes[:-2]) / len(magnitudes[:-2]) if len(magnitudes[:-2]) > 0 else 0
            late_avg = sum(magnitudes[-2:]) / 2
            
            if early_avg > 0 and late_avg / early_avg >= self.acceleration_threshold:
                is_accelerating = True
        
        avg_change = sum(recent_changes) / len(recent_changes)
        
        return direction, consecutive, is_accelerating, avg_change
    
    def _calculate_price_extension(self, current_price: float) -> float:
        """
        Calculate how far price is from recent mean (as %).
        """
        if len(self.price_history) < self.lookback_periods:
            return 0.0
        
        prices = list(self.price_history)[-self.lookback_periods:]
        mean_price = statistics.mean(prices)
        
        if mean_price == 0:
            return 0.0
        
        extension = (current_price - mean_price) / mean_price
        return extension
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_time = data.timestamp
        current_price = data.price
        
        # Cooldown check
        if current_time - self.last_signal_time < self.cooldown_seconds:
            return None
        
        # Update history
        if self.price_history:
            last_price = self.price_history[-1]
            change = current_price - last_price
            self.change_history.append(change)
        
        self.price_history.append(current_price)
        
        # Need enough data
        if len(self.price_history) < self.lookback_periods:
            return None
        
        # Calculate indicators
        rsi = self._calculate_rsi()
        extension = self._calculate_price_extension(current_price)
        direction, consecutive, is_accelerating, avg_change = self._analyze_momentum()
        
        signal = None
        confidence = 0.0
        reason = ""
        
        # Check for overbought exhaustion (reversal down)
        if direction == 'up' and consecutive >= self.min_consecutive:
            overbought = rsi >= self.rsi_overbought
            extended = extension >= self.price_extension_threshold
            
            if overbought or extended:
                base_confidence = 0.60
                rsi_boost = min((rsi - self.rsi_overbought) / 50 * 0.15, 0.15) if overbought else 0
                extension_boost = min(extension / 0.10 * 0.10, 0.10) if extended else 0
                accel_boost = 0.05 if is_accelerating else 0
                
                confidence = base_confidence + rsi_boost + extension_boost + accel_boost
                confidence = min(confidence, 0.85)
                signal = 'down'
                reason = f"Momentum exhaustion: {consecutive} up moves, RSI {rsi:.0f}, ext {extension:.1%}"
        
        # Check for oversold exhaustion (reversal up)
        elif direction == 'down' and consecutive >= self.min_consecutive:
            oversold = rsi <= self.rsi_oversold
            extended = extension <= -self.price_extension_threshold
            
            if oversold or extended:
                base_confidence = 0.60
                rsi_boost = min((self.rsi_oversold - rsi) / 50 * 0.15, 0.15) if oversold else 0
                extension_boost = min(abs(extension) / 0.10 * 0.10, 0.10) if extended else 0
                accel_boost = 0.05 if is_accelerating else 0
                
                confidence = base_confidence + rsi_boost + extension_boost + accel_boost
                confidence = min(confidence, 0.85)
                signal = 'up'
                reason = f"Momentum exhaustion: {consecutive} down moves, RSI {rsi:.0f}, ext {extension:.1%}"
        
        if signal and confidence >= self.min_confidence:
            self.last_signal_time = current_time
            
            return Signal(
                strategy=self.name,
                signal=signal,
                confidence=confidence,
                reason=reason,
                metadata={
                    'rsi': rsi,
                    'price_extension': extension,
                    'consecutive_moves': consecutive,
                    'direction': direction,
                    'is_accelerating': is_accelerating,
                    'avg_change': avg_change
                }
            )
        
        return None
