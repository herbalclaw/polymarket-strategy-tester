"""
InventorySkewStrategy

Exploits market maker inventory skewing behavior. When market makers accumulate
inventory on one side, they skew their quotes to encourage trades that reduce
that inventory. This creates predictable price pressure.

Key insight: Heavy YES inventory → market makers lower quotes to encourage selling
Heavy NO inventory → market makers raise quotes to encourage buying
By detecting inventory imbalances through order book dynamics, we can front-run
the quote adjustments.

Reference: Stoikov model adaptation for prediction markets - Market makers skew
quotes proportionally to inventory to manage risk.
"""

from typing import Optional
from collections import deque
import statistics

from core.base_strategy import BaseStrategy, Signal, MarketData


class InventorySkewStrategy(BaseStrategy):
    """
    Detect and exploit market maker inventory skewing.
    
    Strategy logic:
    1. Analyze order book depth asymmetry as proxy for inventory pressure
    2. Detect when bid/ask clusters suggest MM inventory imbalance
    3. Trade in direction that aligns with MM's desired inventory reduction
    4. Capture the price move as MMs adjust quotes
    
    Works on the principle that MMs skew quotes to manage inventory:
    - Long inventory → lower quotes (want to sell)
    - Short inventory → raise quotes (want to buy)
    """
    
    name = "InventorySkew"
    description = "Exploit market maker inventory skewing patterns"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        
        # Order book analysis depth
        self.depth_levels = self.config.get('depth_levels', 5)
        
        # Inventory pressure thresholds
        self.skew_threshold = self.config.get('skew_threshold', 0.15)  # 15% imbalance
        self.strong_skew = self.config.get('strong_skew', 0.30)
        
        # Volume requirements
        self.min_volume = self.config.get('min_volume', 2000)
        self.min_depth_ratio = self.config.get('min_depth_ratio', 2.0)
        
        # History tracking
        self.skew_history = deque(maxlen=20)
        self.price_history = deque(maxlen=20)
        
        # Confirmation
        self.confirmation_periods = self.config.get('confirmation_periods', 2)
        self.skew_count = 0
        self.last_skew_direction = None
        
        # Cooldown
        self.last_signal_time = 0
        self.cooldown_seconds = self.config.get('cooldown_seconds', 90)
    
    def calculate_inventory_pressure(self, data: MarketData) -> tuple:
        """
        Calculate inventory pressure indicators from order book.
        
        Returns: (skew_score, bid_depth, ask_depth, interpretation)
        skew_score: positive = MM likely long (wants to sell)
                    negative = MM likely short (wants to buy)
        """
        if not data.order_book:
            return 0.0, 0.0, 0.0, "neutral"
        
        bids = data.order_book.get('bids', [])
        asks = data.order_book.get('asks', [])
        
        if not bids or not asks:
            return 0.0, 0.0, 0.0, "neutral"
        
        # Calculate depth at each level
        bid_depth = sum(float(b.get('size', 0)) for b in bids[:self.depth_levels])
        ask_depth = sum(float(a.get('size', 0)) for a in asks[:self.depth_levels])
        
        total_depth = bid_depth + ask_depth
        if total_depth < self.min_volume:
            return 0.0, bid_depth, ask_depth, "low_volume"
        
        # Calculate skew: positive = more bids (MM likely long)
        skew = (bid_depth - ask_depth) / total_depth
        
        # Interpretation
        if skew > self.strong_skew:
            interpretation = "heavy_long"
        elif skew > self.skew_threshold:
            interpretation = "moderate_long"
        elif skew < -self.strong_skew:
            interpretation = "heavy_short"
        elif skew < -self.skew_threshold:
            interpretation = "moderate_short"
        else:
            interpretation = "balanced"
        
        return skew, bid_depth, ask_depth, interpretation
    
    def detect_quote_skewing(self, data: MarketData, skew: float) -> tuple:
        """
        Detect if quotes are being skewed based on mid price vs microprice.
        
        Returns: (is_skewed, skew_direction, magnitude)
        """
        if not data.order_book:
            return False, "neutral", 0.0
        
        bids = data.order_book.get('bids', [])
        asks = data.order_book.get('asks', [])
        
        if not bids or not asks:
            return False, "neutral", 0.0
        
        best_bid = float(bids[0].get('price', data.bid))
        best_ask = float(asks[0].get('price', data.ask))
        mid = (best_bid + best_ask) / 2
        
        bid_vol = sum(float(b.get('size', 0)) for b in bids[:self.depth_levels])
        ask_vol = sum(float(a.get('size', 0)) for a in asks[:self.depth_levels])
        total_vol = bid_vol + ask_vol
        
        if total_vol == 0:
            return False, "neutral", 0.0
        
        # Microprice: volume-weighted fair value
        microprice = (best_bid * ask_vol + best_ask * bid_vol) / total_vol
        
        # Compare mid to microprice
        deviation = mid - microprice
        
        # If mid is below microprice, quotes are skewed down (MM wants to sell)
        # If mid is above microprice, quotes are skewed up (MM wants to buy)
        threshold = 0.002  # 0.2 cents threshold
        
        if deviation < -threshold:
            return True, "down", abs(deviation)
        elif deviation > threshold:
            return True, "up", abs(deviation)
        
        return False, "neutral", 0.0
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_time = data.timestamp
        
        # Cooldown check
        if current_time - self.last_signal_time < self.cooldown_seconds:
            return None
        
        # Calculate inventory pressure
        skew, bid_depth, ask_depth, interpretation = self.calculate_inventory_pressure(data)
        self.skew_history.append(skew)
        self.price_history.append(data.price)
        
        # Need enough history
        if len(self.skew_history) < self.confirmation_periods:
            return None
        
        # Check for quote skewing
        is_skewed, skew_direction, skew_magnitude = self.detect_quote_skewing(data, skew)
        
        signal = None
        confidence = 0.0
        reason = ""
        metadata = {}
        
        # Strategy: Trade in direction of quote skew
        # If MMs are skewing quotes down → they want to sell (are long) → we sell too
        # If MMs are skewing quotes up → they want to buy (are short) → we buy too
        
        if is_skewed and abs(skew) > self.skew_threshold:
            # Confirm skew persistence
            recent_skews = list(self.skew_history)[-self.confirmation_periods:]
            avg_skew = statistics.mean(recent_skews)
            
            # Check consistency between inventory pressure and quote skew
            if skew_direction == "down" and avg_skew > self.skew_threshold:
                # MM is long and skewing quotes down to sell
                signal = "down"
                base_conf = 0.58
                skew_boost = min(abs(avg_skew) * 0.2, 0.12)
                magnitude_boost = min(skew_magnitude * 50, 0.08)
                
                confidence = min(base_conf + skew_boost + magnitude_boost, 0.82)
                reason = f"MM inventory skew: heavy long ({avg_skew:.2f}), quotes skewed down"
                metadata = {
                    'skew': avg_skew,
                    'bid_depth': bid_depth,
                    'ask_depth': ask_depth,
                    'interpretation': interpretation,
                    'skew_magnitude': skew_magnitude
                }
            
            elif skew_direction == "up" and avg_skew < -self.skew_threshold:
                # MM is short and skewing quotes up to buy
                signal = "up"
                base_conf = 0.58
                skew_boost = min(abs(avg_skew) * 0.2, 0.12)
                magnitude_boost = min(skew_magnitude * 50, 0.08)
                
                confidence = min(base_conf + skew_boost + magnitude_boost, 0.82)
                reason = f"MM inventory skew: heavy short ({avg_skew:.2f}), quotes skewed up"
                metadata = {
                    'skew': avg_skew,
                    'bid_depth': bid_depth,
                    'ask_depth': ask_depth,
                    'interpretation': interpretation,
                    'skew_magnitude': skew_magnitude
                }
        
        if signal and confidence >= self.min_confidence:
            self.last_signal_time = current_time
            
            return Signal(
                strategy=self.name,
                signal=signal,
                confidence=confidence,
                reason=reason,
                metadata=metadata
            )
        
        return None
