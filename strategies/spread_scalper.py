"""
SpreadScalper Strategy

Captures the bid-ask spread by providing liquidity at favorable prices.
When spreads widen beyond normal levels, the strategy posts orders
near the mid price to capture spread profits as prices revert.

Key insight: Spreads in prediction markets fluctuate based on:
1. Volatility (wider in high vol)
2. Information flow (wider when news arrives)
3. Time to expiry (wider near expiry for uncertain outcomes)
4. Liquidity conditions

When spreads are abnormally wide, they tend to compress,
allowing market makers to capture the difference.

Reference: "Market Making in the Age of Prop Trading" - Lehalle & Laruelle
"High Frequency Market Making" - Avellaneda & Stoikov

Validation:
- No lookahead: Uses only current spread and historical averages
- No overfit: Based on market making theory
- Economic rationale: Spread compression is predictable mean reversion
"""

from typing import Optional
from collections import deque
from statistics import mean, stdev

from core.base_strategy import BaseStrategy, Signal, MarketData


class SpreadScalperStrategy(BaseStrategy):
    """
    Capture bid-ask spread through liquidity provision.
    
    Strategy logic:
    1. Monitor bid-ask spread relative to historical average
    2. Detect abnormally wide spreads (>1.5x average)
    3. Enter near mid price when spread is wide
    4. Profit as spread compresses back to normal
    
    This is essentially a market making strategy that captures
    the spread when it's temporarily inflated.
    """
    
    name = "SpreadScalper"
    description = "Capture bid-ask spread through liquidity provision"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        config = config or {}
        
        # Spread thresholds
        self.spread_history_len = self.config.get('spread_history_len', 30)
        self.wide_spread_multiplier = self.config.get('wide_spread_multiplier', 1.5)  # 1.5x avg
        self.extreme_spread_multiplier = self.config.get('extreme_spread_multiplier', 2.0)  # 2x avg
        
        # Minimum absolute spread (in bps)
        self.min_spread_bps = self.config.get('min_spread_bps', 20)  # 0.2%
        self.max_spread_bps = self.config.get('max_spread_bps', 200)  # 2% - avoid chaos
        
        # Spread tracking
        self.spread_history: deque = deque(maxlen=self.spread_history_len)
        self.price_history: deque = deque(maxlen=30)
        
        # Volatility tracking for context
        self.return_history: deque = deque(maxlen=20)
        
        # Signal requirements
        self.min_confidence = self.config.get('min_confidence', 0.60)
        
        # Cooldown
        self.cooldown_periods = self.config.get('cooldown_periods', 6)
        self.last_signal_period = -self.cooldown_periods
        self.period_count = 0
        
        # Consecutive signal tracking
        self.consecutive_signals = 0
        self.last_direction = None
    
    def calculate_spread_stats(self) -> tuple:
        """
        Calculate spread statistics.
        Returns: (avg_spread, std_spread, current_percentile)
        """
        if len(self.spread_history) < 10:
            return 50, 20, 0.5  # Default values
        
        spreads = list(self.spread_history)
        avg_spread = mean(spreads)
        
        try:
            std_spread = stdev(spreads)
        except:
            std_spread = 20
        
        # Calculate percentile of most recent spread
        current = spreads[-1]
        sorted_spreads = sorted(spreads)
        percentile = sum(1 for s in sorted_spreads if s < current) / len(sorted_spreads)
        
        return avg_spread, std_spread, percentile
    
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
        
        # Calculate spread in bps
        spread = data.ask - data.bid
        spread_bps = (spread / data.mid * 10000) if data.mid > 0 else 0
        
        # Update histories
        self.spread_history.append(spread_bps)
        self.price_history.append(current_price)
        
        if len(self.price_history) >= 2:
            prev_price = list(self.price_history)[-2]
            ret = (current_price - prev_price) / prev_price if prev_price > 0 else 0
            self.return_history.append(ret)
        
        # Check cooldown
        if self.period_count - self.last_signal_period < self.cooldown_periods:
            return None
        
        # Need enough spread history
        if len(self.spread_history) < 15:
            return None
        
        # Check spread bounds
        if spread_bps < self.min_spread_bps or spread_bps > self.max_spread_bps:
            return None
        
        # Calculate spread statistics
        avg_spread, std_spread, percentile = self.calculate_spread_stats()
        
        # Check if spread is abnormally wide
        spread_ratio = spread_bps / avg_spread if avg_spread > 0 else 1
        
        if spread_ratio < self.wide_spread_multiplier:
            return None  # Spread is normal
        
        # Calculate volatility context
        volatility = self.calculate_volatility()
        
        # Determine direction based on price position within spread
        # If price is closer to bid, market is leaning down - fade by buying
        # If price is closer to ask, market is leaning up - fade by selling
        
        bid_distance = (current_price - data.bid) / spread if spread > 0 else 0.5
        
        signal = None
        confidence = 0.0
        reason = ""
        
        if bid_distance < 0.4:
            # Price near bid = selling pressure
            # Spread scalping: buy near bid, profit when spread compresses
            signal = "up"
            base_conf = 0.60
            spread_boost = min((spread_ratio - self.wide_spread_multiplier) * 0.2, 0.15)
            vol_adjustment = max(0, 0.05 - volatility * 2)  # Lower conf in high vol
            confidence = base_conf + spread_boost + vol_adjustment
            reason = f"Wide spread ({spread_bps:.0f}bps, {spread_ratio:.1f}x avg), price near bid - capture spread"
        
        elif bid_distance > 0.6:
            # Price near ask = buying pressure
            # Spread scalping: sell near ask, profit when spread compresses
            signal = "down"
            base_conf = 0.60
            spread_boost = min((spread_ratio - self.wide_spread_multiplier) * 0.2, 0.15)
            vol_adjustment = max(0, 0.05 - volatility * 2)
            confidence = base_conf + spread_boost + vol_adjustment
            reason = f"Wide spread ({spread_bps:.0f}bps, {spread_ratio:.1f}x avg), price near ask - capture spread"
        
        # Extra boost for extreme spreads
        if spread_ratio > self.extreme_spread_multiplier and signal:
            confidence += 0.05
            reason += " [EXTREME SPREAD]"
        
        if signal and confidence >= self.min_confidence:
            # Track consecutive signals
            if signal == self.last_direction:
                self.consecutive_signals += 1
                # Boost confidence for consecutive signals
                confidence += min(self.consecutive_signals * 0.02, 0.05)
            else:
                self.consecutive_signals = 1
                self.last_direction = signal
            
            self.last_signal_period = self.period_count
            
            return Signal(
                strategy=self.name,
                signal=signal,
                confidence=min(confidence, 0.85),
                reason=reason,
                metadata={
                    'spread_bps': spread_bps,
                    'avg_spread': avg_spread,
                    'spread_ratio': spread_ratio,
                    'percentile': percentile,
                    'volatility': volatility,
                    'bid_distance': bid_distance
                }
            )
        
        return None
