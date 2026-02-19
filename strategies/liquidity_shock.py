"""
Liquidity Shock Fade Strategy

Detects and fades liquidity shocks - sudden price movements caused by
large order execution rather than fundamental information.

Key insight: In prediction markets, large market orders create temporary
price dislocations that revert once the order flow imbalance subsides.
This is the "transient volatility" effect documented in market microstructure.

Reference: "Market Microstructure in Practice" - Lehalle & Laruelle
"""

from typing import Optional
from collections import deque
from statistics import mean, stdev

from core.base_strategy import BaseStrategy, Signal, MarketData


class LiquidityShockStrategy(BaseStrategy):
    """
    Fade liquidity shocks caused by large order flow.
    
    Detects sudden price moves that are likely temporary (high volume,
    rapid price change) and trades the expected reversion.
    """
    
    name = "LiquidityShock"
    description = "Fade liquidity shocks and temporary dislocations"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        config = config or {}
        
        # Price and volume history
        self.price_history: deque = deque(maxlen=100)
        self.volume_history: deque = deque(maxlen=100)
        
        # Shock detection parameters
        self.shock_threshold = self.config.get('shock_threshold', 0.015)  # 1.5% move
        self.volatility_multiplier = self.config.get('volatility_multiplier', 2.0)  # 2x normal vol
        
        # Reversion confirmation
        self.confirmation_periods = self.config.get('confirmation_periods', 2)
        self.post_shock_prices: deque = deque(maxlen=10)
        
        # Shock state tracking
        self.shock_detected = False
        self.shock_direction = None  # 'up' or 'down'
        self.shock_price = 0.0
        self.shock_time = 0
        
        # Cooldown
        self.cooldown_periods = self.config.get('cooldown_periods', 5)
        self.last_signal_period = -self.cooldown_periods
        self.period_count = 0
        
    def calculate_volatility(self, window: int = 20) -> float:
        """Calculate recent price volatility (std dev of returns)."""
        if len(self.price_history) < window + 1:
            return 0.01  # Default 1%
        
        prices = list(self.price_history)[-window-1:]
        returns = []
        
        for i in range(1, len(prices)):
            if prices[i-1] > 0:
                ret = abs((prices[i] - prices[i-1]) / prices[i-1])
                returns.append(ret)
        
        if len(returns) < 3:
            return 0.01
        
        try:
            return stdev(returns)
        except:
            return 0.01
    
    def detect_shock(self, current_price: float) -> Optional[dict]:
        """
        Detect if current price represents a liquidity shock.
        
        Returns shock info or None.
        """
        if len(self.price_history) < 5:
            return None
        
        # Get baseline price (average of recent prices)
        baseline_prices = list(self.price_history)[-5:]
        baseline = mean(baseline_prices)
        
        if baseline == 0:
            return None
        
        # Calculate price change from baseline
        price_change = (current_price - baseline) / baseline
        
        # Calculate normal volatility
        normal_vol = self.calculate_volatility()
        
        # Shock conditions:
        # 1. Price move exceeds threshold
        # 2. Price move exceeds normal volatility by multiplier
        
        is_shock = abs(price_change) > self.shock_threshold and \
                   abs(price_change) > normal_vol * self.volatility_multiplier
        
        if not is_shock:
            return None
        
        return {
            'direction': 'up' if price_change > 0 else 'down',
            'magnitude': abs(price_change),
            'baseline': baseline,
            'current': current_price,
            'normal_vol': normal_vol
        }
    
    def check_reversion(self, shock_info: dict) -> Optional[str]:
        """
        Check if price is reverting after shock.
        
        Returns signal direction or None if no clear reversion.
        """
        if len(self.post_shock_prices) < self.confirmation_periods:
            return None
        
        recent_prices = list(self.post_shock_prices)
        
        # Check if price is moving back toward baseline
        shock_price = shock_info['current']
        baseline = shock_info['baseline']
        current = recent_prices[-1]
        
        # Calculate progress toward reversion
        if shock_info['direction'] == 'up':
            # Shock was up - look for price moving down
            if current < shock_price:
                # Price is falling - confirm reversion
                return 'down'
        else:
            # Shock was down - look for price moving up
            if current > shock_price:
                # Price is rising - confirm reversion
                return 'up'
        
        return None
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_price = data.price
        current_time = data.timestamp
        
        self.period_count += 1
        
        # Check cooldown
        if self.period_count - self.last_signal_period < self.cooldown_periods:
            # Still in cooldown - update history but don't generate signals
            self.price_history.append(current_price)
            return None
        
        # If we detected a shock, track post-shock prices
        if self.shock_detected:
            self.post_shock_prices.append(current_price)
            
            # Check for reversion confirmation
            shock_info = {
                'direction': self.shock_direction,
                'current': self.shock_price,
                'baseline': self.shock_price * (1.01 if self.shock_direction == 'down' else 0.99)
            }
            
            reversion = self.check_reversion(shock_info)
            
            if reversion:
                # Generate fade signal
                self.shock_detected = False
                self.post_shock_prices.clear()
                self.last_signal_period = self.period_count
                
                confidence = min(0.65 + len(self.post_shock_prices) * 0.03, 0.85)
                
                return Signal(
                    strategy=self.name,
                    signal=reversion,
                    confidence=confidence,
                    reason=f"Liquidity shock fade: {self.shock_direction} shock at {self.shock_price:.3f}, fading",
                    metadata={
                        'shock_direction': self.shock_direction,
                        'shock_price': self.shock_price,
                        'reversion_price': current_price,
                        'confirmation_periods': len(self.post_shock_prices)
                    }
                )
            
            # Reset if shock is too old (10 periods)
            if self.period_count - self.shock_time > 10:
                self.shock_detected = False
                self.post_shock_prices.clear()
        
        # Store price
        self.price_history.append(current_price)
        
        # Detect new shock
        shock = self.detect_shock(current_price)
        
        if shock:
            self.shock_detected = True
            self.shock_direction = shock['direction']
            self.shock_price = current_price
            self.shock_time = self.period_count
            self.post_shock_prices.clear()
            # Don't generate signal yet - wait for reversion confirmation
        
        return None
