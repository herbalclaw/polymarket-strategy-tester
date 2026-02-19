"""
InformationDivergence Strategy

Exploits the divergence between market-implied probability and
statistically-estimated probability using Bayesian updating.

Key insight: Markets incorporate information at different speeds.
By tracking how quickly prices update to new information vs. statistical
estimates, we can identify when market prices lag behind true probabilities.

Uses Bayesian probability updating combined with price momentum to
estimate true probability faster than the market consensus.

Reference: "The Mathematical Execution Behind Prediction Market Alpha" - Bawa (2025)
"""

from typing import Optional, Tuple
from collections import deque
from statistics import mean, stdev
import math

from core.base_strategy import BaseStrategy, Signal, MarketData


class InformationDivergenceStrategy(BaseStrategy):
    """
    Exploits information divergence between market price and statistical estimate.
    
    Strategy logic:
    1. Estimate true probability using Bayesian updating on price history
    2. Compare estimate to current market price
    3. Trade when divergence exceeds threshold (market is "slow" to update)
    
    Key formula:
    P_posterior = (P_prior * Likelihood) / Evidence
    
    For prediction markets, we use price momentum as a proxy for
    information flow and update our probability estimate faster than
    the market consensus.
    """
    
    name = "InformationDivergence"
    description = "Exploit information divergence using Bayesian updating"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        config = config or {}
        
        # Bayesian updating parameters
        self.prior_weight = self.config.get('prior_weight', 0.6)  # Weight on prior
        self.likelihood_weight = self.config.get('likelihood_weight', 0.4)  # Weight on new data
        
        # Price history for estimation
        self.price_history: deque = deque(maxlen=100)
        self.return_history: deque = deque(maxlen=50)
        
        # Divergence thresholds
        self.min_divergence = self.config.get('min_divergence', 0.03)  # 3% divergence
        self.max_divergence = self.config.get('max_divergence', 0.20)  # Cap at 20%
        
        # Momentum parameters
        self.short_window = self.config.get('short_window', 5)
        self.long_window = self.config.get('long_window', 20)
        
        # Volatility regime
        self.volatility_lookback = self.config.get('volatility_lookback', 20)
        self.high_vol_threshold = self.config.get('high_vol_threshold', 0.02)
        
        # Confidence scaling
        self.confidence_base = self.config.get('confidence_base', 0.60)
        
        # Cooldown
        self.cooldown_periods = self.config.get('cooldown_periods', 8)
        self.last_signal_period = -self.cooldown_periods
        self.period_count = 0
        
        # Current probability estimate
        self.current_estimate = 0.5
        self.estimate_confidence = 0.5
    
    def calculate_volatility(self) -> float:
        """Calculate recent price volatility."""
        if len(self.return_history) < 10:
            return 0.01
        
        returns = list(self.return_history)[-self.volatility_lookback:]
        if len(returns) < 2:
            return 0.01
        
        try:
            return stdev(returns)
        except:
            return 0.01
    
    def update_probability_estimate(self, current_price: float) -> Tuple[float, float]:
        """
        Update probability estimate using Bayesian framework.
        
        Returns (P_estimate, confidence_in_estimate)
        """
        if len(self.price_history) < self.long_window:
            # Not enough data - use market price as estimate
            return current_price, 0.5
        
        prices = list(self.price_history)
        
        # Calculate momentum (short-term trend)
        short_ma = mean(prices[-self.short_window:])
        long_ma = mean(prices[-self.long_window:])
        
        if long_ma == 0:
            momentum = 0
        else:
            momentum = (short_ma - long_ma) / long_ma
        
        # Calculate trend strength (acceleration)
        if len(prices) >= self.long_window + 5:
            very_short = mean(prices[-3:])
            trend_accel = (very_short - short_ma) / short_ma if short_ma > 0 else 0
        else:
            trend_accel = 0
        
        # Volatility adjustment
        volatility = self.calculate_volatility()
        vol_factor = max(0.3, 1.0 - volatility * 20)  # Higher vol = lower confidence
        
        # Bayesian update
        # Prior: previous estimate
        prior = self.current_estimate
        
        # Likelihood: based on momentum and trend
        # Positive momentum suggests higher probability
        likelihood = prior + momentum * 0.5 + trend_accel * 0.3
        likelihood = max(0.05, min(0.95, likelihood))
        
        # Posterior: weighted combination
        posterior = (self.prior_weight * prior + 
                     self.likelihood_weight * likelihood +
                     (1 - self.prior_weight - self.likelihood_weight) * current_price)
        
        # Clamp to valid range
        posterior = max(0.05, min(0.95, posterior))
        
        # Confidence based on data quality
        confidence = vol_factor * min(1.0, len(prices) / self.long_window)
        confidence = max(0.3, min(0.9, confidence))
        
        # Update stored estimate
        self.current_estimate = posterior
        self.estimate_confidence = confidence
        
        return posterior, confidence
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_price = data.price
        self.period_count += 1
        
        # Update history
        self.price_history.append(current_price)
        
        # Calculate return
        if len(self.price_history) >= 2:
            prev_price = list(self.price_history)[-2]
            if prev_price > 0:
                ret = (current_price - prev_price) / prev_price
                self.return_history.append(ret)
        
        # Check cooldown
        if self.period_count - self.last_signal_period < self.cooldown_periods:
            return None
        
        # Need enough data
        if len(self.price_history) < self.long_window:
            return None
        
        # Update probability estimate
        p_estimate, estimate_conf = self.update_probability_estimate(current_price)
        
        # Market-implied probability is just the price
        p_market = current_price
        
        # Calculate divergence
        divergence = p_estimate - p_market
        
        # Check if divergence is significant
        if abs(divergence) < self.min_divergence:
            return None
        
        if abs(divergence) > self.max_divergence:
            # Divergence too large - likely model error or extreme event
            return None
        
        # Check volatility regime
        volatility = self.calculate_volatility()
        if volatility > self.high_vol_threshold:
            # High volatility - reduce confidence
            estimate_conf *= 0.8
        
        # Generate signal based on divergence direction
        signal = None
        confidence = 0.0
        reason = ""
        metadata = {}
        
        if divergence > 0:
            # Our estimate > market price = buy UP
            confidence = self.confidence_base + min(divergence * 2, 0.15)
            confidence *= estimate_conf  # Scale by estimate confidence
            confidence = min(confidence, 0.85)
            
            if confidence >= self.min_confidence:
                signal = "up"
                reason = f"Info divergence: estimate={p_estimate:.3f}, market={p_market:.3f}, div={divergence:.3f}"
                metadata = {
                    'p_estimate': p_estimate,
                    'p_market': p_market,
                    'divergence': divergence,
                    'estimate_conf': estimate_conf,
                    'volatility': volatility
                }
        
        elif divergence < 0:
            # Our estimate < market price = buy DOWN
            confidence = self.confidence_base + min(abs(divergence) * 2, 0.15)
            confidence *= estimate_conf
            confidence = min(confidence, 0.85)
            
            if confidence >= self.min_confidence:
                signal = "down"
                reason = f"Info divergence: estimate={p_estimate:.3f}, market={p_market:.3f}, div={divergence:.3f}"
                metadata = {
                    'p_estimate': p_estimate,
                    'p_market': p_market,
                    'divergence': divergence,
                    'estimate_conf': estimate_conf,
                    'volatility': volatility
                }
        
        if signal and confidence >= self.min_confidence:
            self.last_signal_period = self.period_count
            
            return Signal(
                strategy=self.name,
                signal=signal,
                confidence=confidence,
                reason=reason,
                metadata=metadata
            )
        
        return None
