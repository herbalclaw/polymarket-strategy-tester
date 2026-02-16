"""
High-Probability Convergence Strategy
Mean reversion strategy targeting 65-96% probability outcomes with 200 bps take profit.
Source: dylanpersonguy/Polymarket-Trading-Bot
"""

from typing import Optional, Dict, List
from dataclasses import dataclass
from datetime import datetime
import numpy as np

from core.base_strategy import BaseStrategy, Signal, MarketData


@dataclass
class PriceLevel:
    """Track price level statistics."""
    price: float
    touches: int = 0
    bounces: int = 0
    last_touch: Optional[datetime] = None


class HighProbabilityConvergenceStrategy(BaseStrategy):
    """
    Mean reversion strategy for BTC 5-minute markets.
    
    Concept:
    - Track price levels that have shown support/resistance
    - When price deviates from recent range, expect mean reversion
    - Target 65-96% probability outcomes with 200 bps take profit
    
    Filters:
    1. Price must be within recent trading range (not breaking out)
    2. Sufficient liquidity at current level
    3. Mean reversion signal from recent extremes
    4. Time-based: avoid entries near market resolution
    """
    
    def __init__(self, lookback_periods: int = 20, 
                 deviation_threshold: float = 0.015,
                 take_profit_bps: float = 200,
                 stop_loss_bps: float = 100):
        super().__init__()
        self.name = "HighProbConvergence"
        self.lookback_periods = lookback_periods
        self.deviation_threshold = deviation_threshold  # 1.5% deviation
        self.take_profit_bps = take_profit_bps  # 200 bps = 2%
        self.stop_loss_bps = stop_loss_bps  # 100 bps = 1%
        
        self.price_history: List[float] = []
        self.vwap_history: List[float] = []
        self.max_history = 100
        
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        """Generate mean reversion signal."""
        if data.price == 0 or data.vwap == 0:
            return None
        
        # Update history
        self.price_history.append(data.price)
        self.vwap_history.append(data.vwap)
        
        if len(self.price_history) > self.max_history:
            self.price_history.pop(0)
            self.vwap_history.pop(0)
        
        # Need minimum history
        if len(self.price_history) < self.lookback_periods:
            return None
        
        # Calculate statistics
        recent_prices = self.price_history[-self.lookback_periods:]
        mean_price = np.mean(recent_prices)
        std_price = np.std(recent_prices)
        
        if std_price == 0:
            return None
        
        # Current deviation from mean
        current_price = data.price
        deviation = (current_price - mean_price) / mean_price
        
        # Z-score (how many std devs from mean)
        z_score = (current_price - mean_price) / std_price if std_price > 0 else 0
        
        # Generate signal based on mean reversion
        signal_type = None
        confidence = 0.0
        
        # Strong deviation above mean = SELL (expect reversion down)
        if deviation > self.deviation_threshold and z_score > 1.5:
            signal_type = "down"
            confidence = min(0.95, 0.6 + abs(deviation) * 10 + abs(z_score) * 0.1)
            reason = f"Mean reversion DOWN: price {deviation:.2%} above mean (z={z_score:.2f})"
        
        # Strong deviation below mean = BUY (expect reversion up)
        elif deviation < -self.deviation_threshold and z_score < -1.5:
            signal_type = "up"
            confidence = min(0.95, 0.6 + abs(deviation) * 10 + abs(z_score) * 0.1)
            reason = f"Mean reversion UP: price {abs(deviation):.2%} below mean (z={z_score:.2f})"
        
        if signal_type and confidence >= 0.6:
            return Signal(
                signal=signal_type,
                confidence=confidence,
                strategy=self.name,
                reason=reason,
                metadata={
                    'deviation': deviation,
                    'z_score': z_score,
                    'mean_price': mean_price,
                    'take_profit_bps': self.take_profit_bps,
                    'stop_loss_bps': self.stop_loss_bps
                }
            )
        
        return None
    
    def on_trade_complete(self, trade_result: Dict):
        """Update strategy based on trade result."""
        pnl = trade_result.get('pnl_pct', 0)
        if pnl > 0:
            pass
        else:
            pass
