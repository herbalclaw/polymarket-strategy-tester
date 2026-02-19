"""
KellyCriterionStrategy

Implements Kelly criterion for optimal position sizing in binary options.
Based on the mathematical framework for event contract trading.

Key insight: Kelly's formula determines optimal bet fraction maximizing
long-run capital growth: f* = (P_true - P_market) / (1 - P_market)

For prediction markets with binary settlement, edge comes from estimating
P_true more accurately than crowd consensus.

Reference: Kelly (1956) - "A New Interpretation of Information Rate"
Applied to prediction markets in Bawa (2025) - "Mathematical Execution Behind Prediction Market Alpha"
"""

from typing import Optional
from collections import deque
from statistics import mean, stdev

from core.base_strategy import BaseStrategy, Signal, MarketData


class KellyCriterionStrategy(BaseStrategy):
    """
    Kelly criterion-based strategy for binary prediction markets.
    
    Uses Bayesian probability estimation combined with market price
to calculate expected edge. Only enters when Kelly fraction
    suggests positive expected value with sufficient margin.
    
    Key formula:
    f* = (P_model - P_market) / (1 - P_market)
    
    Where:
    - P_model = estimated true probability from price momentum
    - P_market = current market price (implied probability)
    - f* = optimal fraction of capital to bet
    
    Uses fractional Kelly (25%) for robustness against model error.
    """
    
    name = "KellyCriterion"
    description = "Kelly criterion optimal sizing for binary options"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        config = config or {}
        
        # Price history for probability estimation
        self.price_history: deque = deque(maxlen=100)
        self.returns_history: deque = deque(maxlen=50)
        
        # Kelly parameters
        self.kelly_fraction = self.config.get('kelly_fraction', 0.25)  # Conservative: 25% of full Kelly
        self.min_edge = self.config.get('min_edge', 0.03)  # Minimum 3% edge required
        self.max_edge = self.config.get('max_edge', 0.20)  # Cap edge at 20% (avoid overconfidence)
        
        # Probability estimation
        self.lookback_periods = self.config.get('lookback_periods', 20)
        self.momentum_weight = self.config.get('momentum_weight', 0.3)
        
        # Market regime detection
        self.volatility_lookback = self.config.get('volatility_lookback', 20)
        self.trend_lookback = self.config.get('trend_lookback', 10)
        
        # Signal thresholds
        self.min_kelly_fraction = self.config.get('min_kelly_fraction', 0.05)  # Need at least 5% Kelly
        
        # Cooldown
        self.cooldown_periods = self.config.get('cooldown_periods', 10)
        self.last_signal_period = -self.cooldown_periods
        self.period_count = 0
        
        # Confidence calibration
        self.confidence_scaling = self.config.get('confidence_scaling', 5.0)  # Scale edge to confidence
    
    def estimate_true_probability(self, current_price: float) -> tuple:
        """
        Estimate true probability using price momentum and trend.
        
        Returns (P_up, P_down, confidence_in_estimate)
        """
        if len(self.price_history) < self.lookback_periods:
            # Not enough data - assume market is efficient
            return current_price, 1 - current_price, 0.5
        
        prices = list(self.price_history)
        
        # Calculate momentum
        if len(prices) >= 5:
            short_ma = mean(prices[-5:])
            long_ma = mean(prices[-self.lookback_periods:])
            momentum = (short_ma - long_ma) / long_ma if long_ma > 0 else 0
        else:
            momentum = 0
        
        # Calculate trend
        if len(prices) >= self.trend_lookback:
            early = mean(prices[-self.trend_lookback:-self.trend_lookback//2])
            late = mean(prices[-self.trend_lookback//2:])
            trend = (late - early) / early if early > 0 else 0
        else:
            trend = 0
        
        # Calculate volatility
        if len(self.returns_history) >= 10:
            returns = list(self.returns_history)[-self.volatility_lookback:]
            if len(returns) > 1:
                try:
                    volatility = stdev(returns)
                except:
                    volatility = 0.01
            else:
                volatility = 0.01
        else:
            volatility = 0.01
        
        # Combine signals for probability adjustment
        # Base: current market price (efficient market baseline)
        base_prob = current_price
        
        # Adjust based on momentum and trend
        # Momentum suggests continuation
        momentum_adjustment = momentum * self.momentum_weight
        
        # Trend confirmation
        trend_adjustment = trend * 0.2
        
        # Volatility reduces confidence (higher vol = less certain)
        confidence = max(0.3, 1.0 - volatility * 10)
        
        # Calculate adjusted probability
        adjusted_prob = base_prob + momentum_adjustment + trend_adjustment
        
        # Clamp to valid probability range
        adjusted_prob = max(0.05, min(0.95, adjusted_prob))
        
        return adjusted_prob, 1 - adjusted_prob, confidence
    
    def calculate_kelly_fraction(self, p_true: float, p_market: float) -> float:
        """
        Calculate Kelly criterion fraction for binary bet.
        
        f* = (P_true - P_market) / (1 - P_market)
        
        Positive = bet on this outcome
        Negative = bet against (or skip)
        """
        if p_market >= 1.0 or p_market <= 0:
            return 0
        
        # Full Kelly
        full_kelly = (p_true - p_market) / (1 - p_market)
        
        # Apply fractional Kelly for safety
        fractional_kelly = full_kelly * self.kelly_fraction
        
        return fractional_kelly
    
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
                self.returns_history.append(ret)
        
        # Check cooldown
        if self.period_count - self.last_signal_period < self.cooldown_periods:
            return None
        
        # Need enough data
        if len(self.price_history) < self.lookback_periods:
            return None
        
        # Estimate true probabilities
        p_up, p_down, estimate_confidence = self.estimate_true_probability(current_price)
        
        # Current market implied probability (price = implied prob for binary)
        p_market_up = current_price
        p_market_down = 1 - current_price
        
        # Calculate Kelly fractions for both directions
        kelly_up = self.calculate_kelly_fraction(p_up, p_market_up)
        kelly_down = self.calculate_kelly_fraction(p_down, p_market_down)
        
        # Determine if there's sufficient edge
        signal = None
        confidence = 0.0
        reason = ""
        metadata = {}
        
        # Check for UP signal
        if kelly_up > self.min_kelly_fraction:
            edge = p_up - p_market_up
            if edge > self.min_edge:
                signal = "up"
                # Scale confidence by edge and Kelly fraction
                base_conf = 0.60
                edge_boost = min(edge * self.confidence_scaling, 0.15)
                kelly_boost = min(kelly_up * 0.5, 0.10)
                estimate_boost = (estimate_confidence - 0.5) * 0.1
                
                confidence = base_conf + edge_boost + kelly_boost + estimate_boost
                confidence = min(confidence, 0.90)
                
                reason = f"Kelly UP: edge={edge:.2%}, kelly={kelly_up:.2%}, P_est={p_up:.2%}"
                metadata = {
                    'p_true': p_up,
                    'p_market': p_market_up,
                    'edge': edge,
                    'kelly_fraction': kelly_up,
                    'estimate_confidence': estimate_confidence
                }
        
        # Check for DOWN signal
        elif kelly_down > self.min_kelly_fraction:
            edge = p_down - p_market_down
            if edge > self.min_edge:
                signal = "down"
                # Scale confidence by edge and Kelly fraction
                base_conf = 0.60
                edge_boost = min(edge * self.confidence_scaling, 0.15)
                kelly_boost = min(kelly_down * 0.5, 0.10)
                estimate_boost = (estimate_confidence - 0.5) * 0.1
                
                confidence = base_conf + edge_boost + kelly_boost + estimate_boost
                confidence = min(confidence, 0.90)
                
                reason = f"Kelly DOWN: edge={edge:.2%}, kelly={kelly_down:.2%}, P_est={p_down:.2%}"
                metadata = {
                    'p_true': p_down,
                    'p_market': p_market_down,
                    'edge': edge,
                    'kelly_fraction': kelly_down,
                    'estimate_confidence': estimate_confidence
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
