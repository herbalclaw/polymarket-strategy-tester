"""
BidAskBounce Strategy

Exploits the natural oscillation of prices between bid and ask levels
in a central limit order book (CLOB). Prices tend to bounce between
support (bid cluster) and resistance (ask cluster) levels, creating
predictable short-term patterns.

Key insight: In prediction markets with 1-cent tick sizes, prices often
oscillate within a narrow range. By identifying when price hits
extreme bid or ask levels, we can predict the bounce direction.

Reference: "High Frequency Trading" - Aldridge (2013)
"""

from typing import Optional
from collections import deque
import statistics

from core.base_strategy import BaseStrategy, Signal, MarketData


class BidAskBounceStrategy(BaseStrategy):
    """
    Trade bid-ask bounces in CLOB markets.
    
    Strategy logic:
    1. Track recent price range (highs and lows)
    2. Identify when price touches bid extreme (support) -> bounce up
    3. Identify when price touches ask extreme (resistance) -> bounce down
    4. Confirm with micro-momentum before entering
    
    Works best in range-bound markets typical of 5-min prediction markets.
    """
    
    name = "BidAskBounce"
    description = "Trade bid-ask level bounces in CLOB"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        
        # Price history
        self.price_history = deque(maxlen=30)
        self.bid_history = deque(maxlen=20)
        self.ask_history = deque(maxlen=20)
        
        # Range tracking
        self.lookback_periods = self.config.get('lookback_periods', 15)
        self.range_percentile = self.config.get('range_percentile', 0.15)  # Bottom/top 15%
        
        # Bounce confirmation
        self.bounce_threshold = self.config.get('bounce_threshold', 0.002)  # 0.2% move
        self.confirmation_periods = self.config.get('confirmation_periods', 2)
        
        # Spread filter
        self.max_spread = self.config.get('max_spread', 0.015)  # 1.5 cents max
        
        # Cooldown
        self.last_signal_time = 0
        self.cooldown_seconds = self.config.get('cooldown_seconds', 60)
        
        # Recent bounce tracking
        self.recent_bounce = None
        self.bounce_confirm_count = 0
    
    def get_price_percentile(self, current: float, is_high: bool = False) -> float:
        """
        Calculate where current price sits in recent range.
        Returns 0.0 (at bottom) to 1.0 (at top).
        """
        if len(self.price_history) < self.lookback_periods:
            return 0.5
        
        prices = list(self.price_history)[-self.lookback_periods:]
        
        if not prices:
            return 0.5
        
        low = min(prices)
        high = max(prices)
        
        if high == low:
            return 0.5
        
        percentile = (current - low) / (high - low)
        return percentile
    
    def detect_bounce_setup(self, data: MarketData) -> tuple:
        """
        Detect if price is at a bounce setup level.
        Returns (setup_type, strength) where setup_type is 'bid_support', 
        'ask_resistance', or None.
        """
        if len(self.price_history) < self.lookback_periods:
            return None, 0.0
        
        current_price = data.price
        percentile = self.get_price_percentile(current_price)
        
        # Check spread
        spread = data.ask - data.bid if data.ask > data.bid else 0
        if spread > self.max_spread:
            return None, 0.0
        
        # Near bottom of range - potential bounce up from bid support
        if percentile < self.range_percentile:
            # Check if we're near the bid level
            distance_from_bid = (current_price - data.bid) / data.bid if data.bid > 0 else 1
            if distance_from_bid < 0.005:  # Within 0.5% of bid
                strength = 1.0 - (percentile / self.range_percentile)  # Higher at extremes
                return "bid_support", strength
        
        # Near top of range - potential bounce down from ask resistance
        if percentile > (1 - self.range_percentile):
            # Check if we're near the ask level
            distance_from_ask = (data.ask - current_price) / data.ask if data.ask > 0 else 1
            if distance_from_ask < 0.005:  # Within 0.5% of ask
                strength = (percentile - (1 - self.range_percentile)) / self.range_percentile
                return "ask_resistance", strength
        
        return None, 0.0
    
    def confirm_bounce(self, setup_type: str) -> tuple:
        """
        Confirm that a bounce is actually occurring.
        Returns (confirmed, strength)
        """
        if len(self.price_history) < self.confirmation_periods + 1:
            return False, 0.0
        
        prices = list(self.price_history)
        recent = prices[-(self.confirmation_periods + 1):]
        
        if setup_type == "bid_support":
            # Looking for upward move after touching support
            if len(recent) >= 2:
                change = (recent[-1] - recent[0]) / recent[0] if recent[0] > 0 else 0
                if change > self.bounce_threshold:
                    return True, min(change * 100, 1.0)  # Cap at 1.0
        
        elif setup_type == "ask_resistance":
            # Looking for downward move after touching resistance
            if len(recent) >= 2:
                change = (recent[-1] - recent[0]) / recent[0] if recent[0] > 0 else 0
                if change < -self.bounce_threshold:
                    return True, min(abs(change) * 100, 1.0)
        
        return False, 0.0
    
    def calculate_micro_momentum(self) -> float:
        """Calculate very short-term momentum (last 3 periods)."""
        if len(self.price_history) < 3:
            return 0.0
        
        prices = list(self.price_history)[-3:]
        if prices[0] == 0:
            return 0.0
        
        return (prices[-1] - prices[0]) / prices[0]
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_time = data.timestamp
        
        # Cooldown check
        if current_time - self.last_signal_time < self.cooldown_seconds:
            return None
        
        # Update history
        self.price_history.append(data.price)
        self.bid_history.append(data.bid)
        self.ask_history.append(data.ask)
        
        # Need enough data
        if len(self.price_history) < self.lookback_periods:
            return None
        
        # Detect bounce setup
        setup_type, setup_strength = self.detect_bounce_setup(data)
        
        if setup_type:
            # Track this setup
            if self.recent_bounce == setup_type:
                self.bounce_confirm_count += 1
            else:
                self.recent_bounce = setup_type
                self.bounce_confirm_count = 1
            
            # Check for confirmation
            confirmed, confirm_strength = self.confirm_bounce(setup_type)
            
            if confirmed and self.bounce_confirm_count >= self.confirmation_periods:
                micro_momentum = self.calculate_micro_momentum()
                
                if setup_type == "bid_support":
                    # Bounce up from bid support
                    # Confirm momentum is positive
                    if micro_momentum > 0:
                        base_confidence = 0.60
                        setup_boost = setup_strength * 0.10
                        confirm_boost = confirm_strength * 0.08
                        
                        confidence = min(base_confidence + setup_boost + confirm_boost, 0.80)
                        
                        if confidence >= self.min_confidence:
                            self.last_signal_time = current_time
                            self.recent_bounce = None
                            self.bounce_confirm_count = 0
                            
                            return Signal(
                                strategy=self.name,
                                signal="up",
                                confidence=confidence,
                                reason=f"Bid support bounce: {setup_strength:.2f} strength, momentum={micro_momentum:.3f}",
                                metadata={
                                    'setup_type': setup_type,
                                    'setup_strength': setup_strength,
                                    'confirm_strength': confirm_strength,
                                    'percentile': self.get_price_percentile(data.price),
                                    'micro_momentum': micro_momentum
                                }
                            )
                
                elif setup_type == "ask_resistance":
                    # Bounce down from ask resistance
                    # Confirm momentum is negative
                    if micro_momentum < 0:
                        base_confidence = 0.60
                        setup_boost = setup_strength * 0.10
                        confirm_boost = confirm_strength * 0.08
                        
                        confidence = min(base_confidence + setup_boost + confirm_boost, 0.80)
                        
                        if confidence >= self.min_confidence:
                            self.last_signal_time = current_time
                            self.recent_bounce = None
                            self.bounce_confirm_count = 0
                            
                            return Signal(
                                strategy=self.name,
                                signal="down",
                                confidence=confidence,
                                reason=f"Ask resistance bounce: {setup_strength:.2f} strength, momentum={micro_momentum:.3f}",
                                metadata={
                                    'setup_type': setup_type,
                                    'setup_strength': setup_strength,
                                    'confirm_strength': confirm_strength,
                                    'percentile': self.get_price_percentile(data.price),
                                    'micro_momentum': micro_momentum
                                }
                            )
        else:
            # Reset if no setup
            self.recent_bounce = None
            self.bounce_confirm_count = 0
        
        return None
