"""
SpreadCaptureStrategy

Exploits bid-ask spread dynamics in prediction markets. Market makers
quote spreads that vary based on volatility, inventory, and time to
settlement. By capturing the spread at favorable times, we can generate
consistent small profits.

Key insight: Spreads widen during uncertainty and contract during stability.
Entering near mid during wide spreads and exiting as spreads compress
captures the spread decay.

Reference: "Market Microstructure & High-Frequency Trading" - Preston (2024)
"Bid-ask spread dynamics in prediction markets" - various
"""

from typing import Optional
from collections import deque
import statistics
import time

from core.base_strategy import BaseStrategy, Signal, MarketData


class SpreadCaptureStrategy(BaseStrategy):
    """
    Capture bid-ask spread compression profits.
    
    Strategy logic:
    1. Monitor spread width relative to historical average
    2. Enter positions when spreads are wide (>75th percentile)
    3. Exit as spreads compress back to normal
    4. Use limit orders when possible to capture maker rebates
    
    Works best in volatile but mean-reverting conditions.
    """
    
    name = "SpreadCapture"
    description = "Capture profits from bid-ask spread dynamics"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        config = config or {}
        
        # Spread tracking
        self.spread_history = deque(maxlen=50)
        self.spread_percentiles = deque(maxlen=50)
        
        # Entry/exit thresholds (percentile-based)
        self.wide_spread_threshold = self.config.get('wide_spread_threshold', 0.75)  # 75th percentile
        self.normal_spread_threshold = self.config.get('normal_spread_threshold', 0.50)  # 50th percentile
        
        # Minimum spread requirements
        self.min_spread_bps = self.config.get('min_spread_bps', 10)  # 0.1%
        self.max_spread_bps = self.config.get('max_spread_bps', 200)  # 2%
        
        # Volatility filter
        self.price_history = deque(maxlen=30)
        self.max_volatility = self.config.get('max_volatility', 0.03)  # 3%
        
        # Position tracking (for spread capture logic)
        self.in_position = False
        self.position_direction = None
        self.entry_spread = 0.0
        self.entry_time = 0
        
        # Time decay
        self.max_hold_seconds = self.config.get('max_hold_seconds', 120)
        
        # Cooldown
        self.last_signal_time = 0
        self.cooldown_seconds = self.config.get('cooldown_seconds', 45)
        
        # Minimum volume
        self.min_volume = self.config.get('min_volume', 500)
    
    def calculate_spread_metrics(self, data: MarketData) -> dict:
        """
        Calculate various spread metrics.
        """
        spread = data.ask - data.bid if data.ask > data.bid else 0
        mid = data.mid
        spread_bps = (spread / mid * 10000) if mid > 0 else 0
        
        self.spread_history.append(spread_bps)
        
        metrics = {
            'current_spread': spread,
            'current_bps': spread_bps,
            'mid': mid,
            'bid': data.bid,
            'ask': data.ask
        }
        
        # Calculate percentiles if we have enough history
        if len(self.spread_history) >= 20:
            spreads = sorted(self.spread_history)
            metrics['median_spread'] = statistics.median(spreads)
            metrics['p25'] = spreads[int(len(spreads) * 0.25)]
            metrics['p75'] = spreads[int(len(spreads) * 0.75)]
            metrics['p90'] = spreads[int(len(spreads) * 0.90)]
            
            # Current percentile
            current = spread_bps
            below_count = sum(1 for s in spreads if s < current)
            metrics['current_percentile'] = below_count / len(spreads)
        else:
            metrics['median_spread'] = spread_bps
            metrics['p25'] = spread_bps * 0.5
            metrics['p75'] = spread_bps * 1.5
            metrics['p90'] = spread_bps * 2.0
            metrics['current_percentile'] = 0.5
        
        return metrics
    
    def calculate_volatility(self) -> float:
        """Calculate recent price volatility."""
        if len(self.price_history) < 10:
            return 0.0
        
        prices = list(self.price_history)
        try:
            return statistics.stdev(prices) / statistics.mean(prices) if len(prices) > 1 else 0
        except:
            return 0.0
    
    def detect_spread_opportunity(self, metrics: dict, data: MarketData) -> tuple:
        """
        Detect if current spread presents opportunity.
        
        Returns: (is_opportunity, direction, expected_edge)
        """
        spread_bps = metrics['current_bps']
        percentile = metrics.get('current_percentile', 0.5)
        
        # Filter out extreme spreads (likely news/event)
        if spread_bps > self.max_spread_bps:
            return False, "neutral", 0.0
        
        # Need minimum spread to be worth it
        if spread_bps < self.min_spread_bps:
            return False, "neutral", 0.0
        
        # Check if spread is wide (opportunity to capture compression)
        if percentile > self.wide_spread_threshold:
            # Determine direction based on price position within spread
            mid = metrics['mid']
            price = data.price
            
            # If price near bid, market is selling (potential up)
            # If price near ask, market is buying (potential down)
            bid_distance = (price - metrics['bid']) / spread if spread > 0 else 0.5
            
            if bid_distance < 0.3:
                # Price near bid - likely to bounce up
                direction = "up"
            elif bid_distance > 0.7:
                # Price near ask - likely to bounce down
                direction = "down"
            else:
                # Price near mid - need other signals
                return False, "neutral", 0.0
            
            # Expected edge is half the spread (capturing spread compression)
            expected_edge = spread_bps / 2
            
            return True, direction, expected_edge
        
        return False, "neutral", 0.0
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_time = data.timestamp
        
        # Update history
        self.price_history.append(data.price)
        
        # Calculate spread metrics
        metrics = self.calculate_spread_metrics(data)
        
        # Check volatility
        volatility = self.calculate_volatility()
        if volatility > self.max_volatility:
            return None
        
        # Check volume if available
        if hasattr(data, 'volume') and data.volume and data.volume < self.min_volume:
            return None
        
        # Detect opportunity
        is_opp, direction, edge = self.detect_spread_opportunity(metrics, data)
        
        if is_opp:
            # Cooldown check
            if current_time - self.last_signal_time < self.cooldown_seconds:
                return None
            
            # Calculate confidence based on spread percentile and edge
            percentile = metrics.get('current_percentile', 0.5)
            base_conf = 0.58
            spread_boost = (percentile - self.wide_spread_threshold) * 0.3
            edge_boost = min(edge / 100, 0.10)  # Edge in bps / 100
            
            confidence = min(base_conf + spread_boost + edge_boost, 0.82)
            
            self.last_signal_time = current_time
            
            return Signal(
                strategy=self.name,
                signal=direction,
                confidence=confidence,
                reason=f"Wide spread capture: {metrics['current_bps']:.1f}bps at P{percentile:.0%}, edge={edge:.1f}bps",
                metadata={
                    'spread_bps': metrics['current_bps'],
                    'percentile': percentile,
                    'expected_edge': edge,
                    'median_spread': metrics.get('median_spread', 0),
                    'volatility': volatility
                }
            )
        
        return None
