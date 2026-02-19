"""
Serial Correlation Mean Reversion Strategy

Based on the observation that short-term price movements in prediction markets
exhibit negative serial correlation due to microstructure effects and noise
trader activity.

Key insight: After a price move in one direction, the next move tends to
revert (negative autocorrelation), especially in short timeframes where
noise trading dominates.

Reference: "Short-Term Trading and Stock Return Reversals" - Nagel (2012)
"""

from typing import Optional
from collections import deque
from statistics import mean

from core.base_strategy import BaseStrategy, Signal, MarketData


class SerialCorrelationStrategy(BaseStrategy):
    """
    Trade mean reversion based on serial correlation of returns.
    
    When returns show negative autocorrelation (typical in microstructure),
    a positive return predicts a negative next return, and vice versa.
    """
    
    name = "SerialCorrelation"
    description = "Mean reversion based on serial correlation"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        
        # Return history
        self.return_history: deque = deque(maxlen=50)
        self.price_history: deque = deque(maxlen=50)
        
        # Correlation window
        self.corr_window = self.config.get('corr_window', 10)
        
        # Minimum correlation magnitude to trade
        self.min_correlation = self.config.get('min_correlation', -0.3)
        
        # Recent return threshold
        self.return_threshold = self.config.get('return_threshold', 0.005)  # 0.5%
        
        # Cooldown
        self.cooldown_periods = self.config.get('cooldown_periods', 3)
        self.last_signal_period = -self.cooldown_periods
        self.period_count = 0
        
    def calculate_returns(self) -> list:
        """Calculate price returns from history."""
        if len(self.price_history) < 2:
            return []
        
        prices = list(self.price_history)
        returns = []
        
        for i in range(1, len(prices)):
            if prices[i-1] > 0:
                ret = (prices[i] - prices[i-1]) / prices[i-1]
                returns.append(ret)
        
        return returns
    
    def calculate_autocorrelation(self, lag: int = 1) -> float:
        """
        Calculate autocorrelation of returns at given lag.
        
        Returns correlation coefficient (-1 to 1).
        Negative = mean reverting
        Positive = trending
        """
        returns = self.calculate_returns()
        
        if len(returns) < self.corr_window + lag:
            return 0.0
        
        recent_returns = returns[-self.corr_window-lag:]
        
        # Create pairs: return[t] vs return[t+lag]
        x = recent_returns[:-lag]
        y = recent_returns[lag:]
        
        if len(x) != len(y) or len(x) < 3:
            return 0.0
        
        # Calculate correlation
        mean_x = mean(x)
        mean_y = mean(y)
        
        numerator = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
        denom_x = sum((xi - mean_x) ** 2 for xi in x) ** 0.5
        denom_y = sum((yi - mean_y) ** 2 for yi in y) ** 0.5
        
        if denom_x == 0 or denom_y == 0:
            return 0.0
        
        return numerator / (denom_x * denom_y)
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_price = data.price
        
        # Store price
        self.price_history.append(current_price)
        self.period_count += 1
        
        # Check cooldown
        if self.period_count - self.last_signal_period < self.cooldown_periods:
            return None
        
        # Need enough history
        if len(self.price_history) < self.corr_window + 5:
            return None
        
        # Calculate returns and autocorrelation
        returns = self.calculate_returns()
        if len(returns) < 2:
            return None
        
        autocorr = self.calculate_autocorrelation(lag=1)
        
        # Only trade if we see negative autocorrelation (mean reversion)
        if autocorr > self.min_correlation:
            return None
        
        # Get most recent return
        last_return = returns[-1]
        
        # Need significant recent move to fade
        if abs(last_return) < self.return_threshold:
            return None
        
        # Generate mean reversion signal
        # If last return was positive, expect negative next (fade up)
        # If last return was negative, expect positive next (fade down)
        
        if last_return > 0:
            signal = "down"
            confidence = min(0.6 + abs(autocorr) * 0.3 + abs(last_return) * 10, 0.85)
            reason = f"Serial corr: Fade +{last_return:.2%} return (autocorr: {autocorr:.2f})"
        else:
            signal = "up"
            confidence = min(0.6 + abs(autocorr) * 0.3 + abs(last_return) * 10, 0.85)
            reason = f"Serial corr: Fade {last_return:.2%} return (autocorr: {autocorr:.2f})"
        
        self.last_signal_period = self.period_count
        
        return Signal(
            strategy=self.name,
            signal=signal,
            confidence=confidence,
            reason=reason,
            metadata={
                'autocorrelation': autocorr,
                'last_return': last_return,
                'current_price': current_price,
                'corr_window': self.corr_window
            }
        )
