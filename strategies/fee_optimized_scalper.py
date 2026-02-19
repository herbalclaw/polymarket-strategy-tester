"""
Fee-Optimized Scalping Strategy

Exploits Polymarket's fee structure where fees are lowest at price extremes.
Mathematical edge: fee(p) = p × (1-p) × r, where r = fee_rate_bps

At p=0.05: fee = 0.30%, breakeven edge = 0.31%
At p=0.50: fee = 1.56%, breakeven edge = 3.13%
At p=0.95: fee = 0.30%, breakeven edge = 5.94%

Strategy: Only trade near extremes (p < 0.15 or p > 0.85) where fees are minimal
and breakeven edge requirements are lowest.

Reference: quantjourney.substack.com - Understanding the Polymarket Fee Curve
"""

from typing import Optional
from collections import deque
import statistics

from core.base_strategy import BaseStrategy, Signal, MarketData


class FeeOptimizedScalperStrategy(BaseStrategy):
    """
    Fee-optimized scalping strategy for Polymarket.
    
    Key insight: Polymarket fees follow a parabolic curve peaking at 0.50.
    By only trading near extremes, we minimize fee drag and maximize
    the probability of profit on small edges.
    
    Trading zones:
    - Long zone: price < 0.15 (low fee, high upside)
    - Short zone: price > 0.85 (low fee, high upside on NO)
    """
    
    name = "FeeOptimizedScalper"
    description = "Fee-optimized scalping near price extremes"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        config = config or {}
        
        # Price zones for trading (extremes only)
        self.long_threshold = self.config.get('long_threshold', 0.15)
        self.short_threshold = self.config.get('short_threshold', 0.85)
        
        # Minimum edge required (accounting for fees)
        self.min_edge_bps = self.config.get('min_edge_bps', 50)  # 0.5%
        
        # Lookback for mean reversion detection
        self.lookback = self.config.get('lookback', 10)
        self.price_history = deque(maxlen=self.lookback)
        
        # Volatility filter
        self.max_volatility = self.config.get('max_volatility', 0.05)  # 5%
        
        # Fee calculation constants (approximate)
        self.fee_rate = self.config.get('fee_rate', 0.000625)  # 6.25 bps base
    
    def calculate_fee(self, price: float) -> float:
        """Calculate taker fee at given price."""
        return price * (1 - price) * self.fee_rate
    
    def calculate_breakeven_edge(self, price: float) -> float:
        """Calculate breakeven edge required at given price."""
        fee = self.calculate_fee(price)
        if price < 0.5:
            upside = 1.0 - price
        else:
            upside = price  # For NO tokens, upside is price
        return fee / upside if upside > 0 else 1.0
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        price = data.price
        
        # Store price history
        self.price_history.append(price)
        
        # Only trade in extreme zones
        in_long_zone = price < self.long_threshold
        in_short_zone = price > self.short_threshold
        
        if not (in_long_zone or in_short_zone):
            return None
        
        # Need enough history
        if len(self.price_history) < self.lookback // 2:
            return None
        
        # Calculate volatility
        prices = list(self.price_history)
        try:
            volatility = statistics.stdev(prices) / statistics.mean(prices) if len(prices) > 1 else 0
        except:
            volatility = 0
        
        # Skip high volatility periods
        if volatility > self.max_volatility:
            return None
        
        # Calculate mean and trend
        mean_price = statistics.mean(prices)
        
        # Fee-adjusted edge calculation
        fee = self.calculate_fee(price)
        breakeven = self.calculate_breakeven_edge(price)
        
        signal = None
        confidence = 0.0
        reason = ""
        
        if in_long_zone:
            # Price is very low - potential mean reversion up
            # Only enter if we have some upward momentum or extreme deviation
            price_vs_mean = (mean_price - price) / price if price > 0 else 0
            
            # Edge = potential gain - fees
            potential_gain = (mean_price - price) if price < mean_price else 0.01
            edge = potential_gain - fee
            edge_bps = edge * 10000
            
            if edge_bps > self.min_edge_bps:
                confidence = min(0.6 + edge_bps / 200, 0.85)
                signal = "up"
                reason = f"Extreme low {price:.3f}, edge {edge_bps:.0f}bps, fee {fee*10000:.1f}bps"
        
        elif in_short_zone:
            # Price is very high - potential mean reversion down
            price_vs_mean = (price - mean_price) / price if price > 0 else 0
            
            # For short, we're betting on NO (price going down)
            potential_gain = (price - mean_price) if price > mean_price else 0.01
            edge = potential_gain - fee
            edge_bps = edge * 10000
            
            if edge_bps > self.min_edge_bps:
                confidence = min(0.6 + edge_bps / 200, 0.85)
                signal = "down"
                reason = f"Extreme high {price:.3f}, edge {edge_bps:.0f}bps, fee {fee*10000:.1f}bps"
        
        if signal and confidence >= self.min_confidence:
            return Signal(
                strategy=self.name,
                signal=signal,
                confidence=confidence,
                reason=reason,
                metadata={
                    'price': price,
                    'fee_bps': fee * 10000,
                    'breakeven_bps': breakeven * 10000,
                    'edge_bps': edge_bps if 'edge_bps' in dir() else 0,
                    'zone': 'long' if in_long_zone else 'short',
                    'volatility': volatility
                }
            )
        
        return None
