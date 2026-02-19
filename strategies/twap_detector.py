"""
TWAPDetector Strategy

Detects and exploits institutional TWAP (Time-Weighted Average Price) orders.
Large traders often execute via TWAP to minimize market impact, creating
predictable order flow patterns that can be detected and front-run.

Key insight: TWAP orders create regular, predictable trade patterns:
- Consistent trade size at regular intervals
- Price pressure in the execution direction
- Order book absorption at specific levels

By detecting these patterns early, we can position ahead of the TWAP flow
and capture the price movement as the institutional order executes.

Reference: "Algorithmic Trading: Winning Strategies and Their Rationale" - Chan
"Market Microstructure in Practice" - Lehalle & Laruelle
"The Lifecycle of a TWAP Order" - various trading blogs

Validation:
- No lookahead: Uses only current and historical order flow
- No overfit: Based on well-documented execution patterns
- Economic rationale: Large orders move prices predictably
"""

from typing import Optional
from collections import deque
import statistics
import time

from core.base_strategy import BaseStrategy, Signal, MarketData


class TWAPDetectorStrategy(BaseStrategy):
    """
    Detect institutional TWAP orders and trade alongside them.
    
    Strategy logic:
    1. Monitor for regular trade patterns (consistent timing, size)
    2. Detect order book absorption at specific price levels
    3. Identify sustained pressure in one direction
    4. Once TWAP is detected, trade in the same direction
    5. Exit before TWAP completion (avoid the reversal)
    
    TWAP patterns:
    - Regular interval trades (e.g., every 30 seconds)
    - Similar trade sizes
    - Aggressive execution (market orders or crossing spread)
    - Sustained direction over multiple periods
    """
    
    name = "TWAPDetector"
    description = "Detect and exploit institutional TWAP orders"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        
        # Trade pattern detection
        self.trade_history = deque(maxlen=50)
        self.volume_history = deque(maxlen=30)
        self.time_history = deque(maxlen=30)
        
        # TWAP detection parameters
        self.min_trades_for_pattern = self.config.get('min_trades_for_pattern', 5)
        self.regularity_threshold = self.config.get('regularity_threshold', 0.7)  # 70% regular timing
        self.size_consistency_threshold = self.config.get('size_consistency_threshold', 0.6)  # 60% similar sizes
        
        # Direction detection
        self.pressure_history = deque(maxlen=20)
        self.price_history = deque(maxlen=30)
        
        # TWAP state
        self.twap_detected = False
        self.twap_direction = None
        self.twap_start_time = 0
        self.twap_estimated_end = 0
        self.twap_strength = 0.0
        
        # Entry/exit timing
        self.max_twap_duration = self.config.get('max_twap_duration', 300)  # 5 minutes max
        self.min_twap_duration = self.config.get('min_twap_duration', 60)  # 1 minute min
        self.exit_before_completion = self.config.get('exit_before_completion', 0.8)  # Exit at 80%
        
        # Cooldown
        self.last_signal_time = 0
        self.cooldown_seconds = self.config.get('cooldown_seconds', 120)
        self.last_exit_time = 0
        
        # Minimum volume for detection
        self.min_volume = self.config.get('min_volume', 2000)
        self.min_trade_size = self.config.get('min_trade_size', 100)
    
    def detect_trade_regularity(self) -> tuple:
        """
        Detect if recent trades show regular timing patterns.
        
        Returns: (is_regular, avg_interval, cv_interval)
        cv = coefficient of variation (std/mean, lower = more regular)
        """
        if len(self.time_history) < self.min_trades_for_pattern:
            return False, 0, 1.0
        
        times = list(self.time_history)
        if len(times) < 2:
            return False, 0, 1.0
        
        # Calculate intervals between trades
        intervals = [times[i] - times[i-1] for i in range(1, len(times))]
        
        if len(intervals) < 3:
            return False, 0, 1.0
        
        avg_interval = statistics.mean(intervals)
        
        if avg_interval == 0:
            return False, 0, 1.0
        
        try:
            std_interval = statistics.stdev(intervals)
            cv_interval = std_interval / avg_interval
        except:
            return False, avg_interval, 1.0
        
        # Low CV indicates regular timing
        is_regular = cv_interval < (1 - self.regularity_threshold)
        
        return is_regular, avg_interval, cv_interval
    
    def detect_size_consistency(self) -> tuple:
        """
        Detect if recent trades show consistent size patterns.
        
        Returns: (is_consistent, avg_size, cv_size)
        """
        if len(self.volume_history) < self.min_trades_for_pattern:
            return False, 0, 1.0
        
        volumes = list(self.volume_history)
        if len(volumes) < 3:
            return False, 0, 1.0
        
        avg_size = statistics.mean(volumes)
        
        if avg_size == 0:
            return False, 0, 1.0
        
        try:
            std_size = statistics.stdev(volumes)
            cv_size = std_size / avg_size
        except:
            return False, avg_size, 1.0
        
        # Low CV indicates consistent sizes
        is_consistent = cv_size < (1 - self.size_consistency_threshold)
        
        return is_consistent, avg_size, cv_size
    
    def calculate_buy_pressure(self, data: MarketData) -> float:
        """
        Calculate buy/sell pressure from order book and price action.
        Returns: +1.0 = strong buy pressure, -1.0 = strong sell pressure
        """
        if not data.order_book:
            return 0.0
        
        bids = data.order_book.get('bids', [])
        asks = data.order_book.get('asks', [])
        
        if not bids or not asks:
            return 0.0
        
        # Calculate depth imbalance
        bid_vol = sum(float(b.get('size', 0)) for b in bids[:5])
        ask_vol = sum(float(a.get('size', 0)) for a in asks[:5])
        total_vol = bid_vol + ask_vol
        
        if total_vol == 0:
            return 0.0
        
        # Depth imbalance: positive = more bids = buying pressure
        depth_imbalance = (bid_vol - ask_vol) / total_vol
        
        # Price momentum
        if len(self.price_history) >= 5:
            prices = list(self.price_history)
            recent_change = (prices[-1] - prices[-5]) / prices[-5] if prices[-5] > 0 else 0
            momentum = max(-1, min(1, recent_change * 100))  # Scale to [-1, 1]
        else:
            momentum = 0.0
        
        # Combine signals
        pressure = depth_imbalance * 0.6 + momentum * 0.4
        
        return max(-1, min(1, pressure))
    
    def detect_twap_pattern(self, data: MarketData) -> tuple:
        """
        Detect if a TWAP order is currently executing.
        
        Returns: (is_twap, direction, strength, confidence)
        """
        current_time = data.timestamp
        
        # Check regularity
        is_regular, avg_interval, cv_interval = self.detect_trade_regularity()
        
        # Check size consistency
        is_consistent, avg_size, cv_size = self.detect_size_consistency()
        
        # Check pressure
        pressure = self.calculate_buy_pressure(data)
        self.pressure_history.append(pressure)
        
        # Need both regularity and consistency
        if not (is_regular and is_consistent):
            return False, "none", 0.0, 0.0
        
        # Need sustained pressure
        if len(self.pressure_history) < 5:
            return False, "none", 0.0, 0.0
        
        recent_pressure = list(self.pressure_history)[-5:]
        avg_pressure = statistics.mean(recent_pressure)
        
        # Pressure must be consistently in one direction
        if abs(avg_pressure) < 0.3:
            return False, "none", 0.0, 0.0
        
        # Determine direction from pressure
        direction = "up" if avg_pressure > 0 else "down"
        
        # Calculate strength
        regularity_score = 1 - cv_interval
        consistency_score = 1 - cv_size
        pressure_score = abs(avg_pressure)
        
        strength = (regularity_score + consistency_score + pressure_score) / 3
        
        # Calculate confidence
        confidence = 0.55 + strength * 0.25
        
        return True, direction, strength, confidence
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_time = data.timestamp
        
        # Update history
        self.price_history.append(data.price)
        self.time_history.append(current_time)
        
        # Estimate volume from order book changes
        if data.order_book:
            bids = data.order_book.get('bids', [])
            asks = data.order_book.get('asks', [])
            if bids and asks:
                est_volume = sum(float(b.get('size', 0)) for b in bids[:3]) + \
                            sum(float(a.get('size', 0)) for a in asks[:3])
                self.volume_history.append(est_volume)
        
        # Detect TWAP pattern
        is_twap, direction, strength, confidence = self.detect_twap_pattern(data)
        
        # Update TWAP state
        if is_twap and not self.twap_detected:
            # New TWAP detected
            self.twap_detected = True
            self.twap_direction = direction
            self.twap_start_time = current_time
            self.twap_estimated_end = current_time + self.max_twap_duration
            self.twap_strength = strength
        
        elif not is_twap and self.twap_detected:
            # TWAP may have ended
            elapsed = current_time - self.twap_start_time
            if elapsed > self.min_twap_duration:
                # TWAP completed
                self.twap_detected = False
                self.twap_direction = None
                self.last_exit_time = current_time
        
        # Check if we should exit existing position
        if self.twap_detected:
            elapsed = current_time - self.twap_start_time
            progress = elapsed / self.max_twap_duration
            
            # Exit before completion to avoid reversal
            if progress > self.exit_before_completion:
                self.twap_detected = False
                self.last_exit_time = current_time
                return None  # Signal exit (handled by position manager)
        
        # Cooldown check
        if current_time - self.last_signal_time < self.cooldown_seconds:
            return None
        
        # Generate entry signal when TWAP is detected
        if is_twap and self.twap_detected:
            # Only enter if we're early in the TWAP
            elapsed = current_time - self.twap_start_time
            progress = elapsed / self.max_twap_duration
            
            if progress < self.exit_before_completion:
                # Calculate final confidence
                time_boost = (1 - progress) * 0.1  # Higher confidence early
                final_confidence = min(confidence + time_boost, 0.85)
                
                if final_confidence >= self.min_confidence:
                    self.last_signal_time = current_time
                    
                    return Signal(
                        strategy=self.name,
                        signal=direction,
                        confidence=final_confidence,
                        reason=f"TWAP detected: {direction} (strength={strength:.2f}, progress={progress:.0%})",
                        metadata={
                            'direction': direction,
                            'strength': strength,
                            'progress': progress,
                            'elapsed': elapsed,
                            'regularity_cv': 1 - strength,
                            'pressure': statistics.mean(list(self.pressure_history)[-5:]) if self.pressure_history else 0
                        }
                    )
        
        return None
