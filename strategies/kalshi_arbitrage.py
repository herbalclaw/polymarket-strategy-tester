from strategies.base_strategy import BaseStrategy
import numpy as np
from datetime import datetime, timedelta

class KalshiArbitrage(BaseStrategy):
    """
    Strategy: Cross-platform arbitrage between Polymarket and Kalshi.
    
    Concept: Exploit price differences for identical events across platforms.
    When prices diverge beyond fee thresholds, buy low on one platform and 
    sell high on another.
    
    Requirements:
    - Monitor same events on both Polymarket and Kalshi
    - Fast execution (opportunities close in minutes)
    - Account for 2% fees on both platforms
    """
    
    def __init__(self):
        super().__init__("KalshiArbitrage")
        self.min_spread = 0.04  # 4% minimum spread (covers 2% fees on both sides)
        self.max_position_size = 0.20  # 20% of capital max
        self.kalshi_fee = 0.02  # 2% Kalshi fee
        self.polymarket_fee = 0.02  # 2% Polymarket fee
        self.total_fees = self.kalshi_fee + self.polymarket_fee
        
    def should_trade(self, market_data):
        """Check if arbitrage opportunity exists"""
        # Need both Polymarket and Kalshi prices
        poly_price = market_data.get('polymarket_price')
        kalshi_price = market_data.get('kalshi_price')
        
        if poly_price is None or kalshi_price is None:
            return False
            
        # Calculate spread
        spread = abs(poly_price - kalshi_price)
        
        # Trade if spread covers fees + profit
        return spread > (self.total_fees + self.min_spread)
        
    def get_signal(self, market_data):
        """Generate arbitrage signal"""
        if not self.should_trade(market_data):
            return None
            
        poly_price = market_data.get('polymarket_price', 0)
        kalshi_price = market_data.get('kalshi_price', 0)
        spread = abs(poly_price - kalshi_price)
        
        # Buy on cheaper platform, sell on expensive
        if poly_price < kalshi_price:
            # Buy on Polymarket, sell on Kalshi
            return {
                'action': 'ARBITRAGE',
                'buy_platform': 'polymarket',
                'sell_platform': 'kalshi',
                'buy_price': poly_price,
                'sell_price': kalshi_price,
                'spread': spread,
                'confidence': min(spread * 2, 0.95),  # Higher confidence with larger spread
                'reason': f"Arbitrage: Buy Polymarket @ {poly_price:.3f}, Sell Kalshi @ {kalshi_price:.3f}"
            }
        else:
            # Buy on Kalshi, sell on Polymarket
            return {
                'action': 'ARBITRAGE',
                'buy_platform': 'kalshi',
                'sell_platform': 'polymarket',
                'buy_price': kalshi_price,
                'sell_price': poly_price,
                'spread': spread,
                'confidence': min(spread * 2, 0.95),
                'reason': f"Arbitrage: Buy Kalshi @ {kalshi_price:.3f}, Sell Polymarket @ {poly_price:.3f}"
            }
            
    def calculate_position_size(self, capital, confidence):
        """Size based on spread and available capital"""
        # Larger spreads = larger positions (more edge)
        size_multiplier = min(confidence * 1.5, 1.0)
        return capital * self.max_position_size * size_multiplier
        
    def get_required_data(self):
        """Specify required data feeds"""
        return ['polymarket_price', 'kalshi_price', 'event_name']
