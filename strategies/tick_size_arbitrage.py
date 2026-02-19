"""
Tick-Size Arbitrage Strategy

Exploits Polymarket's tick size regime changes near price extremes.
When price approaches 0.01 or 0.99, tick sizes change, creating
micro-inefficiencies that can be captured.

Also exploits the "rounding game" - when prices are near tick boundaries,
small order flow can push prices across ticks, creating temporary mispricing.

Reference: Research on CLOB microstructure and tick-size effects
"""

from typing import Optional
from collections import deque
import statistics

from core.base_strategy import BaseStrategy, Signal, MarketData


class TickSizeArbitrageStrategy(BaseStrategy):
    """
    Tick-size arbitrage for Polymarket CLOB.
    
    Key insights:
    1. Tick sizes are larger near extremes (0.01 increments)
    2. Small orders can move prices across tick boundaries
    3. This creates temporary micro-inefficiencies
    
    Strategy detects when price is near tick boundary and
    anticipates the direction of the next tick move based on
    order flow imbalance.
    """
    
    name = "TickSizeArbitrage"
    description = "Exploits tick-size regime changes and micro-inefficiencies"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        config = config or {}
        
        # Tick size thresholds
        self.tick_size_normal = self.config.get('tick_size_normal', 0.01)  # 1 cent
        self.tick_size_extreme = self.config.get('tick_size_extreme', 0.001)  # 0.1 cent near extremes
        
        # Extreme zone boundaries
        self.extreme_low = self.config.get('extreme_low', 0.05)
        self.extreme_high = self.config.get('extreme_high', 0.95)
        
        # Proximity to tick boundary required
        self.tick_proximity = self.config.get('tick_proximity', 0.003)  # 0.3 cents
        
        # Order flow lookback
        self.flow_lookback = self.config.get('flow_lookback', 5)
        self.flow_history = deque(maxlen=self.flow_lookback)
        
        # Price history for tick detection
        self.price_history = deque(maxlen=20)
    
    def get_tick_size(self, price: float) -> float:
        """Get effective tick size at given price."""
        if price < self.extreme_low or price > self.extreme_high:
            return self.tick_size_extreme
        return self.tick_size_normal
    
    def find_nearest_tick(self, price: float, tick_size: float) -> float:
        """Find nearest tick level."""
        return round(price / tick_size) * tick_size
    
    def calculate_tick_proximity(self, price: float, tick_size: float) -> float:
        """Calculate distance to nearest tick boundary."""
        nearest = self.find_nearest_tick(price, tick_size)
        next_tick = nearest + tick_size if price >= nearest else nearest - tick_size
        
        # Distance to nearest tick as fraction of tick size
        dist_to_nearest = abs(price - nearest)
        dist_to_next = abs(price - next_tick)
        
        return min(dist_to_nearest, dist_to_next)
    
    def calculate_order_flow_imbalance(self, data: MarketData) -> float:
        """Calculate order flow imbalance from recent trades/orders."""
        if not data.order_book:
            return 0.0
        
        bids = data.order_book.get('bids', [])
        asks = data.order_book.get('asks', [])
        
        if not bids or not asks:
            return 0.0
        
        # Calculate top-of-book imbalance
        bid_vol = sum(float(b.get('size', 0)) for b in bids[:3])
        ask_vol = sum(float(a.get('size', 0)) for a in asks[:3])
        
        if bid_vol + ask_vol == 0:
            return 0.0
        
        # Returns positive for bid-heavy (buy pressure), negative for ask-heavy
        return (bid_vol - ask_vol) / (bid_vol + ask_vol)
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        price = data.price
        
        # Store history
        self.price_history.append(price)
        
        # Calculate order flow
        flow = self.calculate_order_flow_imbalance(data)
        self.flow_history.append(flow)
        
        # Get effective tick size
        tick_size = self.get_tick_size(price)
        
        # Find nearest tick
        nearest_tick = self.find_nearest_tick(price, tick_size)
        
        # Calculate proximity to tick boundary
        proximity = self.calculate_tick_proximity(price, tick_size)
        
        # Only trade near tick boundaries
        if proximity > self.tick_proximity:
            return None
        
        # Need order flow history
        if len(self.flow_history) < 3:
            return None
        
        # Average recent flow
        avg_flow = statistics.mean(self.flow_history)
        
        signal = None
        confidence = 0.0
        reason = ""
        
        # Determine which tick we're closer to
        dist_to_lower = abs(price - (nearest_tick - tick_size))
        dist_to_upper = abs(price - (nearest_tick + tick_size))
        closer_to_upper = dist_to_upper < dist_to_lower
        
        # Signal logic: flow direction + tick proximity
        if avg_flow > 0.3:  # Strong bid pressure
            if closer_to_upper:
                # Pressure pushing toward upper tick
                confidence = min(0.6 + avg_flow * 0.3, 0.85)
                signal = "up"
                reason = f"Tick arb: bid pressure {avg_flow:.2f}, near upper tick {nearest_tick + tick_size:.3f}"
            else:
                # Already at lower tick, pressure pushing away
                confidence = min(0.55 + avg_flow * 0.2, 0.75)
                signal = "up"
                reason = f"Tick arb: bid pressure {avg_flow:.2f}, pushing from lower tick"
        
        elif avg_flow < -0.3:  # Strong ask pressure
            if not closer_to_upper:
                # Pressure pushing toward lower tick
                confidence = min(0.6 + abs(avg_flow) * 0.3, 0.85)
                signal = "down"
                reason = f"Tick arb: ask pressure {abs(avg_flow):.2f}, near lower tick {nearest_tick - tick_size:.3f}"
            else:
                # Already at upper tick, pressure pushing away
                confidence = min(0.55 + abs(avg_flow) * 0.2, 0.75)
                signal = "down"
                reason = f"Tick arb: ask pressure {abs(avg_flow):.2f}, pushing from upper tick"
        
        if signal and confidence >= self.min_confidence:
            return Signal(
                strategy=self.name,
                signal=signal,
                confidence=confidence,
                reason=reason,
                metadata={
                    'price': price,
                    'tick_size': tick_size,
                    'nearest_tick': nearest_tick,
                    'proximity': proximity,
                    'flow_imbalance': avg_flow,
                    'zone': 'extreme' if tick_size == self.tick_size_extreme else 'normal'
                }
            )
        
        return None
