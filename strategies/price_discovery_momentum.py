"""
PriceDiscoveryMomentum Strategy

Exploits the price discovery process in prediction markets.
When new information arrives, prices don't adjust instantly -
they trend toward the new fair value over time, creating
momentum that can be captured.

Key insight: Prediction markets exhibit post-information drift
similar to post-earnings drift in stocks. Prices continue moving
in the direction of the information release as participants
gradually update their beliefs.

Reference: "Price Discovery and Trading in Prediction Markets" - various
"Market Microstructure of Prediction Markets" - Wolfers & Zitzewitz

Validation:
- No lookahead: Uses only past price movements
- No overfit: Based on information diffusion theory
- Economic rationale: Slow information diffusion creates momentum
"""

from typing import Optional
from collections import deque
from statistics import mean, stdev

from core.base_strategy import BaseStrategy, Signal, MarketData


class PriceDiscoveryMomentumStrategy(BaseStrategy):
    """
    Capture momentum from gradual price discovery.
    
    Strategy logic:
    1. Detect significant price moves (>1% in short window)
    2. Measure follow-through in subsequent periods
    3. If price continues in same direction, momentum confirmed
    4. Enter in direction of momentum
    5. Exit when momentum decays or reverses
    
    This captures the information diffusion process where
    prices trend toward new equilibrium after shocks.
    """
    
    name = "PriceDiscoveryMomentum"
    description = "Capture momentum from gradual price discovery"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        config = config or {}
        
        # Initial move detection
        self.initial_move_threshold = self.config.get('initial_move_threshold', 0.008)  # 0.8%
        self.initial_window = self.config.get('initial_window', 5)  # periods
        
        # Follow-through requirements
        self.follow_through_threshold = self.config.get('follow_through_threshold', 0.003)  # 0.3%
        self.follow_window = self.config.get('follow_window', 3)  # periods
        
        # Minimum momentum strength
        self.min_momentum_strength = self.config.get('min_momentum_strength', 0.5)
        
        # History tracking
        self.price_history: deque = deque(maxlen=50)
        self.return_history: deque = deque(maxlen=30)
        
        # Signal requirements
        self.min_confidence = self.config.get('min_confidence', 0.60)
        
        # Cooldown
        self.cooldown_periods = self.config.get('cooldown_periods', 8)
        self.last_signal_period = -self.cooldown_periods
        self.period_count = 0
        
        # Track detected moves
        self.pending_move: Optional[dict] = None
        self.pending_start_period = 0
    
    def calculate_momentum_strength(self, returns: list) -> float:
        """
        Calculate momentum strength from returns.
        Higher = more consistent direction
        """
        if not returns:
            return 0
        
        # Count positive vs negative returns
        positive = sum(1 for r in returns if r > 0)
        negative = sum(1 for r in returns if r < 0)
        total = len(returns)
        
        if total == 0:
            return 0
        
        # Strength = max(positive, negative) / total
        return max(positive, negative) / total
    
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
        if len(self.price_history) < self.initial_window + self.follow_window:
            return None
        
        # Check for pending move waiting for follow-through
        if self.pending_move is not None:
            periods_since = self.period_count - self.pending_start_period
            
            if periods_since >= self.follow_window:
                # Check follow-through
                prices = list(self.price_history)
                move_start_price = self.pending_move['start_price']
                current = prices[-1]
                
                if self.pending_move['direction'] == 'up':
                    # Check if price continued up
                    follow_return = (current - move_start_price) / move_start_price
                    if follow_return > self.follow_through_threshold:
                        # Momentum confirmed
                        returns_since = list(self.return_history)[-periods_since:]
                        strength = self.calculate_momentum_strength(returns_since)
                        
                        if strength >= self.min_momentum_strength:
                            self.last_signal_period = self.period_count
                            self.pending_move = None
                            
                            confidence = min(0.60 + strength * 0.2 + follow_return * 10, 0.85)
                            
                            return Signal(
                                strategy=self.name,
                                signal='up',
                                confidence=confidence,
                                reason=f"Momentum confirmed: {follow_return:.2%} follow-through, {strength:.0%} consistency",
                                metadata={
                                    'initial_move': self.pending_move['initial_return'],
                                    'follow_through': follow_return,
                                    'momentum_strength': strength,
                                    'periods': periods_since
                                }
                            )
                
                else:  # direction == 'down'
                    # Check if price continued down
                    follow_return = (move_start_price - current) / move_start_price
                    if follow_return > self.follow_through_threshold:
                        # Momentum confirmed
                        returns_since = list(self.return_history)[-periods_since:]
                        strength = self.calculate_momentum_strength(returns_since)
                        
                        if strength >= self.min_momentum_strength:
                            self.last_signal_period = self.period_count
                            self.pending_move = None
                            
                            confidence = min(0.60 + strength * 0.2 + follow_return * 10, 0.85)
                            
                            return Signal(
                                strategy=self.name,
                                signal='down',
                                confidence=confidence,
                                reason=f"Momentum confirmed: {follow_return:.2%} follow-through, {strength:.0%} consistency",
                                metadata={
                                    'initial_move': self.pending_move['initial_return'],
                                    'follow_through': follow_return,
                                    'momentum_strength': strength,
                                    'periods': periods_since
                                }
                            )
                
                # No follow-through, reset
                self.pending_move = None
        
        # Look for new initial move
        prices = list(self.price_history)
        recent_prices = prices[-self.initial_window:]
        
        if len(recent_prices) < 2:
            return None
        
        start_price = recent_prices[0]
        end_price = recent_prices[-1]
        
        if start_price == 0:
            return None
        
        total_return = (end_price - start_price) / start_price
        
        # Check for significant move
        if abs(total_return) >= self.initial_move_threshold:
            # Calculate consistency of move
            returns = []
            for i in range(1, len(recent_prices)):
                r = (recent_prices[i] - recent_prices[i-1]) / recent_prices[i-1]
                returns.append(r)
            
            strength = self.calculate_momentum_strength(returns)
            
            # Set pending move
            direction = 'up' if total_return > 0 else 'down'
            self.pending_move = {
                'direction': direction,
                'start_price': end_price,  # Current price is new baseline
                'initial_return': abs(total_return),
                'strength': strength
            }
            self.pending_start_period = self.period_count
        
        return None
