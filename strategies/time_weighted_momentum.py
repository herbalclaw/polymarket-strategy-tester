"""
Time-Weighted Momentum (TWM) Strategy

Captures intraday momentum patterns specific to prediction markets.
Uses time-of-window effects and volume-weighted price acceleration.

Key insight: BTC 5-min markets show predictable patterns based on:
- Time elapsed in current window (early vs late)
- Volume acceleration (increasing vs decreasing)
- Price momentum relative to time remaining

Reference: "Intraday Momentum in Prediction Markets" - microstructure research
"""

from typing import Optional, Dict
from collections import deque
from statistics import mean
import time

from core.base_strategy import BaseStrategy, Signal, MarketData


class TimeWeightedMomentumStrategy(BaseStrategy):
    """
    Time-weighted momentum for short-term prediction markets.
    
    Adjusts momentum strength based on time remaining in window.
    Earlier in window = more noise, less signal
    Later in window = less noise, more signal
    """
    
    name = "TimeWeightedMomentum"
    description = "Time-weighted momentum with volume acceleration"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        
        # Window parameters (5-minute BTC markets)
        self.window_seconds = self.config.get('window_seconds', 300)  # 5 min
        
        # Momentum calculation
        self.price_history: deque = deque(maxlen=30)
        self.volume_history: deque = deque(maxlen=30)
        self.timestamp_history: deque = deque(maxlen=30)
        
        # Thresholds
        self.momentum_threshold = self.config.get('momentum_threshold', 0.005)  # 0.5%
        self.volume_accel_threshold = self.config.get('volume_accel_threshold', 0.1)  # 10%
        
        # Time weighting (later = higher weight)
        self.time_weight_exponent = self.config.get('time_weight_exponent', 2.0)
        
        # Minimum data points
        self.min_points = 10
        
    def calculate_time_weight(self, timestamp: float) -> float:
        """
        Calculate time weight based on position in window.
        
        Returns weight from 0 (start of window) to 1 (end of window).
        """
        window_start = (int(timestamp) // self.window_seconds) * self.window_seconds
        elapsed = timestamp - window_start
        progress = elapsed / self.window_seconds
        
        # Apply exponential weighting (later = much higher weight)
        return progress ** self.time_weight_exponent
    
    def calculate_volume_acceleration(self) -> float:
        """
        Calculate volume acceleration (change in volume rate).
        
        Returns acceleration ratio (>1 = accelerating, <1 = decelerating).
        """
        if len(self.volume_history) < 6:
            return 1.0
        
        volumes = list(self.volume_history)
        
        # Compare recent volume to earlier volume
        recent_vol = mean(volumes[-3:])
        earlier_vol = mean(volumes[:3])
        
        if earlier_vol == 0:
            return 1.0
        
        return recent_vol / earlier_vol
    
    def calculate_weighted_momentum(self) -> Optional[float]:
        """
        Calculate time-weighted price momentum.
        
        Weights recent price changes more heavily based on time in window.
        """
        if len(self.price_history) < self.min_points:
            return None
        
        prices = list(self.price_history)
        timestamps = list(self.timestamp_history)
        
        # Calculate weighted returns
        weighted_returns = []
        total_weight = 0
        
        for i in range(1, len(prices)):
            price_return = (prices[i] - prices[i-1]) / prices[i-1] if prices[i-1] > 0 else 0
            time_weight = self.calculate_time_weight(timestamps[i])
            
            weighted_returns.append(price_return * time_weight)
            total_weight += time_weight
        
        if total_weight == 0:
            return 0
        
        # Sum of weighted returns / sum of weights
        momentum = sum(weighted_returns) / total_weight
        return momentum
    
    def generate_signal(self, market_data: MarketData) -> Optional[Signal]:
        """Generate signal based on time-weighted momentum."""
        current_time = market_data.timestamp
        
        # Update histories
        self.price_history.append(market_data.price)
        self.volume_history.append(market_data.volume_24h)
        self.timestamp_history.append(current_time)
        
        # Need enough data
        if len(self.price_history) < self.min_points:
            return None
        
        # Calculate metrics
        momentum = self.calculate_weighted_momentum()
        if momentum is None:
            return None
        
        vol_accel = self.calculate_volume_acceleration()
        time_weight = self.calculate_time_weight(current_time)
        
        # Time remaining in window (0 to 1)
        time_remaining = 1 - time_weight
        
        # Generate signal when momentum exceeds threshold
        # AND we have volume confirmation
        if abs(momentum) > self.momentum_threshold and vol_accel > (1 + self.volume_accel_threshold):
            # Strong momentum with volume acceleration
            
            if momentum > 0:
                # Bullish momentum
                confidence = min(0.6 + abs(momentum) * 20 + time_weight * 0.2, 0.9)
                return Signal(
                    strategy=self.name,
                    signal="up",
                    confidence=confidence,
                    reason=f"TWM: +{momentum:.2%} momentum, {vol_accel:.1f}x vol accel, {time_remaining:.0%} remaining",
                    metadata={
                        'momentum': momentum,
                        'volume_acceleration': vol_accel,
                        'time_weight': time_weight,
                        'time_remaining': time_remaining
                    }
                )
            else:
                # Bearish momentum
                confidence = min(0.6 + abs(momentum) * 20 + time_weight * 0.2, 0.9)
                return Signal(
                    strategy=self.name,
                    signal="down",
                    confidence=confidence,
                    reason=f"TWM: {momentum:.2%} momentum, {vol_accel:.1f}x vol accel, {time_remaining:.0%} remaining",
                    metadata={
                        'momentum': momentum,
                        'volume_acceleration': vol_accel,
                        'time_weight': time_weight,
                        'time_remaining': time_remaining
                    }
                )
        
        return None
