"""
VPIN (Volume-Synchronized Probability of Informed Trading) Strategy

Based on research by Easley, Lopez de Prado, and O'Hara (2012).
VPIN detects order flow toxicity - the probability that market makers
are trading against informed traders.

In prediction markets, high VPIN indicates informed traders know
something the market doesn't, creating a directional edge.

Reference: "Flow Toxicity and Volatility in a High Frequency World"
"""

from typing import Optional, Dict, List
from collections import deque
from statistics import mean, stdev
import math

from core.base_strategy import BaseStrategy, Signal, MarketData


class VPINStrategy(BaseStrategy):
    """
    VPIN-based strategy to detect informed trading.
    
    High VPIN = toxic order flow = informed traders are active
    When VPIN spikes above threshold, follow the direction of recent trades.
    """
    
    name = "VPIN"
    description = "Volume-Synchronized Probability of Informed Trading"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        
        # VPIN parameters
        self.bucket_size = self.config.get('bucket_size', 1000)  # Volume bucket size
        self.num_buckets = self.config.get('num_buckets', 50)  # Buckets for VPIN calc
        self.vpin_threshold = self.config.get('vpin_threshold', 0.60)  # 60% threshold
        
        # Trade tracking
        self.volume_buckets: deque = deque(maxlen=self.num_buckets)
        self.current_bucket_volume = 0
        self.current_bucket_buy_volume = 0
        
        # Price history for direction
        self.price_history: deque = deque(maxlen=20)
        
        # VPIN history for standardization
        self.vpin_history: deque = deque(maxlen=100)
        
        # Minimum data before generating signals
        self.min_buckets = 20
        
    def calculate_buy_volume(self, price: float, prev_price: float, volume: float) -> float:
        """
        Estimate buy vs sell volume using tick rule.
        
        Returns estimated buy volume (0 to volume).
        """
        if price > prev_price:
            # Uptick = mostly buying
            return volume * 0.8
        elif price < prev_price:
            # Downtick = mostly selling
            return volume * 0.2
        else:
            # No change = split
            return volume * 0.5
    
    def update_bucket(self, price: float, volume: float):
        """Update current volume bucket."""
        if len(self.price_history) > 0:
            prev_price = self.price_history[-1]
            buy_vol = self.calculate_buy_volume(price, prev_price, volume)
            self.current_bucket_buy_volume += buy_vol
        
        self.current_bucket_volume += volume
        
        # If bucket is full, save it and start new one
        if self.current_bucket_volume >= self.bucket_size:
            # Calculate buy/sell ratio for this bucket
            buy_ratio = self.current_bucket_buy_volume / self.current_bucket_volume if self.current_bucket_volume > 0 else 0.5
            
            self.volume_buckets.append({
                'volume': self.current_bucket_volume,
                'buy_ratio': buy_ratio,
                'sell_ratio': 1 - buy_ratio
            })
            
            # Reset bucket
            self.current_bucket_volume = 0
            self.current_bucket_buy_volume = 0
    
    def calculate_vpin(self) -> Optional[float]:
        """
        Calculate VPIN metric.
        
        VPIN = mean(|buy_ratio - sell_ratio|) across buckets
        Higher VPIN = more one-sided flow = more toxic
        """
        if len(self.volume_buckets) < self.min_buckets:
            return None
        
        imbalances = []
        for bucket in self.volume_buckets:
            imbalance = abs(bucket['buy_ratio'] - bucket['sell_ratio'])
            imbalances.append(imbalance)
        
        vpin = mean(imbalances) if imbalances else 0.5
        return vpin
    
    def get_price_trend(self) -> float:
        """Calculate recent price trend (-1 to 1)."""
        if len(self.price_history) < 5:
            return 0
        
        prices = list(self.price_history)
        early = mean(prices[:len(prices)//2])
        late = mean(prices[len(prices)//2:])
        
        if early == 0:
            return 0
        
        trend = (late - early) / early
        return max(-1, min(1, trend))  # Clamp to [-1, 1]
    
    def generate_signal(self, market_data: MarketData) -> Optional[Signal]:
        """Generate signal based on VPIN and price trend."""
        # Update price history
        self.price_history.append(market_data.price)
        
        # Update volume bucket (use spread as proxy for volume)
        volume_proxy = market_data.volume_24h / 288 if market_data.volume_24h > 0 else 100
        self.update_bucket(market_data.price, volume_proxy)
        
        # Calculate VPIN
        vpin = self.calculate_vpin()
        if vpin is None:
            return None
        
        # Store VPIN history
        self.vpin_history.append(vpin)
        
        # Calculate standardized VPIN (z-score)
        if len(self.vpin_history) >= 20:
            hist = list(self.vpin_history)
            vpin_mean = mean(hist)
            try:
                vpin_std = stdev(hist)
            except:
                vpin_std = 0.1
            
            if vpin_std > 0:
                vpin_zscore = (vpin - vpin_mean) / vpin_std
            else:
                vpin_zscore = 0
        else:
            vpin_zscore = 0
        
        # Generate signal when VPIN is elevated
        if vpin > self.vpin_threshold or vpin_zscore > 1.5:
            # High VPIN = informed trading detected
            # Follow the direction of recent price movement
            trend = self.get_price_trend()
            
            if trend > 0.01:  # Positive trend
                confidence = min(0.6 + vpin * 0.3 + abs(trend) * 5, 0.9)
                return Signal(
                    strategy=self.name,
                    signal="up",
                    confidence=confidence,
                    reason=f"High VPIN ({vpin:.2f}) with positive trend ({trend:.2%})",
                    metadata={
                        'vpin': vpin,
                        'vpin_zscore': vpin_zscore,
                        'trend': trend,
                        'threshold': self.vpin_threshold
                    }
                )
            elif trend < -0.01:  # Negative trend
                confidence = min(0.6 + vpin * 0.3 + abs(trend) * 5, 0.9)
                return Signal(
                    strategy=self.name,
                    signal="down",
                    confidence=confidence,
                    reason=f"High VPIN ({vpin:.2f}) with negative trend ({trend:.2%})",
                    metadata={
                        'vpin': vpin,
                        'vpin_zscore': vpin_zscore,
                        'trend': trend,
                        'threshold': self.vpin_threshold
                    }
                )
        
        return None
