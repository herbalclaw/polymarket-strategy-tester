from typing import Optional, Dict, List
from collections import deque
import statistics
import time

from core.base_strategy import BaseStrategy, Signal, MarketData


class KalshiArbitrageStrategy(BaseStrategy):
    """
    Inter-Exchange Arbitrage: Polymarket vs Kalshi
    
    Academic research shows price discrepancies between prediction
    market platforms lasting seconds to minutes.
    
    Edge: Same event priced differently across platforms
    Method: Buy low on one platform, sell high on other
    
    Research: "Price Discovery and Trading in Prediction Markets"
    Note: For BTC 5-min markets, we simulate cross-platform arb
          by looking for price discrepancies within Polymarket's
          order book (bid/ask spread exploitation)
    
    Adapted for single-market: Exploit bid-ask inefficiencies
    """
    
    name = "KalshiArbitrage"
    description = "Cross-platform arbitrage adapted for order book edges"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        # Minimum spread to capture
        self.min_spread_bps = self.config.get('min_spread_bps', 50)  # 0.5%
        self.max_spread_bps = self.config.get('max_spread_bps', 300)  # 3%
        
        # Price history for detecting discrepancies
        self.price_history: deque = deque(maxlen=30)
        self.bid_history: deque = deque(maxlen=30)
        self.ask_history: deque = deque(maxlen=30)
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_price = data.price
        bid = data.bid
        ask = data.ask
        
        if bid == 0 or ask == 0:
            return None
        
        # Calculate spread in basis points
        spread = (ask - bid) / current_price * 10000  # bps
        
        # Store history
        self.price_history.append(current_price)
        self.bid_history.append(bid)
        self.ask_history.append(ask)
        
        # Need history
        if len(self.price_history) < 5:
            return None
        
        # Strategy 1: Wide spread = buy at bid, sell at ask
        if spread > self.min_spread_bps and spread < self.max_spread_bps:
            # Check if price is trending to determine direction
            recent_prices = list(self.price_history)[-5:]
            price_trend = (recent_prices[-1] - recent_prices[0]) / recent_prices[0] * 100
            
            if price_trend > 0.1:  # Slight uptrend
                # Buy YES at bid (expect to sell higher)
                return Signal(
                    strategy=self.name,
                    signal="up",
                    confidence=min(0.5 + spread / 500, 0.75),
                    reason=f"Arb spread: {spread:.0f} bps, trend {price_trend:.2f}%",
                    metadata={
                        'spread_bps': spread,
                        'bid': bid,
                        'ask': ask,
                        'trend': price_trend
                    }
                )
            elif price_trend < -0.1:  # Slight downtrend
                # Buy NO at ask (expect to sell lower)
                return Signal(
                    strategy=self.name,
                    signal="down",
                    confidence=min(0.5 + spread / 500, 0.75),
                    reason=f"Arb spread: {spread:.0f} bps, trend {price_trend:.2f}%",
                    metadata={
                        'spread_bps': spread,
                        'bid': bid,
                        'ask': ask,
                        'trend': price_trend
                    }
                )
        
        # Strategy 2: Price discrepancy from recent median
        if len(self.price_history) >= 10:
            median_price = statistics.median(list(self.price_history)[-10:])
            deviation = (current_price - median_price) / median_price * 100
            
            # If price deviates significantly, expect reversion
            if abs(deviation) > 1.0:  # 1% deviation
                if deviation > 0:
                    # Price too high, expect down
                    return Signal(
                        strategy=self.name,
                        signal="down",
                        confidence=min(0.55 + abs(deviation) / 10, 0.80),
                        reason=f"Price arb: {deviation:.2f}% above median",
                        metadata={
                            'median': median_price,
                            'current': current_price,
                            'deviation': deviation
                        }
                    )
                else:
                    # Price too low, expect up
                    return Signal(
                        strategy=self.name,
                        signal="up",
                        confidence=min(0.55 + abs(deviation) / 10, 0.80),
                        reason=f"Price arb: {deviation:.2f}% below median",
                        metadata={
                            'median': median_price,
                            'current': current_price,
                            'deviation': deviation
                        }
                    )
        
        return None
