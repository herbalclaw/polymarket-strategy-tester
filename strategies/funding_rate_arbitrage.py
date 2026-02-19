"""
FundingRateArbitrage Strategy - Exploit funding rate anomalies in prediction markets.

Economic Rationale:
- Polymarket doesn't have traditional funding rates like perp exchanges
- However, the "implied funding" comes from the time decay of binary options
- The edge comes from comparing the current price to the expected drift
- In efficient markets, price should drift toward the true probability over time

Edge Source:
- Time-premium extraction
- Drift arbitrage (price vs expected value)
- Mean reversion of overextended moves
"""

from typing import Optional, Dict, Any, List
from datetime import datetime
from core.base_strategy import BaseStrategy, Signal, MarketData


class FundingRateArbitrageStrategy(BaseStrategy):
    """
    Exploit time-premium and drift in BTC 5-min prediction markets.
    
    Logic:
    - Binary options have negative theta (time decay)
    - Price should drift toward 0 or 1 as expiry approaches
    - When price stays flat despite time passing, there's mispricing
    - Trade the expected drift vs actual price action
    
    This is analogous to funding rate arbitrage in perpetual futures:
    - Longs pay shorts when perp > spot
    - Here, "time buyers" pay "time sellers" through decay
    """
    
    name = "FundingRateArbitrage"
    version = "1.0.0"
    
    def __init__(self, config: Dict = None):
        super().__init__(config)
        self.price_history: List[Dict] = []
        self.max_history = 50
        
        # Drift thresholds
        self.min_drift_threshold = 0.01  # 1% minimum expected drift
        self.time_decay_factor = 0.15  # How fast should price drift
        
    def calculate_expected_drift(self, current_price: float, time_remaining: float) -> float:
        """
        Calculate expected price drift given time remaining.
        
        In binary options, price should accelerate toward 0 or 1 as expiry approaches.
        This is the "theta" effect.
        """
        if time_remaining <= 0:
            return 0.0
        
        # Distance from 0.50 (neutral)
        distance_from_neutral = abs(current_price - 0.50)
        
        # If price is near 0.50, drift is minimal (uncertainty zone)
        # If price is far from 0.50, drift accelerates toward resolution
        if distance_from_neutral < 0.05:
            return 0.0
        
        # Expected drift per second (simplified model)
        # Price should move toward nearest extreme (0 or 1)
        direction = 1 if current_price > 0.50 else -1
        expected_move = direction * self.time_decay_factor * (distance_from_neutral / time_remaining)
        
        return expected_move
    
    def detect_stagnation(self, prices: List[float], window: int = 10) -> float:
        """
        Detect if price has been stagnant (flat) despite time passing.
        Returns stagnation score (0 = moving normally, 1 = completely flat).
        """
        if len(prices) < window:
            return 0.0
        
        recent = prices[-window:]
        price_range = max(recent) - min(recent)
        
        # Normalize by average price
        avg_price = sum(recent) / len(recent)
        if avg_price == 0:
            return 0.0
        
        normalized_range = price_range / avg_price
        
        # If range is very small relative to time passed, it's stagnant
        stagnation = max(0, 1 - normalized_range * 10)
        
        return stagnation
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        """Generate signal based on funding rate (time premium) arbitrage."""
        
        current_price = data.mid
        current_time = data.timestamp
        
        # Time in current 5-minute window
        time_in_window = current_time % 300
        time_remaining = 300 - time_in_window
        progress = time_in_window / 300  # 0 to 1
        
        # Track history
        self.price_history.append({
            'price': current_price,
            'time': current_time,
            'time_remaining': time_remaining,
            'progress': progress
        })
        
        if len(self.price_history) > self.max_history:
            self.price_history.pop(0)
        
        if len(self.price_history) < 15:
            return None
        
        prices = [p['price'] for p in self.price_history]
        
        # Calculate expected drift
        expected_drift = self.calculate_expected_drift(current_price, time_remaining)
        
        # Detect stagnation
        stagnation = self.detect_stagnation(prices, 15)
        
        # Get order book
        if not data.order_book:
            return None
        
        bids = data.order_book.get('bids', [])
        asks = data.order_book.get('asks', [])
        
        if not bids or not asks:
            return None
        
        # Calculate bid-ask imbalance
        bid_vol = sum(b[1] for b in bids[:3]) if bids else 0
        ask_vol = sum(a[1] for a in asks[:3]) if asks else 0
        
        if bid_vol + ask_vol == 0:
            return None
        
        imbalance = (bid_vol - ask_vol) / (bid_vol + ask_vol)
        
        # SIGNAL 1: Price stagnation with expected drift
        # If price should be drifting but isn't, trade the expected move
        if stagnation > 0.6 and abs(expected_drift) > self.min_drift_threshold:
            
            # Price should be rising but is flat
            if expected_drift > 0 and imbalance > 0.2:
                confidence = min(0.85, 0.6 + stagnation * 0.2 + abs(expected_drift) * 10)
                return Signal(
                    strategy=self.name,
                    signal='up',
                    confidence=confidence,
                    reason=f"Drift arb UP: stagnation={stagnation:.2f}, expected_drift={expected_drift:+.4f}",
                    metadata={
                        'stagnation': stagnation,
                        'expected_drift': expected_drift,
                        'imbalance': imbalance,
                        'time_remaining': time_remaining
                    }
                )
            
            # Price should be falling but is flat
            if expected_drift < 0 and imbalance < -0.2:
                confidence = min(0.85, 0.6 + stagnation * 0.2 + abs(expected_drift) * 10)
                return Signal(
                    strategy=self.name,
                    signal='down',
                    confidence=confidence,
                    reason=f"Drift arb DOWN: stagnation={stagnation:.2f}, expected_drift={expected_drift:+.4f}",
                    metadata={
                        'stagnation': stagnation,
                        'expected_drift': expected_drift,
                        'imbalance': imbalance,
                        'time_remaining': time_remaining
                    }
                )
        
        # SIGNAL 2: Late-window acceleration
        # In final 90 seconds, if price hasn't moved much, expect resolution
        if time_remaining < 90 and progress > 0.7:
            
            # Calculate price change over window
            price_change = prices[-1] - prices[0]
            
            # If price is high (>0.65) but hasn't accelerated, buy
            if current_price > 0.65 and price_change < 0.05 and imbalance > 0.15:
                confidence = min(0.88, 0.62 + (current_price - 0.65) * 0.5)
                return Signal(
                    strategy=self.name,
                    signal='up',
                    confidence=confidence,
                    reason=f"Late-window drift UP: price={current_price:.3f}, progress={progress:.1%}",
                    metadata={
                        'price': current_price,
                        'progress': progress,
                        'price_change': price_change,
                        'imbalance': imbalance
                    }
                )
            
            # If price is low (<0.35) but hasn't accelerated, sell
            if current_price < 0.35 and price_change > -0.05 and imbalance < -0.15:
                confidence = min(0.88, 0.62 + (0.35 - current_price) * 0.5)
                return Signal(
                    strategy=self.name,
                    signal='down',
                    confidence=confidence,
                    reason=f"Late-window drift DOWN: price={current_price:.3f}, progress={progress:.1%}",
                    metadata={
                        'price': current_price,
                        'progress': progress,
                        'price_change': price_change,
                        'imbalance': imbalance
                    }
                )
        
        # SIGNAL 3: Time-premium extraction
        # When price is stuck near 0.50 with high volume, fade the move
        if 0.45 <= current_price <= 0.55 and stagnation < 0.3:
            recent_volatility = max(prices[-10:]) - min(prices[-10:])
            
            if recent_volatility > 0.08:  # High recent volatility
                # Price spiked up but coming back down
                if prices[-1] < prices[-5] and imbalance < -0.1:
                    confidence = min(0.8, 0.6 + recent_volatility * 2)
                    return Signal(
                        strategy=self.name,
                        signal='down',
                        confidence=confidence,
                        reason=f"Time premium fade: volatility={recent_volatility:.3f}, imbalance={imbalance:.2f}",
                        metadata={
                            'volatility': recent_volatility,
                            'imbalance': imbalance,
                            'price': current_price
                        }
                    )
                
                # Price crashed down but bouncing back
                if prices[-1] > prices[-5] and imbalance > 0.1:
                    confidence = min(0.8, 0.6 + recent_volatility * 2)
                    return Signal(
                        strategy=self.name,
                        signal='up',
                        confidence=confidence,
                        reason=f"Time premium fade: volatility={recent_volatility:.3f}, imbalance={imbalance:.2f}",
                        metadata={
                            'volatility': recent_volatility,
                            'imbalance': imbalance,
                            'price': current_price
                        }
                    )
        
        return None
