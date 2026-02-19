"""
Price Skew Momentum Strategy

Uses the skew between YES and NO token prices to detect market sentiment.
In prediction markets, the relationship between complementary tokens
contains information about market maker positioning and trader sentiment.

Key insight: When YES trades at premium to (1-NO), indicates bullish sentiment.
When YES trades at discount, indicates bearish sentiment.
Large deviations create mean-reversion opportunities.

Reference: Market microstructure of binary options and prediction markets
"""

from typing import Optional, Dict
from collections import deque
from statistics import mean, stdev

from core.base_strategy import BaseStrategy, Signal, MarketData


class PriceSkewStrategy(BaseStrategy):
    """
    Price skew strategy for binary prediction markets.
    
    In efficient prediction markets: YES_price + NO_price = 1.0 (minus fees)
    Deviations from this indicate:
    - Temporary order book imbalances
    - Different liquidity on each side
    - Sentiment divergence
    
    Strategy: Trade in direction of skew when it exceeds historical norms.
    """
    
    name = "PriceSkew"
    description = "Price skew momentum between YES/NO tokens"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        config = config or {}
        
        # Skew calculation
        self.skew_history: deque = deque(maxlen=100)
        self.price_history: deque = deque(maxlen=50)
        
        # Thresholds
        self.skew_threshold = self.config.get('skew_threshold', 0.02)  # 2% skew
        self.zscore_threshold = self.config.get('zscore_threshold', 1.5)  # 1.5 std devs
        
        # Mean reversion vs momentum mode
        self.mean_reversion = self.config.get('mean_reversion', False)  # Default: momentum
        
        # Minimum data
        self.min_history = 20
        
    def calculate_skew(self, yes_price: float, no_price: float) -> float:
        """
        Calculate price skew.
        
        Skew = YES_price - (1 - NO_price)
        
        Positive skew = YES trades at premium (bullish)
        Negative skew = YES trades at discount (bearish)
        Zero = Perfect efficiency
        """
        implied_yes = 1 - no_price
        skew = yes_price - implied_yes
        return skew
    
    def get_skew_stats(self) -> Optional[Dict]:
        """Calculate skew statistics."""
        if len(self.skew_history) < self.min_history:
            return None
        
        skews = list(self.skew_history)
        
        avg_skew = mean(skews)
        try:
            std_skew = stdev(skews)
        except:
            std_skew = 0.01  # Default small std
        
        # Current skew
        current_skew = skews[-1]
        
        # Z-score
        if std_skew > 0:
            zscore = (current_skew - avg_skew) / std_skew
        else:
            zscore = 0
        
        return {
            'current': current_skew,
            'mean': avg_skew,
            'std': std_skew,
            'zscore': zscore,
            'max': max(skews),
            'min': min(skews)
        }
    
    def generate_signal(self, market_data: MarketData) -> Optional[Signal]:
        """Generate signal based on price skew."""
        # Get YES and NO prices from order book
        order_book = market_data.order_book or {}
        
        # Try to extract YES and NO prices
        yes_price = None
        no_price = None
        
        if 'yes' in order_book and 'no' in order_book:
            yes_data = order_book['yes']
            no_data = order_book['no']
            
            # Use mid prices
            if 'bid' in yes_data and 'ask' in yes_data:
                yes_price = (yes_data['bid'] + yes_data['ask']) / 2
            if 'bid' in no_data and 'ask' in no_data:
                no_price = (no_data['bid'] + no_data['ask']) / 2
        
        # Fallback to market mid price
        if yes_price is None:
            yes_price = market_data.mid
        if no_price is None:
            # Estimate NO price from YES price
            no_price = 1 - yes_price
        
        # Calculate skew
        skew = self.calculate_skew(yes_price, no_price)
        self.skew_history.append(skew)
        self.price_history.append(yes_price)
        
        # Need enough history
        stats = self.get_skew_stats()
        if stats is None:
            return None
        
        current_skew = stats['current']
        zscore = stats['zscore']
        
        # Check if skew is significant
        skew_significant = abs(current_skew) > self.skew_threshold
        zscore_significant = abs(zscore) > self.zscore_threshold
        
        if not (skew_significant or zscore_significant):
            return None
        
        # Generate signal
        if self.mean_reversion:
            # Mean reversion: trade against the skew
            if current_skew > self.skew_threshold or zscore > self.zscore_threshold:
                # YES at premium - expect reversion down
                confidence = min(0.6 + abs(zscore) * 0.1 + abs(current_skew) * 5, 0.9)
                return Signal(
                    strategy=self.name,
                    signal="down",
                    confidence=confidence,
                    reason=f"Skew mean-reversion: YES premium {current_skew:.2%} (z={zscore:.1f})",
                    metadata={
                        'skew': current_skew,
                        'zscore': zscore,
                        'yes_price': yes_price,
                        'no_price': no_price,
                        'mode': 'mean_reversion'
                    }
                )
            else:
                # YES at discount - expect reversion up
                confidence = min(0.6 + abs(zscore) * 0.1 + abs(current_skew) * 5, 0.9)
                return Signal(
                    strategy=self.name,
                    signal="up",
                    confidence=confidence,
                    reason=f"Skew mean-reversion: YES discount {current_skew:.2%} (z={zscore:.1f})",
                    metadata={
                        'skew': current_skew,
                        'zscore': zscore,
                        'yes_price': yes_price,
                        'no_price': no_price,
                        'mode': 'mean_reversion'
                    }
                )
        else:
            # Momentum: trade with the skew (sentiment following)
            if current_skew > self.skew_threshold or zscore > self.zscore_threshold:
                # YES at premium - bullish sentiment
                confidence = min(0.6 + abs(zscore) * 0.1 + abs(current_skew) * 5, 0.9)
                return Signal(
                    strategy=self.name,
                    signal="up",
                    confidence=confidence,
                    reason=f"Skew momentum: Bullish sentiment {current_skew:.2%} (z={zscore:.1f})",
                    metadata={
                        'skew': current_skew,
                        'zscore': zscore,
                        'yes_price': yes_price,
                        'no_price': no_price,
                        'mode': 'momentum'
                    }
                )
            else:
                # YES at discount - bearish sentiment
                confidence = min(0.6 + abs(zscore) * 0.1 + abs(current_skew) * 5, 0.9)
                return Signal(
                    strategy=self.name,
                    signal="down",
                    confidence=confidence,
                    reason=f"Skew momentum: Bearish sentiment {current_skew:.2%} (z={zscore:.1f})",
                    metadata={
                        'skew': current_skew,
                        'zscore': zscore,
                        'yes_price': yes_price,
                        'no_price': no_price,
                        'mode': 'momentum'
                    }
                )
