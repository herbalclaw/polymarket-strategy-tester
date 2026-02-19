"""
ImpliedVolatilitySkew Strategy - Exploit volatility skew in prediction markets.

Economic Rationale:
- In prediction markets, the price of YES and NO tokens should sum to $1.00
- When they don't, there's an arbitrage opportunity
- However, even when they sum to $1, the *volatility* of each side differs
- Near expiration, OTM options (low probability side) have higher implied volatility
- This creates predictable price dynamics

Edge Source:
- Volatility skew exploitation
- Time-decay asymmetry between YES and NO
- Gamma scalping near 50-cent zone
"""

from typing import Optional, Dict, Any, List
from datetime import datetime
import math
from core.base_strategy import BaseStrategy, Signal, MarketData


class ImpliedVolatilitySkewStrategy(BaseStrategy):
    """
    Exploit volatility skew asymmetry in BTC 5-min prediction markets.
    
    Logic:
    - In binary options, the "losing" side (far from current price) has higher IV
    - This creates convexity that can be exploited
    - Near 50 cents, gamma is highest - small moves create large P&L swings
    - Trade the volatility surface, not just direction
    """
    
    name = "ImpliedVolatilitySkew"
    version = "1.0.0"
    
    def __init__(self, config: Dict = None):
        super().__init__(config)
        self.price_history: List[Dict] = []
        self.max_history = 30
        
        # Gamma zone (highest convexity)
        self.gamma_zone_low = 0.45
        self.gamma_zone_high = 0.55
        
        # Volatility threshold
        self.min_volatility = 0.02  # 2% minimum realized vol
        
    def calculate_realized_volatility(self, prices: List[float], window: int = 10) -> float:
        """Calculate realized volatility from price history."""
        if len(prices) < window + 1:
            return 0.0
        
        recent = prices[-window:]
        returns = []
        for i in range(1, len(recent)):
            if recent[i-1] > 0:
                ret = (recent[i] - recent[i-1]) / recent[i-1]
                returns.append(ret)
        
        if not returns:
            return 0.0
        
        # Standard deviation of returns (annualized for 5-min windows)
        mean_ret = sum(returns) / len(returns)
        variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
        
        # For 5-min windows, approximate daily vol
        return math.sqrt(variance) * math.sqrt(288)  # 288 5-min periods per day
    
    def calculate_gamma(self, price: float) -> float:
        """
        Approximate gamma for binary option.
        Gamma is highest near 0.50 and decreases toward extremes.
        """
        # Simplified gamma approximation
        distance_from_50 = abs(price - 0.50)
        return max(0.1, 2.0 - 3.0 * distance_from_50)
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        """Generate signal based on volatility skew and gamma positioning."""
        
        current_price = data.mid
        
        # Track price and time
        current_time = data.timestamp
        time_in_window = current_time % 300
        time_remaining = 300 - time_in_window
        
        self.price_history.append({
            'price': current_price,
            'time': current_time,
            'time_remaining': time_remaining
        })
        
        if len(self.price_history) > self.max_history:
            self.price_history.pop(0)
        
        if len(self.price_history) < 10:
            return None
        
        prices = [p['price'] for p in self.price_history]
        realized_vol = self.calculate_realized_volatility(prices)
        gamma = self.calculate_gamma(current_price)
        
        # Get order book for skew analysis
        if not data.order_book:
            return None
        
        bids = data.order_book.get('bids', [])
        asks = data.order_book.get('asks', [])
        
        if not bids or not asks:
            return None
        
        # Calculate bid-ask spread
        best_bid = bids[0][0] if bids else current_price - 0.01
        best_ask = asks[0][0] if asks else current_price + 0.01
        spread = best_ask - best_bid
        
        # Calculate depth imbalance (measure of skew)
        bid_depth = sum(b[1] for b in bids[:5]) if len(bids) >= 5 else sum(b[1] for b in bids)
        ask_depth = sum(a[1] for a in asks[:5]) if len(asks) >= 5 else sum(a[1] for a in asks)
        
        if bid_depth + ask_depth == 0:
            return None
        
        depth_skew = (bid_depth - ask_depth) / (bid_depth + ask_depth)
        
        # SIGNAL 1: Gamma scalping in high-vol environment
        # When price is near 50c with high volatility, trade the oscillations
        if self.gamma_zone_low <= current_price <= self.gamma_zone_high and realized_vol > self.min_volatility:
            
            # Price rising toward 55c - expect resistance and fade
            if current_price > 0.52 and depth_skew < -0.2:
                confidence = min(0.85, 0.6 + gamma * 0.2 + realized_vol * 5)
                return Signal(
                    strategy=self.name,
                    signal='down',
                    confidence=confidence,
                    reason=f"Gamma scalp fade high: price={current_price:.3f}, gamma={gamma:.2f}, vol={realized_vol:.3f}",
                    metadata={
                        'price': current_price,
                        'gamma': gamma,
                        'realized_vol': realized_vol,
                        'depth_skew': depth_skew
                    }
                )
            
            # Price falling toward 45c - expect support and fade
            if current_price < 0.48 and depth_skew > 0.2:
                confidence = min(0.85, 0.6 + gamma * 0.2 + realized_vol * 5)
                return Signal(
                    strategy=self.name,
                    signal='up',
                    confidence=confidence,
                    reason=f"Gamma scalp fade low: price={current_price:.3f}, gamma={gamma:.2f}, vol={realized_vol:.3f}",
                    metadata={
                        'price': current_price,
                        'gamma': gamma,
                        'realized_vol': realized_vol,
                        'depth_skew': depth_skew
                    }
                )
        
        # SIGNAL 2: Volatility expansion after compression
        # When vol has been low and suddenly spikes, trade the breakout
        if len(self.price_history) >= 20:
            old_prices = [p['price'] for p in self.price_history[:10]]
            new_prices = [p['price'] for p in self.price_history[-10:]]
            
            old_vol = self.calculate_realized_volatility(old_prices, 10)
            new_vol = self.calculate_realized_volatility(new_prices, 10)
            
            # Volatility breakout
            if old_vol < 0.01 and new_vol > 0.03:
                # Direction based on price movement
                price_change = new_prices[-1] - old_prices[0]
                
                if price_change > 0.02:
                    confidence = min(0.8, 0.6 + new_vol * 5)
                    return Signal(
                        strategy=self.name,
                        signal='up',
                        confidence=confidence,
                        reason=f"Vol expansion breakout UP: vol_old={old_vol:.3f}, vol_new={new_vol:.3f}",
                        metadata={
                            'old_vol': old_vol,
                            'new_vol': new_vol,
                            'price_change': price_change
                        }
                    )
                elif price_change < -0.02:
                    confidence = min(0.8, 0.6 + new_vol * 5)
                    return Signal(
                        strategy=self.name,
                        signal='down',
                        confidence=confidence,
                        reason=f"Vol expansion breakout DOWN: vol_old={old_vol:.3f}, vol_new={new_vol:.3f}",
                        metadata={
                            'old_vol': old_vol,
                            'new_vol': new_vol,
                            'price_change': price_change
                        }
                    )
        
        # SIGNAL 3: Time-decay acceleration near expiry
        # In last 60 seconds, if price is far from 0/1, acceleration is predictable
        if time_remaining < 60 and realized_vol > 0.05:
            # If price > 0.7 with high vol, likely to resolve YES
            if current_price > 0.7 and depth_skew > 0.3:
                confidence = min(0.9, 0.65 + (current_price - 0.7) * 0.5)
                return Signal(
                    strategy=self.name,
                    signal='up',
                    confidence=confidence,
                    reason=f"Time decay momentum: price={current_price:.3f}, time_left={time_remaining}s",
                    metadata={
                        'price': current_price,
                        'time_remaining': time_remaining,
                        'depth_skew': depth_skew
                    }
                )
            
            # If price < 0.3 with high vol, likely to resolve NO
            if current_price < 0.3 and depth_skew < -0.3:
                confidence = min(0.9, 0.65 + (0.3 - current_price) * 0.5)
                return Signal(
                    strategy=self.name,
                    signal='down',
                    confidence=confidence,
                    reason=f"Time decay momentum: price={current_price:.3f}, time_left={time_remaining}s",
                    metadata={
                        'price': current_price,
                        'time_remaining': time_remaining,
                        'depth_skew': depth_skew
                    }
                )
        
        return None
