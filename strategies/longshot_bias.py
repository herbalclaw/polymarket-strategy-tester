from typing import Optional, Dict, List
from collections import deque
import statistics

from core.base_strategy import BaseStrategy, Signal, MarketData


class LongshotBiasStrategy(BaseStrategy):
    """
    Longshot Bias Exploitation Strategy
    
    Based on academic research showing traders systematically overvalue 
    underdogs and undervalue favorites in prediction markets.
    
    Edge: Behavioral bias - people love betting on longshots
    Method: Systematically bet on favorites (short odds) where 
            implied probability < true probability
    
    Research: Quantpedia - Systematic Edges in Prediction Markets
    """
    
    name = "LongshotBias"
    description = "Exploit behavioral bias - overvaluation of underdogs"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        config = config or {}
        # Favorites = price > 0.50 (implied probability > 50%)
        # But we want STRONG favorites with edge
        self.min_favorite_price = self.config.get('min_favorite_price', 0.60)  # 60%+ implied prob
        self.max_favorite_price = self.config.get('max_favorite_price', 0.85)  # Cap at 85%
        self.edge_threshold = self.config.get('edge_threshold', 0.02)  # 2% minimum edge
        
        # Price history to detect true probability vs market price
        self.price_history: deque = deque(maxlen=50)
        self.true_prob_window = self.config.get('true_prob_window', 20)
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_price = data.price
        
        # Store price history
        self.price_history.append(current_price)
        
        # Only trade favorites (price > 0.50 means YES is favorite)
        if current_price < self.min_favorite_price:
            return None
        
        if current_price > self.max_favorite_price:
            return None  # Too expensive, no edge
        
        # Need enough history to estimate true probability
        if len(self.price_history) < self.true_prob_window:
            return None
        
        # Calculate median price as estimate of true probability
        recent_prices = list(self.price_history)[-self.true_prob_window:]
        true_prob = statistics.median(recent_prices)
        
        # Market price vs true probability
        market_prob = current_price
        
        # Edge = true_prob - market_prob
        # If positive, market is undervaluing the favorite
        edge = true_prob - market_prob
        
        if edge < self.edge_threshold:
            return None  # No edge
        
        # Signal: Buy YES on the favorite
        confidence = min(0.5 + edge * 5, 0.85)  # Scale confidence with edge
        
        return Signal(
            strategy=self.name,
            signal="up",  # Buy YES (favorite)
            confidence=confidence,
            reason=f"Favorite bias: market {market_prob:.2%} vs true {true_prob:.2%}, edge {edge:.1%}",
            metadata={
                'market_prob': market_prob,
                'true_prob': true_prob,
                'edge': edge,
                'window': self.true_prob_window
            }
        )
