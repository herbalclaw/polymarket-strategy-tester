from typing import Optional
from collections import deque

from core.base_strategy import BaseStrategy, Signal, MarketData


class LeadLagStrategy(BaseStrategy):
    """
    Cross-Exchange Lead/Lag Strategy
    
    Detects which exchange moves first and follows it.
    Front-runs based on leading exchange's price action.
    """
    
    name = "leadlag"
    description = "Follow the exchange that moves first"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        config = config or {}
        self.price_history: deque = deque(maxlen=self.config.get('history_size', 20))
        self.min_move_pct = self.config.get('min_move_pct', 0.02)  # Reduced from 0.05
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        if not data.exchange_prices:
            return None
        
        # Store current prices
        current_prices = {
            name: ep['price'] 
            for name, ep in data.exchange_prices.items()
        }
        
        self.price_history.append(current_prices)
        
        if len(self.price_history) < 2:
            return None
        
        # Compare current to previous
        prev_prices = self.price_history[-2]  # Look back 2 samples (was 3)
        
        max_change = 0
        leading_exchange = None
        leading_direction = None
        
        for exchange, current_price in current_prices.items():
            if exchange in prev_prices:
                prev_price = prev_prices[exchange]
                change = (current_price - prev_price) / prev_price * 100
                
                if abs(change) > abs(max_change):
                    max_change = change
                    leading_exchange = exchange
                    leading_direction = "up" if change > 0 else "down"
        
        if abs(max_change) > self.min_move_pct and leading_exchange:
            return Signal(
                strategy=self.name,
                signal=leading_direction,
                confidence=min(abs(max_change) * 10, 0.75),
                reason=f"{leading_exchange} leading with {max_change:.3f}% move",
                metadata={
                    'leading_exchange': leading_exchange,
                    'move_pct': max_change,
                    'lookback_samples': 3
                }
            )
        
        return None
