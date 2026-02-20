"""
TimeDecayPositionStrategy - Reduce exposure as settlement approaches

Mathematical framework:
Position(t) = Initial_Position * √(T_remaining / T_initial)

Gamma increases as settlement approaches - reduce position to avoid terminal volatility.
Source: navnoorbawa.substack.com - Mathematical Execution Behind Prediction Market Alpha
"""

from typing import Optional, Dict
import numpy as np
import time
from core.base_strategy import BaseStrategy, Signal, MarketData


class TimeDecayPositionStrategy(BaseStrategy):
    """
    Dynamic position sizing based on time to settlement.
    
    As settlement approaches:
    - Gamma increases exponentially
    - Small probability shifts cause large price moves
    - Reduce position size to manage terminal risk
    """
    
    def __init__(self, 
                 window_minutes: float = 5.0,
                 min_position_pct: float = 0.2):
        super().__init__()
        self.name = "TimeDecayPosition"
        self.window_minutes = window_minutes
        self.min_position_pct = min_position_pct  # Minimum 20% position at end
        
    def get_time_remaining_pct(self, data: MarketData) -> float:
        """Get percentage of window remaining."""
        if not data.market_end_time:
            return 1.0
        
        now = time.time()
        total_window = self.window_minutes * 60
        elapsed = now - (data.market_end_time - total_window)
        remaining = max(0, total_window - elapsed)
        
        return remaining / total_window
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        """
        Generate signal with time-decay position sizing.
        
        Strategy: Enter early in window, exit or reduce as settlement approaches.
        """
        time_pct = self.get_time_remaining_pct(data)
        
        # Don't enter in last 20% of window
        if time_pct < 0.2:
            return None
        
        # Skip extreme prices
        if data.price < 0.02 or data.price > 0.98:
            return None
        
        # Calculate position scaling factor
        # Position(t) = Base * √(time_remaining)
        position_factor = np.sqrt(time_pct)
        
        # Early window: full position
        # Late window: reduced position
        if time_pct > 0.8:
            # Early - look for momentum
            if data.vwap and data.price > data.vwap * 1.02:
                signal_type = "up"
                confidence = 0.7 * position_factor
            elif data.vwap and data.price < data.vwap * 0.98:
                signal_type = "down"
                confidence = 0.7 * position_factor
            else:
                return None
        elif time_pct > 0.5:
            # Mid - follow trend
            if not self.price_history:
                return None
            
            price_change = (data.price - self.price_history[-1]) / self.price_history[-1] if self.price_history[-1] > 0 else 0
            
            if price_change > 0.01:
                signal_type = "up"
                confidence = 0.65 * position_factor
            elif price_change < -0.01:
                signal_type = "down"
                confidence = 0.65 * position_factor
            else:
                return None
        else:
            # Late - only high confidence
            if not data.order_book:
                return None
            
            spread = data.order_book.get('spread_bps', 0)
            if spread < 50:  # Tight spread = consensus
                return None
            
            # Trade the spread if wide
            best_bid = data.order_book.get('best_bid', data.price)
            best_ask = data.order_book.get('best_ask', data.price)
            
            if data.price - best_bid > best_ask - data.price:
                signal_type = "down"  # Closer to ask, sell
                confidence = 0.6 * position_factor
            else:
                signal_type = "up"  # Closer to bid, buy
                confidence = 0.6 * position_factor
        
        # Update price history
        self.price_history.append(data.price)
        if len(self.price_history) > 20:
            self.price_history.pop(0)
        
        if confidence < 0.5:
            return None
        
        return Signal(
            signal=signal_type,
            confidence=confidence,
            strategy=self.name,
            metadata={
                'time_remaining_pct': time_pct,
                'position_factor': position_factor
            }
        )
