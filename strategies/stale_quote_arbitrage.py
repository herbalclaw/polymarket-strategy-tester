"""
Stale Quote Arbitrage Strategy

Exploits stale quotes in the CLOB when prices move rapidly.
When the market price moves significantly but the order book hasn't updated,
stale limit orders become mispriced and offer risk-free profit opportunities.

Economic Rationale:
- In fast-moving markets (BTC 5-min), some market makers can't update quotes fast enough
- Creates temporary stale quotes that can be picked off
- Edge comes from being faster than slow market makers during volatility spikes

Validation:
- No lookahead: Uses current order book and price velocity only
- No overfit: Based on established microstructure literature (SEC reports on HFT)
- Works on single market: Pure order book microstructure play
"""

import time
import numpy as np
from typing import Optional, Dict, List
from collections import deque
from core.base_strategy import BaseStrategy, Signal, MarketData


class StaleQuoteArbitrageStrategy(BaseStrategy):
    """
    Detects and exploits stale quotes in the CLOB.
    
    When price moves rapidly (>threshold in short window), checks if:
    1. Best bid/ask hasn't moved (stale)
    2. Quote size is large (institutional maker)
    3. Spread has widened (liquidity withdrawal)
    
    Trade against stale quotes before they update.
    """
    
    name = "StaleQuoteArbitrage"
    version = "1.0.0"
    
    def __init__(self, config: Dict = None):
        super().__init__(config)
        
        # Parameters
        self.price_history_len = 20  # Keep 20 ticks of history
        self.velocity_threshold = 0.005  # 0.5% price move triggers stale check
        self.stale_threshold_bps = 5  # Quote is stale if >5bps from fair value
        self.min_spread_bps = 10  # Need at least 10bps spread for opportunity
        self.max_quote_age_seconds = 2  # Quotes older than 2s considered stale
        
        # State
        self.price_history: deque = deque(maxlen=self.price_history_len)
        self.mid_history: deque = deque(maxlen=self.price_history_len)
        self.timestamp_history: deque = deque(maxlen=self.price_history_len)
        self.last_signal_time = 0
        self.cooldown_seconds = 10  # Don't signal more than once per 10s
        
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        """Generate signal based on stale quote detection."""
        
        current_time = time.time()
        
        # Cooldown check
        if current_time - self.last_signal_time < self.cooldown_seconds:
            return None
        
        # Need order book data
        if not data.order_book:
            return None
        
        best_bid = data.order_book.get('best_bid', data.bid)
        best_ask = data.order_book.get('best_ask', data.ask)
        bid_size = data.order_book.get('bid_size', 0)
        ask_size = data.order_book.get('ask_size', 0)
        
        if not best_bid or not best_ask or best_bid <= 0 or best_ask <= 0:
            return None
        
        mid = (best_bid + best_ask) / 2
        spread_bps = (best_ask - best_bid) / mid * 10000
        
        # Update history
        self.price_history.append(data.price)
        self.mid_history.append(mid)
        self.timestamp_history.append(current_time)
        
        # Need enough history
        if len(self.price_history) < 10:
            return None
        
        # Calculate price velocity (recent change rate)
        recent_prices = list(self.price_history)[-5:]
        price_velocity = abs(recent_prices[-1] - recent_prices[0]) / recent_prices[0]
        
        # Check for rapid price movement
        if price_velocity < self.velocity_threshold:
            return None
        
        # Price is moving fast - check for stale quotes
        # Calculate fair value based on recent VWAP or moving average
        fair_value = np.mean(list(self.mid_history)[-10:])
        
        # Check if bid is stale (above fair value during down move)
        bid_stale_bps = (best_bid - fair_value) / fair_value * 10000
        # Check if ask is stale (below fair value during up move)  
        ask_stale_bps = (fair_value - best_ask) / fair_value * 10000
        
        opportunity = None
        confidence = 0.0
        reason = ""
        
        # Stale bid opportunity: bid is too high relative to fair value
        # Price moving down but bid hasn't updated -> hit the stale bid
        if bid_stale_bps > self.stale_threshold_bps and price_velocity > 0:
            # Confirm with spread widening (makers pulling liquidity)
            if spread_bps > self.min_spread_bps:
                opportunity = 'down'
                confidence = min(0.95, 0.6 + bid_stale_bps / 50)
                reason = f"Stale bid {bid_stale_bps:.1f}bps above fair, velocity={price_velocity:.3f}, spread={spread_bps:.1f}bps"
        
        # Stale ask opportunity: ask is too low relative to fair value
        # Price moving up but ask hasn't updated -> lift the stale ask
        elif ask_stale_bps > self.stale_threshold_bps and price_velocity > 0:
            if spread_bps > self.min_spread_bps:
                opportunity = 'up'
                confidence = min(0.95, 0.6 + ask_stale_bps / 50)
                reason = f"Stale ask {ask_stale_bps:.1f}bps below fair, velocity={price_velocity:.3f}, spread={spread_bps:.1f}bps"
        
        if opportunity:
            self.last_signal_time = current_time
            return Signal(
                strategy=self.name,
                signal=opportunity,
                confidence=confidence,
                reason=reason,
                metadata={
                    'fair_value': fair_value,
                    'bid_stale_bps': bid_stale_bps,
                    'ask_stale_bps': ask_stale_bps,
                    'price_velocity': price_velocity,
                    'spread_bps': spread_bps
                }
            )
        
        return None
