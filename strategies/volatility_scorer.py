"""
Volatility-Based Market Selection Strategy

Ranks markets by risk-adjusted return potential.
Targets low-volatility markets with high liquidity rewards.

Reference: defiance_cr interview, Poly-Maker bot
"""

from typing import Optional, Dict, List
from collections import deque
from statistics import mean, stdev
import math

from core.base_strategy import BaseStrategy, Signal, MarketData


class VolatilityScorerStrategy(BaseStrategy):
    """
    Selects markets based on volatility/reward ratio.
    
    Formula: Score = Expected_Reward / Volatility
    
    High score = low risk, high reward (ideal)
    Low score = high risk, low reward (avoid)
    """
    
    name = "volatility_scorer"
    description = "Select markets by risk-adjusted reward potential"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        # Timeframes for volatility calculation (in data points)
        self.timeframes = self.config.get('timeframes', {
            'short': 20,    # ~3 hours at 5-min intervals
            'medium': 100,  # ~8 hours
            'long': 500     # ~40 hours
        })
        # Weights for each timeframe
        self.weights = self.config.get('weights', {
            'short': 0.4,
            'medium': 0.3,
            'long': 0.2,
            'reward': 0.1
        })
        # Minimum score to generate signal
        self.min_score = self.config.get('min_score', 0.5)
        # Maximum acceptable volatility (filter out chaotic markets)
        self.max_volatility = self.config.get('max_volatility', 0.05)  # 5%
        
        # Price history for each timeframe
        self.price_history = deque(maxlen=max(self.timeframes.values()))
        
    def calculate_volatility(self, prices: List[float]) -> float:
        """
        Calculate volatility as coefficient of variation.
        
        Returns:
            Volatility score (0 = no movement, higher = more volatile)
        """
        if len(prices) < 2:
            return float('inf')  # Not enough data
        
        avg = mean(prices)
        if avg == 0:
            return float('inf')
        
        try:
            std = stdev(prices)
            cv = std / avg  # Coefficient of variation
            return cv
        except:
            return float('inf')
    
    def calculate_price_range(self, prices: List[float]) -> float:
        """Calculate price range as percentage of mean."""
        if len(prices) < 2:
            return 1.0  # Max uncertainty
        
        avg = mean(prices)
        if avg == 0:
            return 1.0
        
        price_range = (max(prices) - min(prices)) / avg
        return price_range
    
    def score_market(self, market_data: MarketData) -> Optional[Dict]:
        """
        Calculate risk-adjusted score for the market.
        
        Returns:
            Dict with score components or None if insufficient data
        """
        if len(self.price_history) < self.timeframes['short']:
            return None
        
        prices = list(self.price_history)
        
        # Calculate volatility for each timeframe
        volatilities = {}
        for name, window in self.timeframes.items():
            if len(prices) >= window:
                recent_prices = prices[-window:]
                volatilities[name] = self.calculate_volatility(recent_prices)
            else:
                volatilities[name] = float('inf')
        
        # Check if any volatility is too high
        for name, vol in volatilities.items():
            if vol > self.max_volatility:
                return {
                    'score': 0,
                    'volatilities': volatilities,
                    'rejected': True,
                    'reason': f'{name} volatility too high: {vol:.2%}'
                }
        
        # Calculate weighted volatility
        weighted_vol = (
            volatilities.get('short', 1) * self.weights['short'] +
            volatilities.get('medium', 1) * self.weights['medium'] +
            volatilities.get('long', 1) * self.weights['long']
        )
        
        # Estimate reward (simplified - would need actual reward data)
        # For now, use inverse of volatility as proxy for stability
        # More stable markets = easier to market make = higher rewards
        estimated_reward = 0.02  # 2% base reward assumption
        
        # Calculate risk-adjusted score
        if weighted_vol == 0:
            score = float('inf')
        else:
            score = estimated_reward / weighted_vol
        
        # Calculate price trend
        if len(prices) >= 2:
            price_change = (prices[-1] - prices[0]) / prices[0] if prices[0] > 0 else 0
        else:
            price_change = 0
        
        return {
            'score': score,
            'volatilities': volatilities,
            'weighted_volatility': weighted_vol,
            'estimated_reward': estimated_reward,
            'price_change': price_change,
            'rejected': False
        }
    
    def generate_signal(self, market_data: MarketData) -> Optional[Signal]:
        """Generate signal if market passes volatility screening."""
        # Update price history
        self.price_history.append(market_data.price)
        
        # Score the market
        score_data = self.score_market(market_data)
        
        if not score_data:
            return None
        
        # If rejected due to high volatility, no signal
        if score_data.get('rejected'):
            return None
        
        # Check if score meets threshold
        if score_data['score'] < self.min_score:
            return None
        
        # Generate signal based on price trend
        # Low volatility + upward trend = bullish
        # Low volatility + downward trend = bearish
        price_change = score_data['price_change']
        
        if abs(price_change) < 0.01:  # Less than 1% change
            # Sideways market - good for market making
            signal_type = "neutral"
            reason = f"Low vol market (score: {score_data['score']:.2f}) - ideal for market making"
        elif price_change > 0:
            signal_type = "up"
            reason = f"Low vol uptrend ({price_change:.2%}) - score: {score_data['score']:.2f}"
        else:
            signal_type = "down"
            reason = f"Low vol downtrend ({price_change:.2%}) - score: {score_data['score']:.2f}"
        
        # Confidence based on score quality
        confidence = min(0.6 + score_data['score'] * 0.1, 0.85)
        
        return Signal(
            strategy=self.name,
            signal=signal_type,
            confidence=confidence,
            reason=reason,
            metadata={
                'score': score_data['score'],
                'weighted_volatility': score_data['weighted_volatility'],
                'price_change': price_change,
                'timeframe_vols': score_data['volatilities']
            }
        )
