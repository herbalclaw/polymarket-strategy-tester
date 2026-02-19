"""
MicroPriceReversion Strategy

Exploits the microprice (volume-weighted midpoint) deviation from the mid price.
When microprice is significantly above mid, it indicates buying pressure and
potential upward movement. When below, selling pressure.

Key insight: The microprice is a more accurate fair value estimate than mid,
especially in imbalanced orderbooks. Reversion to microprice from extreme
deviations provides edge.

Reference: Stoikov (2018) - The microprice is the expected future price given
order book imbalance.
"""

from typing import Optional
from collections import deque
import statistics

from core.base_strategy import BaseStrategy, Signal, MarketData


class MicroPriceReversionStrategy(BaseStrategy):
    """
    Trade microprice deviations from mid.
    
    MicroPrice = (Bid * AskVol + Ask * BidVol) / (BidVol + AskVol)
    
    When price < microprice - threshold: Buy (price is below fair value)
    When price > microprice + threshold: Sell (price is above fair value)
    
    This captures the tendency of prices to revert to the volume-weighted fair value.
    """
    
    name = "MicroPriceReversion"
    description = "Microprice deviation reversion alpha"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        
        # Order book depth to consider
        self.depth_levels = self.config.get('depth_levels', 3)
        
        # Deviation threshold (in price terms)
        self.deviation_threshold = self.config.get('deviation_threshold', 0.005)  # 0.5 cents
        
        # Strong deviation threshold
        self.strong_deviation = self.config.get('strong_deviation', 0.010)  # 1 cent
        
        # Minimum volume requirement
        self.min_volume = self.config.get('min_volume', 500)
        
        # History tracking
        self.microprice_history = deque(maxlen=20)
        self.deviation_history = deque(maxlen=10)
        
        # Cooldown
        self.last_signal_time = 0
        self.cooldown_seconds = self.config.get('cooldown_seconds', 45)
        
        # Consecutive deviations required
        self.confirmation_count = self.config.get('confirmation_count', 2)
        self.deviation_count = 0
        self.last_deviation_direction = None
    
    def calculate_microprice(self, data: MarketData) -> tuple:
        """
        Calculate microprice and related metrics.
        Returns (microprice, imbalance, total_volume)
        """
        if not data.order_book:
            return data.mid, 0.5, 0
        
        bids = data.order_book.get('bids', [])
        asks = data.order_book.get('asks', [])
        
        if not bids or not asks:
            return data.mid, 0.5, 0
        
        best_bid = float(bids[0].get('price', data.bid))
        best_ask = float(asks[0].get('price', data.ask))
        
        # Calculate volume at depth
        bid_vol = sum(float(b.get('size', 0)) for b in bids[:self.depth_levels])
        ask_vol = sum(float(a.get('size', 0)) for a in asks[:self.depth_levels])
        total_vol = bid_vol + ask_vol
        
        if total_vol < self.min_volume:
            return data.mid, 0.5, total_vol
        
        # Calculate imbalance
        imbalance = bid_vol / total_vol if total_vol > 0 else 0.5
        
        # Calculate microprice: weighted by opposite side volume
        # More ask volume = more buying pressure = higher microprice
        microprice = (best_bid * ask_vol + best_ask * bid_vol) / total_vol
        
        return microprice, imbalance, total_vol
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_time = data.timestamp
        
        # Cooldown check
        if current_time - self.last_signal_time < self.cooldown_seconds:
            return None
        
        # Calculate microprice
        microprice, imbalance, total_vol = self.calculate_microprice(data)
        
        # Need minimum volume
        if total_vol < self.min_volume:
            return None
        
        # Store history
        self.microprice_history.append(microprice)
        
        # Calculate deviation from microprice
        current_price = data.price
        deviation = current_price - microprice  # Positive = price above microprice
        self.deviation_history.append(deviation)
        
        signal = None
        confidence = 0.0
        reason = ""
        
        # Price below microprice by threshold -> Buy (reversion up)
        if deviation < -self.deviation_threshold:
            # Track consecutive deviations
            if self.last_deviation_direction == "up":
                self.deviation_count += 1
            else:
                self.deviation_count = 1
                self.last_deviation_direction = "up"
            
            if self.deviation_count >= self.confirmation_count:
                # Calculate confidence based on deviation magnitude
                dev_size = abs(deviation)
                base_conf = 0.55
                dev_boost = min(dev_size / self.strong_deviation * 0.15, 0.15)
                imbalance_boost = (imbalance - 0.5) * 0.1 if imbalance > 0.5 else 0
                
                confidence = min(base_conf + dev_boost + imbalance_boost, 0.80)
                signal = "up"
                reason = f"Price {current_price:.3f} below micro {microprice:.3f} by {dev_size:.3f}"
        
        # Price above microprice by threshold -> Sell (reversion down)
        elif deviation > self.deviation_threshold:
            # Track consecutive deviations
            if self.last_deviation_direction == "down":
                self.deviation_count += 1
            else:
                self.deviation_count = 1
                self.last_deviation_direction = "down"
            
            if self.deviation_count >= self.confirmation_count:
                # Calculate confidence based on deviation magnitude
                dev_size = abs(deviation)
                base_conf = 0.55
                dev_boost = min(dev_size / self.strong_deviation * 0.15, 0.15)
                imbalance_boost = (0.5 - imbalance) * 0.1 if imbalance < 0.5 else 0
                
                confidence = min(base_conf + dev_boost + imbalance_boost, 0.80)
                signal = "down"
                reason = f"Price {current_price:.3f} above micro {microprice:.3f} by {dev_size:.3f}"
        
        else:
            # Reset deviation tracking
            self.deviation_count = 0
            self.last_deviation_direction = None
        
        if signal and confidence >= self.min_confidence:
            self.last_signal_time = current_time
            
            return Signal(
                strategy=self.name,
                signal=signal,
                confidence=confidence,
                reason=reason,
                metadata={
                    'microprice': microprice,
                    'deviation': deviation,
                    'imbalance': imbalance,
                    'total_volume': total_vol,
                    'price': current_price,
                    'mid': data.mid
                }
            )
        
        return None
