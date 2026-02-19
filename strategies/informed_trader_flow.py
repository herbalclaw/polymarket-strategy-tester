"""
InformedTraderFlow Strategy

Detects "smart money" activity through volume-price divergence patterns.
Based on VPIN (Volume-Synchronized Probability of Informed Trading) research.

Key insight: Large informed traders leave footprints in volume patterns.
When volume spikes without corresponding price movement, it suggests
informed accumulation (if buying) or distribution (if selling).

Reference: "VPIN and the Flash Crash" - Easley, Lopez de Prado, O'Hara
"""

from typing import Optional
from collections import deque
from statistics import mean, stdev

from core.base_strategy import BaseStrategy, Signal, MarketData


class InformedTraderFlowStrategy(BaseStrategy):
    """
    Detect informed trading through volume-price divergence.
    
    Smart money often trades in ways that minimize market impact.
    This creates patterns where volume increases but price doesn't
    move proportionally - signaling informed accumulation/distribution.
    """
    
    name = "InformedTraderFlow"
    description = "Detect smart money through volume-price patterns"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        
        # Price and volume history
        self.price_history: deque = deque(maxlen=100)
        self.volume_history: deque = deque(maxlen=100)
        self.returns_history: deque = deque(maxlen=100)
        
        # VPIN-like calculation parameters
        self.volume_buckets = self.config.get('volume_buckets', 50)
        self.bucket_size = self.config.get('bucket_size', 1000)  # $1000 volume per bucket
        
        # Volume imbalance threshold
        self.imbalance_threshold = self.config.get('imbalance_threshold', 0.6)  # 60% buy or sell
        
        # Price absorption detection
        self.absorption_threshold = self.config.get('absorption_threshold', 2.0)  # 2x normal volume
        self.price_move_threshold = self.config.get('price_move_threshold', 0.002)  # 0.2%
        
        # Trend confirmation
        self.use_trend = self.config.get('use_trend', True)
        self.trend_periods = self.config.get('trend_periods', 10)
        
        # Signal generation
        self.min_confidence = self.config.get('min_confidence', 0.6)
        
        # Cooldown
        self.cooldown_periods = self.config.get('cooldown_periods', 8)
        self.last_signal_period = -self.cooldown_periods
        self.period_count = 0
        
        # Track volume at bid vs ask
        self.bid_volume_history: deque = deque(maxlen=50)
        self.ask_volume_history: deque = deque(maxlen=50)
    
    def calculate_returns(self) -> float:
        """Calculate recent return."""
        if len(self.price_history) < 2:
            return 0
        
        prices = list(self.price_history)
        current = prices[-1]
        previous = prices[-2]
        
        if previous == 0:
            return 0
        
        return (current - previous) / previous
    
    def detect_volume_anomaly(self) -> tuple:
        """
        Detect unusual volume patterns.
        Returns (is_anomaly, volume_ratio, direction)
        """
        if len(self.volume_history) < 20:
            return False, 0, "neutral"
        
        volumes = list(self.volume_history)
        current_volume = volumes[-1]
        avg_volume = mean(volumes[-20:])
        
        if avg_volume == 0:
            return False, 0, "neutral"
        
        volume_ratio = current_volume / avg_volume
        
        # Check if volume is anomalously high
        is_anomaly = volume_ratio > self.absorption_threshold
        
        # Determine direction from order book if available
        direction = "neutral"
        if len(self.bid_volume_history) > 0 and len(self.ask_volume_history) > 0:
            bid_vol = self.bid_volume_history[-1]
            ask_vol = self.ask_volume_history[-1]
            total = bid_vol + ask_vol
            
            if total > 0:
                if bid_vol / total > self.imbalance_threshold:
                    direction = "buying"
                elif ask_vol / total > self.imbalance_threshold:
                    direction = "selling"
        
        return is_anomaly, volume_ratio, direction
    
    def detect_price_absorption(self) -> tuple:
        """
        Detect price absorption - high volume with minimal price movement.
        Returns (is_absorption, absorption_score, direction)
        """
        if len(self.price_history) < 10 or len(self.volume_history) < 10:
            return False, 0, "neutral"
        
        # Calculate recent price volatility
        returns = []
        prices = list(self.price_history)
        for i in range(1, min(10, len(prices))):
            if prices[-i-1] > 0:
                r = (prices[-i] - prices[-i-1]) / prices[-i-1]
                returns.append(abs(r))
        
        if not returns:
            return False, 0, "neutral"
        
        avg_abs_return = mean(returns)
        current_return = abs(self.calculate_returns())
        
        # Volume anomaly detection
        is_anomaly, volume_ratio, direction = self.detect_volume_anomaly()
        
        if not is_anomaly:
            return False, 0, "neutral"
        
        # Price absorption: high volume but low price movement
        if current_return < self.price_move_threshold and avg_abs_return > 0:
            absorption_score = volume_ratio * (avg_abs_return / max(current_return, 0.0001))
            
            if absorption_score > 2.0:  # Significant absorption
                return True, absorption_score, direction
        
        return False, 0, "neutral"
    
    def get_trend_direction(self) -> float:
        """Get trend direction (-1 to 1)."""
        if len(self.price_history) < self.trend_periods:
            return 0
        
        prices = list(self.price_history)
        early = mean(prices[-self.trend_periods:-self.trend_periods//2])
        late = mean(prices[-self.trend_periods//2:])
        
        if early == 0:
            return 0
        
        trend = (late - early) / early
        return max(-1, min(1, trend * 20))  # Scale and clamp
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_price = data.price
        self.period_count += 1
        
        # Update history
        self.price_history.append(current_price)
        self.volume_history.append(data.volume_24h)
        
        # Update order book volume if available
        if data.order_book:
            bids = data.order_book.get('bids', [])
            asks = data.order_book.get('asks', [])
            
            bid_vol = sum(float(b.get('size', 0)) for b in bids[:5])
            ask_vol = sum(float(a.get('size', 0)) for a in asks[:5])
            
            self.bid_volume_history.append(bid_vol)
            self.ask_volume_history.append(ask_vol)
        
        # Check cooldown
        if self.period_count - self.last_signal_period < self.cooldown_periods:
            return None
        
        # Need enough data
        if len(self.price_history) < 30:
            return None
        
        # Calculate returns
        ret = self.calculate_returns()
        self.returns_history.append(ret)
        
        # Detect price absorption (smart money footprint)
        is_absorption, score, direction = self.detect_price_absorption()
        
        if not is_absorption:
            return None
        
        # Get trend for confirmation
        trend = self.get_trend_direction()
        
        # Generate signal based on informed flow direction
        signal = None
        confidence = 0.0
        
        if direction == "buying":
            # Informed buying detected
            if self.use_trend and trend > 0:
                # Confirm with trend
                confidence = min(0.6 + (score - 2) * 0.05 + trend * 0.1, 0.85)
            elif not self.use_trend:
                confidence = min(0.6 + (score - 2) * 0.05, 0.8)
            
            if confidence >= self.min_confidence:
                signal = "up"
        
        elif direction == "selling":
            # Informed selling detected
            if self.use_trend and trend < 0:
                # Confirm with trend
                confidence = min(0.6 + (score - 2) * 0.05 + abs(trend) * 0.1, 0.85)
            elif not self.use_trend:
                confidence = min(0.6 + (score - 2) * 0.05, 0.8)
            
            if confidence >= self.min_confidence:
                signal = "down"
        
        if signal:
            self.last_signal_period = self.period_count
            
            return Signal(
                strategy=self.name,
                signal=signal,
                confidence=confidence,
                reason=f"Informed {direction} flow detected (absorption score: {score:.2f})",
                metadata={
                    'absorption_score': score,
                    'direction': direction,
                    'volume_ratio': score / (avg_abs_return / max(abs(ret), 0.0001)) if 'avg_abs_return' in dir() else score,
                    'trend': trend if self.use_trend else None,
                    'current_return': ret
                }
            )
        
        return None
