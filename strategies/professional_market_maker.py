from core.base_strategy import BaseStrategy
import numpy as np
from datetime import datetime, timedelta

class ProfessionalMarketMaker(BaseStrategy):
    """
    Strategy: Professional market making with inventory management.
    
    Concept: Profit from bid-ask spreads by providing liquidity on both sides.
    Place simultaneous buy/sell orders, capture spread when both fill.
    
    Key Features:
    - Dynamic spread adjustment based on volatility
    - Inventory skew management (keep YES/NO balanced)
    - Quote refresh every 500-1000ms
    - Target 1-2% profit per round trip
    """
    
    def __init__(self):
        super().__init__("ProfessionalMarketMaker")
        self.base_spread = 0.02  # 2% base spread
        self.max_spread = 0.05   # 5% max spread in volatile markets
        self.min_spread = 0.01   # 1% min spread in calm markets
        self.max_position_size = 0.10  # 10% of capital per side
        self.max_inventory_skew = 0.30  # 30% max skew (YES vs NO)
        self.target_profit = 0.015  # 1.5% target per round trip
        
    def should_trade(self, market_data):
        """Check if market is suitable for market making"""
        # Need high volume for liquidity
        volume_24h = market_data.get('volume_24h', 0)
        if volume_24h < 100000:  # Min $100K volume
            return False
            
        # Avoid highly volatile markets
        volatility = market_data.get('volatility_24h', 0)
        if volatility > 0.30:  # Skip if >30% volatility
            return False
            
        # Check current spread
        best_bid = market_data.get('best_bid', 0)
        best_ask = market_data.get('best_ask', 1)
        current_spread = best_ask - best_bid
        
        # Trade if there's room for our spread
        return current_spread > self.min_spread
        
    def get_signal(self, market_data):
        """Generate market making quotes"""
        if not self.should_trade(market_data):
            return None
            
        mid_price = market_data.get('mid_price', 0.5)
        volatility = market_data.get('volatility_24h', 0.1)
        
        # Adjust spread based on volatility
        if volatility > 0.20:
            spread = self.max_spread
        elif volatility > 0.10:
            spread = self.base_spread
        else:
            spread = self.min_spread
            
        # Calculate bid/ask
        bid_price = mid_price - (spread / 2)
        ask_price = mid_price + (spread / 2)
        
        # Ensure prices are valid
        bid_price = max(0.01, min(0.99, bid_price))
        ask_price = max(0.01, min(0.99, ask_price))
        
        return {
            'action': 'MARKET_MAKE',
            'bid_price': bid_price,
            'ask_price': ask_price,
            'spread': spread,
            'confidence': 0.75,  # Market making is lower confidence but higher frequency
            'reason': f"Market making: Bid {bid_price:.3f}, Ask {ask_price:.3f}, Spread {spread:.1%}"
        }
        
    def calculate_position_size(self, capital, confidence):
        """Size based on inventory management"""
        # Start with base size
        base_size = capital * self.max_position_size
        
        # Adjust for confidence
        return base_size * confidence
        
    def manage_inventory(self, current_yes_position, current_no_position, total_capital):
        """Adjust quotes based on inventory skew"""
        total_position = current_yes_position + current_no_position
        if total_position == 0:
            return {'skew': 0, 'adjustment': 0}
            
        # Calculate skew
        yes_ratio = current_yes_position / total_position
        skew = yes_ratio - 0.5  # -0.5 to +0.5
        
        # If heavily skewed YES, lower bid (buy less YES) and raise ask (sell more YES)
        # If heavily skewed NO, raise bid (buy more YES) and lower ask (sell less YES)
        adjustment = skew * 0.02  # 2% adjustment per 50% skew
        
        return {
            'skew': skew,
            'adjustment': adjustment,
            'should_rebalance': abs(skew) > self.max_inventory_skew
        }
        
    def get_required_data(self):
        """Specify required data feeds"""
        return ['mid_price', 'best_bid', 'best_ask', 'volume_24h', 'volatility_24h']
