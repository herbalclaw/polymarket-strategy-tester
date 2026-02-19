"""
Volatility Clustering Strategy

Exploits volatility clustering in BTC 5-minute markets.
Based on GARCH-family models: high volatility periods tend to be followed by high volatility.
Uses realized volatility estimates to predict future volatility and trade accordingly.

Economic Rationale:
- Financial time series exhibit volatility clustering (Mandelbrot, 1963)
- BTC is particularly prone to volatility clustering due to news-driven moves
- In prediction markets, high volatility = higher chance of large price swings
- Trade in direction of volatility expansion after compression

Validation:
- No lookahead: Uses past returns only to estimate future volatility
- No overfit: Based on established financial econometrics (GARCH)
- Works on single market: Pure time-series pattern
"""

import time
import numpy as np
from typing import Optional, Dict, List
from collections import deque
from core.base_strategy import BaseStrategy, Signal, MarketData


class VolatilityClusteringStrategy(BaseStrategy):
    """
    Trades volatility clustering patterns in BTC 5-min markets.
    
    Strategy:
    1. Calculate realized volatility from recent returns
    2. Detect volatility regime changes (compression -> expansion)
    3. Trade in direction of the volatility expansion
    4. Use volatility forecast to size confidence
    
    Key insight: Volatility clusters - a large move predicts more large moves.
    """
    
    name = "VolatilityClustering"
    version = "1.0.0"
    
    def __init__(self, config: Dict = None):
        super().__init__(config)
        
        # Parameters
        self.short_window = 5  # Short-term volatility window
        self.long_window = 20  # Long-term volatility baseline
        self.return_history_len = 50  # Keep 50 returns
        
        self.vol_compression_threshold = 0.6  # Vol < 60% of avg = compression
        self.vol_expansion_threshold = 1.5  # Vol > 150% of avg = expansion
        self.min_vol_percentile = 30  # Need at least 30th percentile vol to trade
        
        self.cooldown_seconds = 60  # One trade per minute max
        
        # State
        self.price_history: deque = deque(maxlen=self.return_history_len + 10)
        self.returns: deque = deque(maxlen=self.return_history_len)
        self.volatility_history: deque = deque(maxlen=self.return_history_len)
        self.last_signal_time = 0
        self.last_regime = 'normal'  # 'low', 'normal', 'high'
        
    def _calculate_realized_volatility(self, returns: List[float], window: int) -> float:
        """Calculate annualized realized volatility."""
        if len(returns) < window:
            return 0.0
        
        recent_returns = list(returns)[-window:]
        # Annualized volatility (assuming 5-min bars, 288 bars/day, 252 trading days)
        # For 5-min: sqrt(288 * 252) ≈ 269.5
        ann_factor = 269.5
        
        vol = np.std(recent_returns) * ann_factor
        return vol
    
    def _detect_volatility_regime(self, short_vol: float, long_vol: float) -> str:
        """Detect current volatility regime."""
        if long_vol == 0:
            return 'normal'
        
        ratio = short_vol / long_vol
        
        if ratio < self.vol_compression_threshold:
            return 'low'
        elif ratio > self.vol_expansion_threshold:
            return 'high'
        return 'normal'
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        """Generate signal based on volatility clustering."""
        
        current_time = time.time()
        
        # Cooldown
        if current_time - self.last_signal_time < self.cooldown_seconds:
            return None
        
        # Update price history
        self.price_history.append(data.price)
        
        # Need enough prices
        if len(self.price_history) < 2:
            return None
        
        # Calculate return
        prices = list(self.price_history)
        ret = (prices[-1] - prices[-2]) / prices[-2] if prices[-2] != 0 else 0
        self.returns.append(ret)
        
        # Need enough returns
        if len(self.returns) < self.long_window:
            return None
        
        # Calculate volatilities
        short_vol = self._calculate_realized_volatility(list(self.returns), self.short_window)
        long_vol = self._calculate_realized_volatility(list(self.returns), self.long_window)
        
        self.volatility_history.append(short_vol)
        
        # Detect regime
        current_regime = self._detect_volatility_regime(short_vol, long_vol)
        
        # Trade on regime transitions
        signal = None
        confidence = 0.0
        reason = ""
        
        # Transition: Compression -> Expansion (breakout coming)
        if self.last_regime == 'low' and current_regime == 'high':
            # Volatility is expanding - trade in direction of recent move
            recent_returns = list(self.returns)[-5:]
            avg_return = np.mean(recent_returns)
            
            if abs(avg_return) > 0.001:  # Need some directional bias
                direction = 'up' if avg_return > 0 else 'down'
                confidence = min(0.9, 0.65 + short_vol / long_vol * 0.1)
                reason = f"Vol expansion: {short_vol/long_vol:.2f}x, recent return {avg_return:.4f}"
                signal = direction
        
        # Transition: Normal -> High (momentum continuation)
        elif self.last_regime == 'normal' and current_regime == 'high':
            recent_returns = list(self.returns)[-3:]
            avg_return = np.mean(recent_returns)
            
            if abs(avg_return) > 0.0005:
                direction = 'up' if avg_return > 0 else 'down'
                confidence = min(0.85, 0.6 + abs(avg_return) * 100)
                reason = f"High vol regime, momentum {avg_return:.4f}"
                signal = direction
        
        # Update regime
        self.last_regime = current_regime
        
        if signal:
            self.last_signal_time = current_time
            return Signal(
                strategy=self.name,
                signal=signal,
                confidence=confidence,
                reason=reason,
                metadata={
                    'short_vol': short_vol,
                    'long_vol': long_vol,
                    'vol_ratio': short_vol / long_vol if long_vol > 0 else 0,
                    'regime': current_regime,
                    'recent_return': avg_return if 'avg_return' in dir() else 0
                }
            )
        
        return None
