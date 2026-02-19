"""
OrderBookSlope Strategy

Exploits the slope/steepness of the order book to predict price movements.
A steep ask slope (many orders at increasing prices) suggests resistance
and potential reversal. A flat ask slope suggests easy upward movement.

Key insight: Order book slope reflects market depth and resistance levels.
Steep slopes act as barriers; flat slopes allow easy price movement.

Reference: "The Price Impact of Order Book Events" - Cont et al. (2014)
"""

from typing import Optional, List, Dict
from collections import deque
from statistics import mean
import math

from core.base_strategy import BaseStrategy, Signal, MarketData


class OrderBookSlopeStrategy(BaseStrategy):
    """
    Trade based on order book slope and depth patterns.
    
    Strategy logic:
    1. Calculate slope of bid and ask sides (price vs cumulative volume)
    2. Steep slope = resistance/support; flat slope = easy movement
    3. Compare bid slope vs ask slope for directional edge
    4. Trade when imbalance between slopes creates opportunity
    
    Slope calculation: linear regression of price vs log(cumulative volume)
    """
    
    name = "OrderBookSlope"
    description = "Order book slope and depth analysis"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        
        # Order book depth to analyze
        self.depth_levels = self.config.get('depth_levels', 10)
        
        # Slope calculation
        self.slope_history = deque(maxlen=30)
        self.imbalance_history = deque(maxlen=20)
        
        # Thresholds
        self.slope_imbalance_threshold = self.config.get('slope_imbalance_threshold', 0.3)
        self.min_slope_diff = self.config.get('min_slope_diff', 0.1)
        
        # Volume requirements
        self.min_total_volume = self.config.get('min_total_volume', 500)
        
        # Price tracking
        self.price_history = deque(maxlen=20)
        
        # Cooldown
        self.last_signal_time = 0
        self.cooldown_seconds = self.config.get('cooldown_seconds', 75)
        
        # Signal tracking
        self.last_signal_side = None
        self.consecutive_count = 0
    
    def calculate_slope(self, levels: List[Dict]) -> float:
        """
        Calculate slope of order book side using linear regression.
        Returns slope (steepness) - higher = more resistance/support
        
        Uses log(volume) to handle varying order sizes
        """
        if not levels or len(levels) < 3:
            return 0.0
        
        # Extract prices and cumulative volumes
        prices = []
        cum_volumes = []
        cum_vol = 0
        
        for level in levels[:self.depth_levels]:
            price = float(level.get('price', 0))
            size = float(level.get('size', 0))
            
            if price > 0 and size > 0:
                cum_vol += size
                prices.append(price)
                cum_volumes.append(math.log(cum_vol + 1))  # Log scale for volume
        
        if len(prices) < 3:
            return 0.0
        
        # Linear regression: slope = Cov(X,Y) / Var(X)
        n = len(prices)
        x_mean = mean(cum_volumes)
        y_mean = mean(prices)
        
        numerator = sum((cum_volumes[i] - x_mean) * (prices[i] - y_mean) for i in range(n))
        denominator = sum((cum_volumes[i] - x_mean) ** 2 for i in range(n))
        
        if denominator == 0:
            return 0.0
        
        slope = numerator / denominator
        return slope
    
    def calculate_depth_imbalance(self, data: MarketData) -> tuple:
        """
        Calculate depth imbalance between bid and ask sides.
        Returns (imbalance_score, bid_slope, ask_slope)
        
        Positive imbalance = bid side steeper (more support)
        Negative imbalance = ask side steeper (more resistance)
        """
        if not data.order_book:
            return 0.0, 0.0, 0.0
        
        bids = data.order_book.get('bids', [])
        asks = data.order_book.get('asks', [])
        
        if not bids or not asks:
            return 0.0, 0.0, 0.0
        
        # Calculate total volume on each side
        bid_vol = sum(float(b.get('size', 0)) for b in bids[:self.depth_levels])
        ask_vol = sum(float(a.get('size', 0)) for a in asks[:self.depth_levels])
        
        if bid_vol + ask_vol < self.min_total_volume:
            return 0.0, 0.0, 0.0
        
        # Calculate slopes
        bid_slope = self.calculate_slope(bids)
        ask_slope = self.calculate_slope(asks)
        
        # Normalize slopes (handle negative bid slope - bids decrease as we go down)
        bid_slope = abs(bid_slope)
        ask_slope = abs(ask_slope)
        
        # Calculate imbalance
        total_slope = bid_slope + ask_slope
        if total_slope == 0:
            return 0.0, bid_slope, ask_slope
        
        # Imbalance: positive = more bid depth, negative = more ask depth
        imbalance = (bid_slope - ask_slope) / total_slope
        
        return imbalance, bid_slope, ask_slope
    
    def calculate_price_velocity(self) -> float:
        """Calculate recent price velocity."""
        if len(self.price_history) < 5:
            return 0.0
        
        prices = list(self.price_history)
        if prices[0] == 0:
            return 0.0
        
        return (prices[-1] - prices[0]) / prices[0]
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_time = data.timestamp
        current_price = data.price
        
        # Update price history
        self.price_history.append(current_price)
        
        # Cooldown check
        if current_time - self.last_signal_time < self.cooldown_seconds:
            return None
        
        # Calculate slope imbalance
        imbalance, bid_slope, ask_slope = self.calculate_depth_imbalance(data)
        self.imbalance_history.append(imbalance)
        
        # Need enough history
        if len(self.imbalance_history) < 5:
            return None
        
        # Calculate average imbalance
        avg_imbalance = mean(list(self.imbalance_history)[-5:])
        
        # Store slope data
        self.slope_history.append({
            'bid_slope': bid_slope,
            'ask_slope': ask_slope,
            'imbalance': imbalance
        })
        
        signal = None
        confidence = 0.0
        reason = ""
        
        # Strong bid slope > ask slope = more support than resistance = bullish
        if avg_imbalance > self.slope_imbalance_threshold:
            # Check price velocity - don't chase if already moved
            velocity = self.calculate_price_velocity()
            
            if velocity < 0.005:  # Not already moved up too much
                base_confidence = 0.60
                imbalance_boost = min((avg_imbalance - self.slope_imbalance_threshold) * 0.3, 0.15)
                velocity_penalty = max(0, velocity * 10)  # Penalty if already moving up
                
                confidence = base_confidence + imbalance_boost - velocity_penalty
                confidence = min(confidence, 0.82)
                
                if confidence >= self.min_confidence:
                    signal = "up"
                    reason = f"Bid slope ({bid_slope:.4f}) > Ask slope ({ask_slope:.4f}), imbalance={avg_imbalance:.2f}"
        
        # Strong ask slope > bid slope = more resistance than support = bearish
        elif avg_imbalance < -self.slope_imbalance_threshold:
            velocity = self.calculate_price_velocity()
            
            if velocity > -0.005:  # Not already moved down too much
                base_confidence = 0.60
                imbalance_boost = min((abs(avg_imbalance) - self.slope_imbalance_threshold) * 0.3, 0.15)
                velocity_penalty = max(0, abs(velocity) * 10)  # Penalty if already moving down
                
                confidence = base_confidence + imbalance_boost - velocity_penalty
                confidence = min(confidence, 0.82)
                
                if confidence >= self.min_confidence:
                    signal = "down"
                    reason = f"Ask slope ({ask_slope:.4f}) > Bid slope ({bid_slope:.4f}), imbalance={avg_imbalance:.2f}"
        
        # Flat slope on both sides = potential breakout setup
        elif bid_slope < 0.001 and ask_slope < 0.001 and len(self.price_history) >= 10:
            # Both sides flat = low resistance in either direction
            # Trade in direction of recent momentum
            velocity = self.calculate_price_velocity()
            
            if abs(velocity) > 0.002:
                base_confidence = 0.58
                velocity_boost = min(abs(velocity) * 50, 0.12)
                
                confidence = base_confidence + velocity_boost
                confidence = min(confidence, 0.75)
                
                if confidence >= self.min_confidence:
                    if velocity > 0:
                        signal = "up"
                        reason = f"Flat order book slopes, positive momentum ({velocity:.3f})"
                    else:
                        signal = "down"
                        reason = f"Flat order book slopes, negative momentum ({velocity:.3f})"
        
        if signal and confidence >= self.min_confidence:
            self.last_signal_time = current_time
            
            # Track consecutive signals
            if signal == self.last_signal_side:
                self.consecutive_count += 1
            else:
                self.consecutive_count = 1
                self.last_signal_side = signal
            
            return Signal(
                strategy=self.name,
                signal=signal,
                confidence=confidence,
                reason=reason,
                metadata={
                    'bid_slope': bid_slope,
                    'ask_slope': ask_slope,
                    'imbalance': avg_imbalance,
                    'velocity': self.calculate_price_velocity(),
                    'consecutive': self.consecutive_count
                }
            )
        
        return None
