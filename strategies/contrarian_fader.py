from strategies.base_strategy import BaseStrategy
import numpy as np
from datetime import datetime, timedelta
import random

class ContrarianFader(BaseStrategy):
    """
    Strategy: Fade emotionally-charged markets where retail bias overwhelms rational probability.
    
    Concept: Bet against popular/emotional markets (fan favorites, hyped events) where prices
    are inflated by bias rather than true probability.
    
    Entry: When market shows signs of emotional overpricing (high volume + price spikes)
    Exit: When price reverts closer to fundamental probability
    """
    
    def __init__(self):
        super().__init__("ContrarianFader")
        self.emotional_keywords = ['trump', 'biden', 'lakers', 'yankees', 'cowboys', 'bitcoin', 'meme']
        self.max_position_size = 0.15  # 15% of capital max
        self.profit_target = 0.08  # 8% profit
        self.stop_loss = 0.05  # 5% stop
        
    def should_trade(self, market_data):
        """Check if market is emotionally overpriced"""
        # Check if market name contains emotional keywords
        market_name = market_data.get('name', '').lower()
        is_emotional = any(kw in market_name for kw in self.emotional_keywords)
        
        if not is_emotional:
            return False
            
        # Check for volume spike (3x average)
        current_volume = market_data.get('volume_24h', 0)
        avg_volume = market_data.get('avg_volume_7d', current_volume)
        volume_spike = current_volume > (avg_volume * 3) if avg_volume > 0 else False
        
        # Check for price spike (>20% in 24h)
        price_change = abs(market_data.get('price_change_24h', 0))
        price_spike = price_change > 0.20
        
        # Trade when emotional + volume spike + price spike
        return is_emotional and volume_spike and price_spike
        
    def get_signal(self, market_data):
        """Generate contrarian signal"""
        if not self.should_trade(market_data):
            return None
            
        current_price = market_data.get('current_price', 0.5)
        
        # If price spiked up (overbought), sell/short
        # If price crashed down (oversold), buy
        price_change = market_data.get('price_change_24h', 0)
        
        if price_change > 0.20:  # Price spiked up - fade it
            return {
                'action': 'SELL',
                'confidence': min(abs(price_change) * 100, 0.85),
                'reason': f"Emotional overpricing detected: {price_change:.1%} spike"
            }
        elif price_change < -0.20:  # Price crashed - buy the dip
            return {
                'action': 'BUY',
                'confidence': min(abs(price_change) * 100, 0.85),
                'reason': f"Emotional overselling detected: {price_change:.1%} drop"
            }
            
        return None
        
    def calculate_position_size(self, capital, confidence):
        """Kelly-inspired sizing with emotional market adjustment"""
        # More conservative in emotional markets
        base_size = capital * self.max_position_size * confidence
        # Reduce size by 30% for emotional uncertainty
        return base_size * 0.70
