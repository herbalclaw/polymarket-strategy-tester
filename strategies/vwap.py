from typing import Optional

from core.base_strategy import BaseStrategy, Signal, MarketData


class VWAPStrategy(BaseStrategy):
    """
    VWAP Deviation Strategy
    
    Mean reversion strategy that bets on price returning to VWAP.
    Buys when price is below VWAP, sells when above.
    """
    
    name = "vwap"
    description = "Mean reversion to Volume Weighted Average Price"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        self.deviation_threshold = self.config.get('deviation_threshold', 0.1)
        self.max_deviation = self.config.get('max_deviation', 1.0)
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_price = data.price
        vwap = data.vwap
        
        if vwap == 0:
            return None
        
        deviation = (current_price - vwap) / vwap * 100
        
        # Only trade if deviation is significant but not extreme
        if abs(deviation) < self.deviation_threshold:
            return None
        
        if abs(deviation) > self.max_deviation:
            return None
        
        if deviation > 0:
            return Signal(
                strategy=self.name,
                signal="down",
                confidence=min(abs(deviation) * 5, 0.85),
                reason=f"Price {deviation:.3f}% above VWAP, expecting reversion",
                metadata={
                    'deviation_pct': deviation,
                    'vwap': vwap,
                    'current_price': current_price
                }
            )
        else:
            return Signal(
                strategy=self.name,
                signal="up",
                confidence=min(abs(deviation) * 5, 0.85),
                reason=f"Price {abs(deviation):.3f}% below VWAP, expecting reversion",
                metadata={
                    'deviation_pct': deviation,
                    'vwap': vwap,
                    'current_price': current_price
                }
            )
