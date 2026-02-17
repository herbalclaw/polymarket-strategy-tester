from typing import Optional, Dict, List
from collections import deque
import statistics

from core.base_strategy import BaseStrategy, Signal, MarketData


class CrossMarketArbitrageStrategy(BaseStrategy):
    """
    Cross-Market Arbitrage (Dependent Markets)
    
    Based on "Unravelling the Probabilistic Forest" research.
    Exploits mispricing across related markets on same platform.
    
    For BTC 5-min markets: We look for price discrepancies
    between consecutive time windows and strike prices.
    
    Edge: Markets don't always price dependent events consistently
    Method: Find probability mismatches in related outcomes
    """
    
    name = "CrossMarketArbitrage"
    description = "Exploit mispricing across related market outcomes"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        # Track multiple market windows
        self.window_prices: Dict[int, deque] = {}  # window -> price history
        self.strike_prices: Dict[float, float] = {}  # strike -> current price
        
        self.min_discrepancy = self.config.get('min_discrepancy', 0.03)  # 3%
        self.lookback_windows = self.config.get('lookback_windows', 3)
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        # Get current window from metadata or calculate
        current_time = data.timestamp
        current_window = int(current_time // 300) * 300
        
        # Store price for this window
        if current_window not in self.window_prices:
            self.window_prices[current_window] = deque(maxlen=20)
        
        self.window_prices[current_window].append(data.price)
        
        # Need multiple windows
        if len(self.window_prices) < 2:
            return None
        
        # Get recent windows
        sorted_windows = sorted(self.window_prices.keys())
        recent_windows = sorted_windows[-self.lookback_windows:]
        
        if len(recent_windows) < 2:
            return None
        
        # Calculate median prices for each window
        window_medians = {}
        for window in recent_windows:
            prices = list(self.window_prices[window])
            if len(prices) >= 3:
                window_medians[window] = statistics.median(prices)
        
        if len(window_medians) < 2:
            return None
        
        # Find discrepancies between consecutive windows
        sorted_medians = sorted(window_medians.items())
        max_discrepancy = 0
        discrepancy_direction = None
        
        for i in range(1, len(sorted_medians)):
            prev_window, prev_price = sorted_medians[i-1]
            curr_window, curr_price = sorted_medians[i]
            
            # Price change between windows
            change = abs(curr_price - prev_price)
            
            if change > max_discrepancy:
                max_discrepancy = change
                discrepancy_direction = "up" if curr_price > prev_price else "down"
        
        if max_discrepancy < self.min_discrepancy:
            return None
        
        # Signal based on discrepancy
        # If big jump up, expect continuation or mean reversion
        # Let's bet on continuation (momentum)
        confidence = min(0.5 + max_discrepancy * 10, 0.80)
        
        return Signal(
            strategy=self.name,
            signal=discrepancy_direction,
            confidence=confidence,
            reason=f"Cross-market arb: {max_discrepancy:.2%} discrepancy across {len(window_medians)} windows",
            metadata={
                'discrepancy': max_discrepancy,
                'windows': len(window_medians),
                'direction': discrepancy_direction
            }
        )
