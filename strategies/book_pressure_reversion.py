"""
BookPressureReversion Strategy

Exploits the natural reversion of prices after extreme order book pressure.
When one side of the book becomes heavily imbalanced (e.g., 3:1 bid:ask ratio),
the price often overextends and reverts as the imbalance normalizes.

Key insight: Extreme book pressure often precedes short-term mean reversion
because:
1. Large orders get filled and pressure dissipates
2. Market makers widen spreads to protect against adverse selection
3. The imbalance itself may indicate temporary order flow distortion

Reference: "High Frequency Trading and Limit Order Book Dynamics" - Cont et al.
"Order Book Dynamics and Price Discovery" - Gould et al.

Validation:
- No lookahead: Uses only current order book state
- No overfit: Based on market microstructure theory
- Economic rationale: Order book imbalances are mean-reverting
"""

from typing import Optional
from collections import deque
from statistics import mean, stdev

from core.base_strategy import BaseStrategy, Signal, MarketData


class BookPressureReversionStrategy(BaseStrategy):
    """
    Trade mean reversion after extreme order book pressure.
    
    Strategy logic:
    1. Monitor order book imbalance (bid volume vs ask volume)
    2. Detect extreme imbalances (>70% on one side)
    3. Wait for price to move in direction of imbalance (confirmation)
    4. Fade the move - enter counter-trend position
    5. Profit as imbalance normalizes and price reverts
    
    This is a counter-trend strategy that exploits temporary
    distortions in order flow.
    """
    
    name = "BookPressureReversion"
    description = "Exploit mean reversion after extreme book pressure"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        config = config or {}
        
        # Imbalance thresholds
        self.extreme_imbalance = self.config.get('extreme_imbalance', 0.70)  # 70% on one side
        self.moderate_imbalance = self.config.get('moderate_imbalance', 0.60)  # 60% on one side
        
        # Price confirmation - need move in direction of imbalance
        self.confirmation_threshold = self.config.get('confirmation_threshold', 0.003)  # 0.3%
        
        # Book depth to consider
        self.book_levels = self.config.get('book_levels', 5)
        
        # History tracking
        self.imbalance_history: deque = deque(maxlen=20)
        self.price_history: deque = deque(maxlen=30)
        self.return_history: deque = deque(maxlen=20)
        
        # Signal requirements
        self.min_confidence = self.config.get('min_confidence', 0.60)
        
        # Cooldown
        self.cooldown_periods = self.config.get('cooldown_periods', 10)
        self.last_signal_period = -self.cooldown_periods
        self.period_count = 0
        
        # Volatility filter
        self.max_volatility = self.config.get('max_volatility', 0.02)  # 2% max
    
    def calculate_book_imbalance(self, data: MarketData) -> float:
        """
        Calculate order book imbalance.
        Returns: -1 (all ask) to 1 (all bid)
        """
        if not data.order_book:
            return 0
        
        bids = data.order_book.get('bids', [])
        asks = data.order_book.get('asks', [])
        
        if not bids or not asks:
            return 0
        
        # Sum volume at top N levels
        bid_vol = sum(float(b.get('size', 0)) for b in bids[:self.book_levels])
        ask_vol = sum(float(a.get('size', 0)) for a in asks[:self.book_levels])
        
        total = bid_vol + ask_vol
        if total == 0:
            return 0
        
        return (bid_vol - ask_vol) / total
    
    def calculate_volatility(self) -> float:
        """Calculate recent price volatility."""
        if len(self.return_history) < 10:
            return 0.01
        
        returns = list(self.return_history)[-10:]
        try:
            return stdev(returns)
        except:
            return 0.01
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_price = data.price
        self.period_count += 1
        
        # Update history
        self.price_history.append(current_price)
        
        if len(self.price_history) >= 2:
            prev_price = list(self.price_history)[-2]
            ret = (current_price - prev_price) / prev_price if prev_price > 0 else 0
            self.return_history.append(ret)
        
        # Check cooldown
        if self.period_count - self.last_signal_period < self.cooldown_periods:
            return None
        
        # Need enough data
        if len(self.price_history) < 10:
            return None
        
        # Calculate current imbalance
        imbalance = self.calculate_book_imbalance(data)
        self.imbalance_history.append(imbalance)
        
        # Volatility check - avoid high vol periods
        volatility = self.calculate_volatility()
        if volatility > self.max_volatility:
            return None
        
        # Check for extreme imbalance
        is_extreme_buy_pressure = imbalance > self.extreme_imbalance
        is_extreme_sell_pressure = imbalance < -self.extreme_imbalance
        
        if not (is_extreme_buy_pressure or is_extreme_sell_pressure):
            return None
        
        # Calculate recent price change to confirm move direction
        prices = list(self.price_history)
        price_change = (prices[-1] - prices[-5]) / prices[-5] if len(prices) >= 5 and prices[-5] > 0 else 0
        
        signal = None
        confidence = 0.0
        reason = ""
        
        if is_extreme_buy_pressure:
            # Heavy bid pressure - price should have moved up
            # We fade it by selling
            if price_change > self.confirmation_threshold:
                signal = "down"
                base_conf = 0.62
                # Higher imbalance = higher confidence
                imb_boost = min((imbalance - self.extreme_imbalance) * 0.3, 0.15)
                # Larger move = higher confidence
                move_boost = min(price_change * 50, 0.1)
                confidence = base_conf + imb_boost + move_boost
                reason = f"Extreme bid pressure ({imbalance:.2%}) with {price_change:.2%} price rise - fade"
        
        elif is_extreme_sell_pressure:
            # Heavy ask pressure - price should have moved down
            # We fade it by buying
            if price_change < -self.confirmation_threshold:
                signal = "up"
                base_conf = 0.62
                # Higher imbalance = higher confidence
                imb_boost = min((abs(imbalance) - self.extreme_imbalance) * 0.3, 0.15)
                # Larger move = higher confidence
                move_boost = min(abs(price_change) * 50, 0.1)
                confidence = base_conf + imb_boost + move_boost
                reason = f"Extreme ask pressure ({abs(imbalance):.2%}) with {abs(price_change):.2%} price drop - fade"
        
        if signal and confidence >= self.min_confidence:
            self.last_signal_period = self.period_count
            
            return Signal(
                strategy=self.name,
                signal=signal,
                confidence=min(confidence, 0.85),
                reason=reason,
                metadata={
                    'imbalance': imbalance,
                    'price_change': price_change,
                    'volatility': volatility,
                    'book_levels': self.book_levels
                }
            )
        
        return None
