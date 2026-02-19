"""
SmartMoneyFlow Strategy

Tracks "smart money" signals from order book and trade flow patterns.
Key insights:
1. Large orders at best bid/ask indicate informed trading
2. Aggressive market orders in one direction show conviction
3. Order book refresh patterns reveal algorithmic vs retail flow

Strategy looks for:
- Large bid/ask size increases (institutional accumulation)
- Market order clustering (urgent flow)
- Order book resilience (sweeps that refill quickly)

Reference: Research on informed trading in prediction markets shows that
large order book changes predict price direction with ~55-60% accuracy.
"""

from typing import Optional
from collections import deque
import statistics

from core.base_strategy import BaseStrategy, Signal, MarketData


class SmartMoneyFlowStrategy(BaseStrategy):
    """
    Follow smart money signals from order book dynamics.
    
    Detects:
    - Bid wall building (large orders appearing at bid)
    - Ask absorption (large sells being absorbed without price drop)
    - Sweep resilience (quick refill after market orders)
    
    These patterns indicate informed traders positioning before moves.
    """
    
    name = "SmartMoneyFlow"
    description = "Smart money flow detection"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        config = config or {}
        
        # Order book tracking
        self.bid_history = deque(maxlen=10)
        self.ask_history = deque(maxlen=10)
        self.bid_size_history = deque(maxlen=10)
        self.ask_size_history = deque(maxlen=10)
        
        # Large size threshold (relative to average)
        self.large_size_multiplier = self.config.get('large_size_multiplier', 2.0)
        
        # Minimum absolute size to consider
        self.min_large_size = self.config.get('min_large_size', 1000)
        
        # Sweep detection: how quickly book refills
        self.sweep_recovery_threshold = self.config.get('sweep_recovery_threshold', 0.7)
        
        # Cooldown
        self.last_signal_time = 0
        self.cooldown_seconds = self.config.get('cooldown_seconds', 60)
        
        # Consecutive signals required
        self.confirmation_needed = self.config.get('confirmation_needed', 2)
        self.up_signals = 0
        self.down_signals = 0
    
    def detect_bid_wall(self, data: MarketData) -> tuple:
        """
        Detect if a significant bid wall has appeared.
        Returns (is_wall, strength) where strength is 0-1
        """
        if not data.order_book or len(self.bid_size_history) < 3:
            return False, 0.0
        
        bids = data.order_book.get('bids', [])
        if not bids:
            return False, 0.0
        
        current_bid_size = float(bids[0].get('size', 0))
        avg_bid_size = statistics.mean(self.bid_size_history)
        
        if avg_bid_size == 0:
            return False, 0.0
        
        # Check if current size is significantly larger
        size_ratio = current_bid_size / avg_bid_size
        is_wall = size_ratio > self.large_size_multiplier and current_bid_size > self.min_large_size
        
        # Strength based on how much larger
        strength = min((size_ratio - 1) / (self.large_size_multiplier - 1), 1.0) if is_wall else 0.0
        
        return is_wall, strength
    
    def detect_ask_wall(self, data: MarketData) -> tuple:
        """
        Detect if a significant ask wall has appeared.
        Returns (is_wall, strength) where strength is 0-1
        """
        if not data.order_book or len(self.ask_size_history) < 3:
            return False, 0.0
        
        asks = data.order_book.get('asks', [])
        if not asks:
            return False, 0.0
        
        current_ask_size = float(asks[0].get('size', 0))
        avg_ask_size = statistics.mean(self.ask_size_history)
        
        if avg_ask_size == 0:
            return False, 0.0
        
        # Check if current size is significantly larger
        size_ratio = current_ask_size / avg_ask_size
        is_wall = size_ratio > self.large_size_multiplier and current_ask_size > self.min_large_size
        
        # Strength based on how much larger
        strength = min((size_ratio - 1) / (self.large_size_multiplier - 1), 1.0) if is_wall else 0.0
        
        return is_wall, strength
    
    def detect_sweep_resilience(self, data: MarketData) -> tuple:
        """
        Detect if order book shows resilience after potential sweep.
        Quick refill of liquidity indicates smart money absorbing flow.
        
        Returns (direction, strength) where direction is 'up', 'down', or None
        """
        if len(self.bid_size_history) < 5 or len(self.ask_size_history) < 5:
            return None, 0.0
        
        bids = list(self.bid_size_history)
        asks = list(self.ask_size_history)
        
        # Look for dip followed by recovery in bids (buy resilience)
        if len(bids) >= 5:
            recent_bids = bids[-3:]
            older_bids = bids[-5:-3]
            
            avg_recent = statistics.mean(recent_bids)
            avg_older = statistics.mean(older_bids)
            
            # If recent is recovering from a dip
            if avg_older > 0 and avg_recent / avg_older > self.sweep_recovery_threshold:
                min_recent = min(recent_bids)
                if min_recent < avg_older * 0.7:  # There was a dip
                    recovery_strength = (avg_recent - min_recent) / avg_older
                    return 'up', min(recovery_strength, 1.0)
        
        # Look for dip followed by recovery in asks (sell resilience)
        if len(asks) >= 5:
            recent_asks = asks[-3:]
            older_asks = asks[-5:-3]
            
            avg_recent = statistics.mean(recent_asks)
            avg_older = statistics.mean(older_asks)
            
            if avg_older > 0 and avg_recent / avg_older > self.sweep_recovery_threshold:
                min_recent = min(recent_asks)
                if min_recent < avg_older * 0.7:
                    recovery_strength = (avg_recent - min_recent) / avg_older
                    return 'down', min(recovery_strength, 1.0)
        
        return None, 0.0
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_time = data.timestamp
        
        # Cooldown check
        if current_time - self.last_signal_time < self.cooldown_seconds:
            return None
        
        # Update history
        if data.order_book:
            bids = data.order_book.get('bids', [])
            asks = data.order_book.get('asks', [])
            
            if bids:
                self.bid_history.append(float(bids[0].get('price', 0)))
                self.bid_size_history.append(float(bids[0].get('size', 0)))
            
            if asks:
                self.ask_history.append(float(asks[0].get('price', 0)))
                self.ask_size_history.append(float(asks[0].get('size', 0)))
        
        # Need enough history
        if len(self.bid_size_history) < 5:
            return None
        
        # Detect signals
        bid_wall, bid_strength = self.detect_bid_wall(data)
        ask_wall, ask_strength = self.detect_ask_wall(data)
        resilience_dir, resilience_strength = self.detect_sweep_resilience(data)
        
        signal = None
        confidence = 0.0
        reason = ""
        
        # Bullish signals
        if bid_wall or resilience_dir == 'up':
            self.up_signals += 1
            self.down_signals = max(0, self.down_signals - 1)
            
            if self.up_signals >= self.confirmation_needed:
                base_conf = 0.58
                wall_boost = bid_strength * 0.1 if bid_wall else 0
                res_boost = resilience_strength * 0.08 if resilience_dir == 'up' else 0
                
                confidence = min(base_conf + wall_boost + res_boost, 0.80)
                signal = "up"
                
                reasons = []
                if bid_wall:
                    reasons.append(f"bid wall ({bid_strength:.0%})")
                if resilience_dir == 'up':
                    reasons.append(f"resilience ({resilience_strength:.0%})")
                reason = "Smart money: " + ", ".join(reasons)
        
        # Bearish signals
        elif ask_wall or resilience_dir == 'down':
            self.down_signals += 1
            self.up_signals = max(0, self.up_signals - 1)
            
            if self.down_signals >= self.confirmation_needed:
                base_conf = 0.58
                wall_boost = ask_strength * 0.1 if ask_wall else 0
                res_boost = resilience_strength * 0.08 if resilience_dir == 'down' else 0
                
                confidence = min(base_conf + wall_boost + res_boost, 0.80)
                signal = "down"
                
                reasons = []
                if ask_wall:
                    reasons.append(f"ask wall ({ask_strength:.0%})")
                if resilience_dir == 'down':
                    reasons.append(f"resilience ({resilience_strength:.0%})")
                reason = "Smart money: " + ", ".join(reasons)
        
        else:
            # Decay signals
            self.up_signals = max(0, self.up_signals - 1)
            self.down_signals = max(0, self.down_signals - 1)
        
        if signal and confidence >= self.min_confidence:
            self.last_signal_time = current_time
            
            return Signal(
                strategy=self.name,
                signal=signal,
                confidence=confidence,
                reason=reason,
                metadata={
                    'bid_wall': bid_wall,
                    'bid_strength': bid_strength,
                    'ask_wall': ask_wall,
                    'ask_strength': ask_strength,
                    'resilience_dir': resilience_dir,
                    'resilience_strength': resilience_strength,
                    'up_signals': self.up_signals,
                    'down_signals': self.down_signals,
                    'price': data.price
                }
            )
        
        return None
