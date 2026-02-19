"""
RetailSentimentFade Strategy - Fade retail overreaction in prediction markets.

Economic Rationale:
- Retail traders in prediction markets tend to overreact to recent price movements
- They chase momentum and panic at extremes, creating mean-reversion opportunities
- This is the "fading the public" concept adapted for binary prediction markets

Edge Source:
- Contrarian positioning against retail sentiment extremes
- Exploits behavioral bias of overreaction in short timeframes
"""

from typing import Optional, Dict, Any, List
from datetime import datetime
from core.base_strategy import BaseStrategy, Signal, MarketData


class RetailSentimentFadeStrategy(BaseStrategy):
    """
    Fade extreme retail sentiment in BTC 5-min prediction markets.
    
    Logic:
    - When price moves rapidly toward extremes (0.05 or 0.95), retail piles on
    - These extremes often overstate the true probability
    - Fade the move: buy when price crashes, sell when price spikes
    - Works best in the middle of the 5-minute window when noise is highest
    """
    
    name = "RetailSentimentFade"
    version = "1.0.0"
    
    def __init__(self, config: Dict = None):
        super().__init__(config)
        config = config or {}
        self.price_history: List[float] = []
        self.max_history = 20
        
        # Configurable thresholds
        self.extreme_low = config.get('extreme_low', 0.15) if config else 0.15
        self.extreme_high = config.get('extreme_high', 0.85) if config else 0.85
        self.velocity_threshold = config.get('velocity_threshold', 0.03) if config else 0.03
        self.min_time_in_window = config.get('min_time_in_window', 60) if config else 60
        
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        """Generate contrarian signal against retail sentiment extremes."""
        
        # Need order book data for this strategy
        if not data.order_book:
            return None
            
        # Get current price
        current_price = data.mid
        
        # Track price history for velocity calculation
        self.price_history.append(current_price)
        if len(self.price_history) > self.max_history:
            self.price_history.pop(0)
        
        # Need enough history
        if len(self.price_history) < 5:
            return None
        
        # Calculate price velocity (recent change)
        price_velocity = current_price - self.price_history[-5]
        
        # Get time in current window (assuming 5-min = 300s windows)
        current_time = data.timestamp
        time_in_window = current_time % 300
        
        # Only trade after minimum time in window (avoid opening noise)
        if time_in_window < self.min_time_in_window:
            return None
        
        # Calculate order book imbalance to gauge retail sentiment
        bids = data.order_book.get('bids', [])
        asks = data.order_book.get('asks', [])
        
        if not bids or not asks:
            return None
        
        # Calculate volume at best levels
        best_bid_vol = sum(b[1] for b in bids[:3]) if bids else 0
        best_ask_vol = sum(a[1] for a in asks[:3]) if asks else 0
        
        if best_bid_vol + best_ask_vol == 0:
            return None
        
        # Order book imbalance (positive = more buying pressure)
        obi = (best_bid_vol - best_ask_vol) / (best_bid_vol + best_ask_vol)
        
        # SIGNAL 1: Extreme low price with buying pressure building
        # Retail panicked, price oversold, smart money stepping in
        if current_price < self.extreme_low and obi > 0.3 and price_velocity > 0:
            confidence = min(0.95, 0.6 + abs(obi) * 0.3 + abs(price_velocity) * 5)
            return Signal(
                strategy=self.name,
                signal='up',
                confidence=confidence,
                reason=f"Fade extreme low: price={current_price:.3f}, OBI={obi:.2f}, velocity={price_velocity:+.3f}",
                metadata={
                    'price': current_price,
                    'obi': obi,
                    'velocity': price_velocity,
                    'time_in_window': time_in_window
                }
            )
        
        # SIGNAL 2: Extreme high price with selling pressure building
        # Retail FOMO'd, price overbought, distribution starting
        if current_price > self.extreme_high and obi < -0.3 and price_velocity < 0:
            confidence = min(0.95, 0.6 + abs(obi) * 0.3 + abs(price_velocity) * 5)
            return Signal(
                strategy=self.name,
                signal='down',
                confidence=confidence,
                reason=f"Fade extreme high: price={current_price:.3f}, OBI={obi:.2f}, velocity={price_velocity:+.3f}",
                metadata={
                    'price': current_price,
                    'obi': obi,
                    'velocity': price_velocity,
                    'time_in_window': time_in_window
                }
            )
        
        # SIGNAL 3: Rapid price spike on low volume (retail chasing)
        if price_velocity > self.velocity_threshold and current_price > 0.6 and obi < 0:
            confidence = min(0.9, 0.65 + abs(price_velocity) * 5)
            return Signal(
                strategy=self.name,
                signal='down',
                confidence=confidence,
                reason=f"Fade momentum spike: price={current_price:.3f}, velocity={price_velocity:+.3f}",
                metadata={
                    'price': current_price,
                    'velocity': price_velocity,
                    'obi': obi
                }
            )
        
        # SIGNAL 4: Rapid price crash on low volume (retail panic)
        if price_velocity < -self.velocity_threshold and current_price < 0.4 and obi > 0:
            confidence = min(0.9, 0.65 + abs(price_velocity) * 5)
            return Signal(
                strategy=self.name,
                signal='up',
                confidence=confidence,
                reason=f"Fade momentum crash: price={current_price:.3f}, velocity={price_velocity:+.3f}",
                metadata={
                    'price': current_price,
                    'velocity': price_velocity,
                    'obi': obi
                }
            )
        
        return None
