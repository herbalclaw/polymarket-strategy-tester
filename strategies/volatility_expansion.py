"""
VolatilityExpansion Strategy

Exploits volatility clustering in short timeframes.
When Bollinger Bands expand after compression, the move tends to continue.

Key insight: Volatility is autocorrelated - high volatility periods
cluster together. After a period of low volatility (compression),
an expansion signals the start of a volatile period.

Reference: Bollinger Band Width (BBW) momentum
"""

from typing import Optional
from collections import deque
from statistics import mean, stdev

from core.base_strategy import BaseStrategy, Signal, MarketData


class VolatilityExpansionStrategy(BaseStrategy):
    """
    Trade volatility expansions after compression periods.
    
    When markets transition from low volatility to high volatility,
    the directional move tends to persist for several periods.
    This is especially true in 5-minute prediction markets where
    news and sentiment create momentum cascades.
    """
    
    name = "VolatilityExpansion"
    description = "Trade volatility expansion after compression"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        
        # Price history for Bollinger Bands
        self.price_history: deque = deque(maxlen=50)
        
        # BBW history
        self.bbw_history: deque = deque(maxlen=30)
        
        # Bollinger Band parameters
        self.bb_period = self.config.get('bb_period', 20)
        self.bb_std = self.config.get('bb_std', 2.0)
        
        # Expansion detection
        self.compression_threshold = self.config.get('compression_threshold', 0.05)  # 5% of price
        self.expansion_threshold = self.config.get('expansion_threshold', 1.25)  # 25% expansion
        
        # Minimum compression periods before expansion
        self.min_compression_periods = self.config.get('min_compression_periods', 5)
        
        # Momentum confirmation
        self.use_momentum = self.config.get('use_momentum', True)
        self.momentum_threshold = self.config.get('momentum_threshold', 0.001)  # 0.1%
        
        # Cooldown
        self.cooldown_periods = self.config.get('cooldown_periods', 5)
        self.last_signal_period = -self.cooldown_periods
        self.period_count = 0
        
        # Track compression state
        self.compression_periods = 0
        self.in_compression = False
    
    def calculate_bollinger_bands(self, prices: list) -> tuple:
        """Calculate Bollinger Bands."""
        if len(prices) < self.bb_period:
            return None, None, None
        
        recent = list(prices)[-self.bb_period:]
        sma = mean(recent)
        std_dev = stdev(recent) if len(recent) > 1 else 0
        
        upper = sma + (self.bb_std * std_dev)
        lower = sma - (self.bb_std * std_dev)
        
        return upper, sma, lower
    
    def calculate_bbw(self, upper: float, lower: float, mid: float) -> float:
        """Calculate Bollinger Band Width as percentage."""
        if mid == 0:
            return 0
        return (upper - lower) / mid
    
    def get_momentum(self) -> float:
        """Calculate recent price momentum."""
        if len(self.price_history) < 5:
            return 0
        
        prices = list(self.price_history)
        recent = prices[-3:]
        earlier = prices[-8:-3]
        
        if not earlier:
            return 0
        
        recent_avg = mean(recent)
        earlier_avg = mean(earlier)
        
        if earlier_avg == 0:
            return 0
        
        return (recent_avg - earlier_avg) / earlier_avg
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_price = data.price
        self.period_count += 1
        
        # Update history
        self.price_history.append(current_price)
        
        # Check cooldown
        if self.period_count - self.last_signal_period < self.cooldown_periods:
            return None
        
        # Need enough data
        if len(self.price_history) < self.bb_period:
            return None
        
        # Calculate Bollinger Bands
        upper, mid, lower = self.calculate_bollinger_bands(self.price_history)
        if upper is None:
            return None
        
        # Calculate BBW
        bbw = self.calculate_bbw(upper, lower, mid)
        self.bbw_history.append(bbw)
        
        # Need BBW history
        if len(self.bbw_history) < self.min_compression_periods + 3:
            return None
        
        # Get recent BBW values
        bbw_list = list(self.bbw_history)
        recent_bbw = bbw_list[-1]
        avg_bbw = mean(bbw_list[-self.min_compression_periods:])
        
        # Detect compression (low volatility period)
        is_compressed = recent_bbw < avg_bbw * 0.8 and recent_bbw < self.compression_threshold
        
        if is_compressed:
            self.compression_periods += 1
            self.in_compression = True
        else:
            # Check for expansion after compression
            if self.in_compression and self.compression_periods >= self.min_compression_periods:
                expansion_ratio = recent_bbw / avg_bbw if avg_bbw > 0 else 0
                
                if expansion_ratio > self.expansion_threshold:
                    # Volatility expansion detected!
                    momentum = self.get_momentum()
                    
                    # Determine direction based on price position and momentum
                    if self.use_momentum and abs(momentum) < self.momentum_threshold:
                        # Not enough momentum, skip
                        self.in_compression = False
                        self.compression_periods = 0
                        return None
                    
                    # Price above mid + positive momentum = UP
                    if current_price > mid and momentum >= 0:
                        confidence = min(0.65 + (expansion_ratio - 1) * 0.2, 0.85)
                        self.last_signal_period = self.period_count
                        self.in_compression = False
                        self.compression_periods = 0
                        
                        return Signal(
                            strategy=self.name,
                            signal="up",
                            confidence=confidence,
                            reason=f"Volatility expansion {expansion_ratio:.2f}x after {self.compression_periods} periods compression",
                            metadata={
                                'bbw': recent_bbw,
                                'avg_bbw': avg_bbw,
                                'expansion_ratio': expansion_ratio,
                                'momentum': momentum,
                                'compression_periods': self.compression_periods,
                                'bb_upper': upper,
                                'bb_lower': lower
                            }
                        )
                    
                    # Price below mid + negative momentum = DOWN
                    elif current_price < mid and momentum <= 0:
                        confidence = min(0.65 + (expansion_ratio - 1) * 0.2, 0.85)
                        self.last_signal_period = self.period_count
                        self.in_compression = False
                        self.compression_periods = 0
                        
                        return Signal(
                            strategy=self.name,
                            signal="down",
                            confidence=confidence,
                            reason=f"Volatility expansion {expansion_ratio:.2f}x after {self.compression_periods} periods compression",
                            metadata={
                                'bbw': recent_bbw,
                                'avg_bbw': avg_bbw,
                                'expansion_ratio': expansion_ratio,
                                'momentum': momentum,
                                'compression_periods': self.compression_periods,
                                'bb_upper': upper,
                                'bb_lower': lower
                            }
                        )
            
            # Reset compression tracking
            self.in_compression = False
            self.compression_periods = 0
        
        return None
