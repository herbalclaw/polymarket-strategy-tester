"""
QuoteStuffingDetector Strategy

Detects and exploits quote stuffing - a manipulative practice where
large numbers of orders are placed and quickly canceled to create
false impressions of supply/demand.

Key insight: Quote stuffing creates detectable patterns:
1. Rapid order book changes (high cancellation rate)
2. Large displayed size that disappears when hit
3. Price moves opposite to the fake depth direction

By detecting these patterns, we can trade against the manipulation.

Reference: "The Flash Crash: High-Frequency Trading in an Electronic Market"
- Kirilenko et al. (2017)
"""

from typing import Optional, Dict
from collections import deque
from statistics import mean, stdev
import time

from core.base_strategy import BaseStrategy, Signal, MarketData


class QuoteStuffingDetectorStrategy(BaseStrategy):
    """
    Detect quote stuffing patterns and trade against manipulation.
    
    Strategy logic:
    1. Monitor order book change frequency (cancellation rate)
    2. Detect "flash" depth that disappears quickly
    3. Identify price rejection at fake levels
    4. Trade in the direction opposite to the stuffing
    
    Quote stuffing is illegal but still occurs in crypto/prediction markets.
    """
    
    name = "QuoteStuffingDetector"
    description = "Detect and exploit quote stuffing manipulation"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        
        # Order book state tracking
        self.last_order_book: Optional[Dict] = None
        self.last_ob_time = 0
        
        # Change tracking
        self.change_history = deque(maxlen=50)
        self.depth_history = deque(maxlen=30)
        
        # Cancellation detection
        self.cancellation_rate_history = deque(maxlen=20)
        
        # Price rejection tracking
        self.price_history = deque(maxlen=30)
        self.rejection_history = deque(maxlen=20)
        
        # Thresholds
        self.stuffing_threshold = self.config.get('stuffing_threshold', 3.0)  # 3x normal change rate
        self.min_changes_per_sec = self.config.get('min_changes_per_sec', 5)
        self.rejection_threshold = self.config.get('rejection_threshold', 0.003)  # 0.3% rejection
        
        # Cooldown
        self.last_signal_time = 0
        self.cooldown_seconds = self.config.get('cooldown_seconds', 120)
        
        # Detection state
        self.stuffing_detected = False
        self.stuffing_direction = None  # 'up' or 'down'
        self.stuffing_start_time = 0
        
        # Minimum data
        self.min_history = 10
    
    def count_order_book_changes(self, current_ob: Dict, last_ob: Dict) -> int:
        """
        Count number of order book level changes.
        Returns number of price levels that changed.
        """
        if not last_ob:
            return 0
        
        changes = 0
        
        # Compare bids
        current_bids = {b.get('price'): b.get('size') for b in current_ob.get('bids', [])}
        last_bids = {b.get('price'): b.get('size') for b in last_ob.get('bids', [])}
        
        all_bid_prices = set(current_bids.keys()) | set(last_bids.keys())
        for price in all_bid_prices:
            if current_bids.get(price) != last_bids.get(price):
                changes += 1
        
        # Compare asks
        current_asks = {a.get('price'): a.get('size') for a in current_ob.get('asks', [])}
        last_asks = {a.get('price'): a.get('size') for a in last_ob.get('asks', [])}
        
        all_ask_prices = set(current_asks.keys()) | set(last_asks.keys())
        for price in all_ask_prices:
            if current_asks.get(price) != last_asks.get(price):
                changes += 1
        
        return changes
    
    def calculate_cancellation_rate(self) -> float:
        """
        Calculate cancellation rate from change history.
        High cancellation rate = potential quote stuffing
        """
        if len(self.change_history) < self.min_history:
            return 0.0
        
        # Calculate rate of changes per second
        if len(self.change_history) < 2:
            return 0.0
        
        total_changes = sum(self.change_history)
        time_span = len(self.change_history)  # Assuming 1-second intervals roughly
        
        if time_span == 0:
            return 0.0
        
        return total_changes / time_span
    
    def detect_flash_depth(self, data: MarketData) -> tuple:
        """
        Detect flash depth - large orders that appear and disappear quickly.
        Returns (is_flash, direction, strength)
        """
        if not data.order_book or len(self.depth_history) < 5:
            return False, "none", 0.0
        
        bids = data.order_book.get('bids', [])
        asks = data.order_book.get('asks', [])
        
        if not bids or not asks:
            return False, "none", 0.0
        
        # Current depth
        current_bid_depth = sum(float(b.get('size', 0)) for b in bids[:5])
        current_ask_depth = sum(float(a.get('size', 0)) for a in asks[:5])
        
        # Average depth from history
        avg_bid_depth = mean([d['bid_depth'] for d in self.depth_history])
        avg_ask_depth = mean([d['ask_depth'] for d in self.depth_history])
        
        # Detect flash depth (current much higher than average)
        bid_flash = current_bid_depth > avg_bid_depth * 2 if avg_bid_depth > 0 else False
        ask_flash = current_ask_depth > avg_ask_depth * 2 if avg_ask_depth > 0 else False
        
        if bid_flash and not ask_flash:
            strength = (current_bid_depth / avg_bid_depth - 1) if avg_bid_depth > 0 else 0
            return True, "up", min(strength, 3.0)
        elif ask_flash and not bid_flash:
            strength = (current_ask_depth / avg_ask_depth - 1) if avg_ask_depth > 0 else 0
            return True, "down", min(strength, 3.0)
        
        return False, "none", 0.0
    
    def detect_price_rejection(self) -> tuple:
        """
        Detect price rejection - price touched a level and reversed quickly.
        Returns (is_rejection, direction, strength)
        """
        if len(self.price_history) < 5:
            return False, "none", 0.0
        
        prices = list(self.price_history)
        
        # Check for rejection pattern: move up then down, or down then up
        if len(prices) >= 5:
            # Recent high/low detection
            recent = prices[-5:]
            
            # Up then down rejection
            if recent[2] > recent[0] and recent[2] > recent[4] and (recent[2] - recent[0]) > self.rejection_threshold:
                strength = (recent[2] - recent[0]) / recent[0] if recent[0] > 0 else 0
                return True, "up", strength
            
            # Down then up rejection
            if recent[2] < recent[0] and recent[2] < recent[4] and (recent[0] - recent[2]) > self.rejection_threshold:
                strength = (recent[0] - recent[2]) / recent[0] if recent[0] > 0 else 0
                return True, "down", strength
        
        return False, "none", 0.0
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_time = data.timestamp
        current_price = data.price
        
        # Update price history
        self.price_history.append(current_price)
        
        # Need order book data
        if not data.order_book:
            return None
        
        # Count order book changes
        changes = self.count_order_book_changes(data.order_book, self.last_order_book)
        self.change_history.append(changes)
        
        # Update depth history
        bids = data.order_book.get('bids', [])
        asks = data.order_book.get('asks', [])
        bid_depth = sum(float(b.get('size', 0)) for b in bids[:5])
        ask_depth = sum(float(a.get('size', 0)) for a in asks[:5])
        
        self.depth_history.append({
            'bid_depth': bid_depth,
            'ask_depth': ask_depth,
            'time': current_time
        })
        
        # Update last order book
        self.last_order_book = data.order_book
        self.last_ob_time = current_time
        
        # Cooldown check
        if current_time - self.last_signal_time < self.cooldown_seconds:
            return None
        
        # Need enough history
        if len(self.change_history) < self.min_history:
            return None
        
        # Calculate metrics
        cancellation_rate = self.calculate_cancellation_rate()
        is_flash, flash_direction, flash_strength = self.detect_flash_depth(data)
        is_rejection, rejection_direction, rejection_strength = self.detect_price_rejection()
        
        # Detect quote stuffing
        is_stuffing = cancellation_rate > self.stuffing_threshold or (is_flash and cancellation_rate > self.min_changes_per_sec)
        
        # Update stuffing state
        if is_stuffing:
            if not self.stuffing_detected:
                self.stuffing_detected = True
                self.stuffing_start_time = current_time
                # Determine stuffing direction from flash depth
                if is_flash:
                    self.stuffing_direction = flash_direction
        
        # Reset stuffing if too old
        if self.stuffing_detected and (current_time - self.stuffing_start_time) > 30:
            self.stuffing_detected = False
            self.stuffing_direction = None
        
        signal = None
        confidence = 0.0
        reason = ""
        
        # Generate signal when stuffing detected + price rejection
        if self.stuffing_detected and is_rejection:
            # Trade against the stuffing
            # If stuffing was "up" (fake bid depth) and we see rejection at highs = sell
            # If stuffing was "down" (fake ask depth) and we see rejection at lows = buy
            
            if self.stuffing_direction == "up" and rejection_direction == "up":
                # Fake bids + rejection at high = manipulation to push up, fade it
                base_confidence = 0.62
                stuffing_boost = min((cancellation_rate - self.stuffing_threshold) * 0.05, 0.1)
                rejection_boost = min(rejection_strength * 10, 0.1)
                
                confidence = base_confidence + stuffing_boost + rejection_boost
                confidence = min(confidence, 0.85)
                
                if confidence >= self.min_confidence:
                    signal = "down"
                    reason = f"Quote stuffing UP detected (rate={cancellation_rate:.1f}/s) + price rejection, fade it"
            
            elif self.stuffing_direction == "down" and rejection_direction == "down":
                # Fake asks + rejection at low = manipulation to push down, fade it
                base_confidence = 0.62
                stuffing_boost = min((cancellation_rate - self.stuffing_threshold) * 0.05, 0.1)
                rejection_boost = min(rejection_strength * 10, 0.1)
                
                confidence = base_confidence + stuffing_boost + rejection_boost
                confidence = min(confidence, 0.85)
                
                if confidence >= self.min_confidence:
                    signal = "up"
                    reason = f"Quote stuffing DOWN detected (rate={cancellation_rate:.1f}/s) + price rejection, fade it"
        
        # Alternative: High cancellation rate + flash depth without rejection
        elif is_stuffing and is_flash and not self.stuffing_detected:
            # Initial stuffing detection - prepare for fade
            if flash_direction == "up":
                # Flash bid depth = likely to be pulled, expect down move
                confidence = 0.60
                signal = "down"
                reason = f"Flash bid depth detected (rate={cancellation_rate:.1f}/s), expect fade"
            else:
                # Flash ask depth = likely to be pulled, expect up move
                confidence = 0.60
                signal = "up"
                reason = f"Flash ask depth detected (rate={cancellation_rate:.1f}/s), expect fade"
        
        if signal and confidence >= self.min_confidence:
            self.last_signal_time = current_time
            
            return Signal(
                strategy=self.name,
                signal=signal,
                confidence=confidence,
                reason=reason,
                metadata={
                    'cancellation_rate': cancellation_rate,
                    'is_stuffing': is_stuffing,
                    'is_flash': is_flash,
                    'flash_direction': flash_direction,
                    'is_rejection': is_rejection,
                    'rejection_direction': rejection_direction,
                    'stuffing_detected': self.stuffing_detected
                }
            )
        
        return None
