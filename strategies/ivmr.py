"""
Implied Volatility Mean Reversion Strategy

For BTC 5-minute prediction markets, "volatility" manifests as
price variance within the 5-minute window. This strategy tracks
implied volatility (price dispersion) and trades mean reversion
when volatility exceeds historical norms.

Key insight: In short-term prediction markets, extreme price
swings within the window often revert as noise traders exit.

Reference: Market microstructure research on short-term mean reversion
"""

from typing import Optional
from collections import deque
import statistics
import math

from core.base_strategy import BaseStrategy, Signal, MarketData


class IVMRStrategy(BaseStrategy):
    """
    Implied Volatility Mean Reversion (IVMR) Strategy.
    
    Tracks price volatility within the current 5-minute window
    and trades mean reversion when volatility is elevated.
    
    Logic:
    1. Calculate rolling volatility (std dev of recent prices)
    2. Compare to historical average volatility
    3. When current vol > 1.5x avg vol, expect mean reversion
    4. Trade toward the VWAP/mean when volatility spikes
    """
    
    name = "IVMR"
    description = "Implied Volatility Mean Reversion"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        config = config or {}
        
        # Volatility calculation window
        self.vol_window = self.config.get('vol_window', 10)
        self.price_history = deque(maxlen=self.vol_window)
        
        # Historical volatility tracking
        self.vol_history = deque(maxlen=50)
        
        # Volatility spike threshold (multiple of average)
        self.spike_threshold = self.config.get('spike_threshold', 1.5)
        
        # Mean reversion threshold (how far from mean to trigger)
        self.reversion_threshold = self.config.get('reversion_threshold', 0.02)  # 2%
        
        # Minimum volatility for signal (avoid noise)
        self.min_volatility = self.config.get('min_volatility', 0.005)  # 0.5%
        
        # Current window tracking
        self.current_window = None
        self.window_prices = []
    
    def calculate_volatility(self, prices: list) -> float:
        """Calculate coefficient of variation (volatility)."""
        if len(prices) < 2:
            return 0.0
        try:
            mean_price = statistics.mean(prices)
            if mean_price == 0:
                return 0.0
            std = statistics.stdev(prices)
            return std / mean_price
        except:
            return 0.0
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        price = data.price
        
        # Track window
        window = int(data.timestamp // 300) * 300
        if window != self.current_window:
            # New window - store previous volatility and reset
            if self.window_prices and len(self.window_prices) >= 5:
                window_vol = self.calculate_volatility(self.window_prices)
                if window_vol > 0:
                    self.vol_history.append(window_vol)
            self.current_window = window
            self.window_prices = []
        
        # Store price
        self.price_history.append(price)
        self.window_prices.append(price)
        
        # Need enough data
        if len(self.price_history) < self.vol_window // 2:
            return None
        
        # Calculate current volatility
        current_vol = self.calculate_volatility(list(self.price_history))
        
        # Need historical context
        if len(self.vol_history) < 10:
            return None
        
        # Calculate average historical volatility
        avg_vol = statistics.mean(self.vol_history)
        
        # Check for volatility spike
        vol_ratio = current_vol / avg_vol if avg_vol > 0 else 0
        
        if vol_ratio < self.spike_threshold or current_vol < self.min_volatility:
            return None
        
        # Calculate mean and deviation
        prices = list(self.price_history)
        mean_price = statistics.mean(prices)
        
        deviation = (price - mean_price) / mean_price if mean_price > 0 else 0
        
        signal = None
        confidence = 0.0
        reason = ""
        
        # Mean reversion logic: trade back toward mean
        if deviation > self.reversion_threshold:
            # Price above mean, expect reversion down
            confidence = min(0.6 + vol_ratio * 0.1 + abs(deviation) * 2, 0.85)
            signal = "down"
            reason = f"IVMR: vol spike {vol_ratio:.1f}x, dev {deviation*100:.1f}%, mean reversion down"
        
        elif deviation < -self.reversion_threshold:
            # Price below mean, expect reversion up
            confidence = min(0.6 + vol_ratio * 0.1 + abs(deviation) * 2, 0.85)
            signal = "up"
            reason = f"IVMR: vol spike {vol_ratio:.1f}x, dev {abs(deviation)*100:.1f}%, mean reversion up"
        
        if signal and confidence >= self.min_confidence:
            return Signal(
                strategy=self.name,
                signal=signal,
                confidence=confidence,
                reason=reason,
                metadata={
                    'price': price,
                    'mean_price': mean_price,
                    'deviation': deviation,
                    'current_vol': current_vol,
                    'avg_vol': avg_vol,
                    'vol_ratio': vol_ratio,
                    'vol_window': len(prices)
                }
            )
        
        return None
