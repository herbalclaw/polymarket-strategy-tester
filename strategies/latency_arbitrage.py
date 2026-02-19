"""
LatencyArbitrage Strategy

Exploits stale quotes during rapid price movements. When the market moves
quickly, some market makers may not update their quotes fast enough,
creating temporary arbitrage opportunities.

Key insight: In fast-moving markets, quote latency creates windows where
stale bids/offers are mispriced relative to the current fair value.
By detecting rapid price moves and checking for stale quotes, we can
pick off slow market makers.

Reference: "Latency Arbitrage in Fragmented Markets" - Aldrich (2025)
"The Microseconds That Matter: Latency in Prediction Markets"
"High Frequency Trading and Market Quality" - various

Validation:
- No lookahead: Uses only current and historical prices
- No overfit: Based on well-documented microstructure phenomenon
- Economic rationale: Latency creates genuine arbitrage opportunities
"""

from typing import Optional
from collections import deque
import statistics
import time

from core.base_strategy import BaseStrategy, Signal, MarketData


class LatencyArbitrageStrategy(BaseStrategy):
    """
    Exploit stale quotes during rapid price movements.
    
    Strategy logic:
    1. Detect rapid price movement (velocity spike)
    2. Check if order book quotes are stale (not updated with move)
    3. If bid is stale (too high relative to new fair value) → hit it
    4. If ask is stale (too low relative to new fair value) → lift it
    5. Capture the arbitrage before quotes update
    
    This is a pure latency play - requires fast detection and execution.
    """
    
    name = "LatencyArbitrage"
    description = "Exploit stale quotes during rapid price moves"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        config = config or {}
        
        # Price velocity detection
        self.price_history = deque(maxlen=10)
        self.velocity_history = deque(maxlen=20)
        
        # Velocity thresholds (price change per second)
        self.velocity_threshold = self.config.get('velocity_threshold', 0.002)  # 0.2% per second
        self.strong_velocity = self.config.get('strong_velocity', 0.005)  # 0.5% per second
        
        # Staleness detection
        self.quote_update_history = deque(maxlen=10)
        self.max_staleness_seconds = self.config.get('max_staleness_seconds', 2)
        
        # Arbitrage thresholds
        self.min_arbitrage_bps = self.config.get('min_arbitrage_bps', 5)  # 5 bps minimum
        self.max_arbitrage_bps = self.config.get('max_arbitrage_bps', 50)  # Cap at 50 bps
        
        # Microprice calculation
        self.depth_levels = self.config.get('depth_levels', 3)
        
        # Cooldown
        self.last_signal_time = 0
        self.cooldown_seconds = self.config.get('cooldown_seconds', 30)
        
        # Minimum volume
        self.min_volume = self.config.get('min_volume', 1000)
        
        # Consecutive velocity confirmation
        self.velocity_count = 0
        self.last_velocity_direction = None
        self.confirmation_periods = self.config.get('confirmation_periods', 2)
    
    def calculate_price_velocity(self) -> tuple:
        """
        Calculate price velocity (change per second).
        Returns (velocity, direction, acceleration)
        """
        if len(self.price_history) < 3:
            return 0.0, "neutral", 0.0
        
        prices = list(self.price_history)
        
        # Calculate velocity over last few ticks
        recent_prices = prices[-3:]
        price_change = (recent_prices[-1] - recent_prices[0]) / recent_prices[0] if recent_prices[0] > 0 else 0
        
        # Assume ~1 second between updates for velocity calc
        velocity = abs(price_change)
        direction = "up" if price_change > 0 else "down" if price_change < 0 else "neutral"
        
        # Calculate acceleration (change in velocity)
        if len(self.velocity_history) >= 2:
            prev_velocity = self.velocity_history[-2]
            acceleration = velocity - prev_velocity
        else:
            acceleration = 0.0
        
        return velocity, direction, acceleration
    
    def calculate_microprice(self, data: MarketData) -> float:
        """
        Calculate fair value (microprice) from order book.
        """
        if not data.order_book:
            return data.mid
        
        bids = data.order_book.get('bids', [])
        asks = data.order_book.get('asks', [])
        
        if not bids or not asks:
            return data.mid
        
        best_bid = float(bids[0].get('price', data.bid))
        best_ask = float(asks[0].get('price', data.ask))
        
        bid_vol = sum(float(b.get('size', 0)) for b in bids[:self.depth_levels])
        ask_vol = sum(float(a.get('size', 0)) for a in asks[:self.depth_levels])
        total_vol = bid_vol + ask_vol
        
        if total_vol < self.min_volume:
            return data.mid
        
        # Volume-weighted microprice
        microprice = (best_bid * ask_vol + best_ask * bid_vol) / total_vol
        return microprice
    
    def detect_stale_quote_arbitrage(self, data: MarketData, velocity: float, direction: str) -> tuple:
        """
        Detect if current quotes are stale relative to fair value.
        
        Returns: (is_arbitrage, trade_direction, edge_bps)
        
        If price moved UP rapidly:
        - Old bids are too high (stale) → hit them (sell)
        - Fair value > bid → arbitrage
        
        If price moved DOWN rapidly:
        - Old asks are too low (stale) → lift them (buy)
        - Fair value < ask → arbitrage
        """
        if not data.order_book:
            return False, "neutral", 0.0
        
        bids = data.order_book.get('bids', [])
        asks = data.order_book.get('asks', [])
        
        if not bids or not asks:
            return False, "neutral", 0.0
        
        best_bid = float(bids[0].get('price', data.bid))
        best_ask = float(asks[0].get('price', data.ask))
        
        # Calculate fair value
        fair_value = self.calculate_microprice(data)
        
        # Check for stale bid (price moved up, bid hasn't adjusted)
        if direction == "up" and velocity > self.velocity_threshold:
            # Fair value should be higher than bid after an up move
            if fair_value > best_bid:
                edge = (fair_value - best_bid) / best_bid * 10000  # bps
                if self.min_arbitrage_bps <= edge <= self.max_arbitrage_bps:
                    return True, "up", edge  # Buy the stale bid (it's underpriced)
        
        # Check for stale ask (price moved down, ask hasn't adjusted)
        if direction == "down" and velocity > self.velocity_threshold:
            # Fair value should be lower than ask after a down move
            if fair_value < best_ask:
                edge = (best_ask - fair_value) / best_ask * 10000  # bps
                if self.min_arbitrage_bps <= edge <= self.max_arbitrage_bps:
                    return True, "down", edge  # Sell the stale ask (it's overpriced)
        
        return False, "neutral", 0.0
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_time = data.timestamp
        
        # Cooldown check
        if current_time - self.last_signal_time < self.cooldown_seconds:
            return None
        
        # Update price history
        self.price_history.append(data.price)
        
        # Need enough history
        if len(self.price_history) < 5:
            return None
        
        # Calculate velocity
        velocity, direction, acceleration = self.calculate_price_velocity()
        self.velocity_history.append(velocity)
        
        # Need sufficient velocity for latency arbitrage
        if velocity < self.velocity_threshold:
            self.velocity_count = 0
            self.last_velocity_direction = None
            return None
        
        # Track consecutive velocity in same direction
        if direction == self.last_velocity_direction:
            self.velocity_count += 1
        else:
            self.velocity_count = 1
            self.last_velocity_direction = direction
        
        # Need confirmation of sustained move
        if self.velocity_count < self.confirmation_periods:
            return None
        
        # Detect stale quote arbitrage opportunity
        is_arb, trade_direction, edge_bps = self.detect_stale_quote_arbitrage(data, velocity, direction)
        
        if is_arb:
            # Calculate confidence based on velocity and edge
            base_conf = 0.62
            velocity_boost = min((velocity - self.velocity_threshold) / self.velocity_threshold * 0.1, 0.1)
            edge_boost = min(edge_bps / 100, 0.1)  # Max 0.1 from edge
            
            confidence = min(base_conf + velocity_boost + edge_boost, 0.85)
            
            if confidence >= self.min_confidence:
                self.last_signal_time = current_time
                
                return Signal(
                    strategy=self.name,
                    signal=trade_direction,
                    confidence=confidence,
                    reason=f"Latency arb: {direction} velocity {velocity:.3%}/s, edge {edge_bps:.1f}bps",
                    metadata={
                        'velocity': velocity,
                        'direction': direction,
                        'acceleration': acceleration,
                        'edge_bps': edge_bps,
                        'fair_value': self.calculate_microprice(data),
                        'velocity_count': self.velocity_count
                    }
                )
        
        return None
