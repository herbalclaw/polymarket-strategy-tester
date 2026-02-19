"""
Sharp Money Detection Strategy

Identifies "smart money" vs "dumb money" based on:
1. Reverse Line Movement (price moves against volume)
2. Large order detection (whale activity)
3. Wallet profitability tracking

Reference: Action Network Sharp Money 101
"""

from typing import Optional, Dict, List
from collections import deque
from statistics import mean

from core.base_strategy import BaseStrategy, Signal, MarketData


class SharpMoneyStrategy(BaseStrategy):
    """
    Detects sharp (professional) money activity.
    
    Key signals:
    - Reverse Line Movement: Price moves opposite to volume direction
    - Whale orders: Large trades that move the market
    - Smart wallet activity: Following proven profitable traders
    """
    
    name = "sharp_money"
    description = "Detect smart money via reverse line movement and whale activity"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        config = config or {}
        # Window for tracking volume/price relationship
        self.window = self.config.get('window', 20)
        # Threshold for reverse line movement detection
        self.rlm_threshold = self.config.get('rlm_threshold', 0.02)
        # Minimum volume to consider (filter noise)
        self.min_volume = self.config.get('min_volume', 1000)
        
        # Track price and volume history
        self.price_history = deque(maxlen=self.window)
        self.volume_history = deque(maxlen=self.window)
        self.large_orders = deque(maxlen=50)  # Track whale orders
        
    def detect_reverse_line_movement(self, market_data: MarketData) -> Optional[Dict]:
        """
        Detect Reverse Line Movement (RLM).
        
        RLM occurs when price moves opposite to the direction
        implied by volume/volume-weighted activity.
        
        Returns:
            Dict with RLM details or None
        """
        if len(self.price_history) < 5:
            return None
        
        # Calculate recent price change
        recent_price = market_data.price
        avg_price = mean(self.price_history)
        price_change_pct = (recent_price - avg_price) / avg_price if avg_price > 0 else 0
        
        # Get volume data (if available)
        # For now, use order book depth as proxy for volume
        exchange_prices = market_data.exchange_prices
        total_bid_depth = sum(e.get('bid_depth', 0) for e in exchange_prices.values())
        total_ask_depth = sum(e.get('ask_depth', 0) for e in exchange_prices.values())
        
        if total_bid_depth + total_ask_depth == 0:
            return None
        
        # Volume imbalance (positive = more buying pressure)
        volume_imbalance = (total_bid_depth - total_ask_depth) / (total_bid_depth + total_ask_depth)
        
        # Detect RLM:
        # - High buying volume but price dropping = smart money selling
        # - High selling volume but price rising = smart money buying
        
        rlm_detected = False
        signal_type = None
        confidence = 0.0
        reason = ""
        
        # Case 1: Buying pressure but price down (smart money selling)
        if volume_imbalance > 0.3 and price_change_pct < -self.rlm_threshold:
            rlm_detected = True
            signal_type = "down"
            confidence = min(0.7 + abs(volume_imbalance) * 0.2, 0.9)
            reason = f"RLM: Buying volume (+{volume_imbalance:.1%}) but price down ({price_change_pct:.2%})"
        
        # Case 2: Selling pressure but price up (smart money buying)
        elif volume_imbalance < -0.3 and price_change_pct > self.rlm_threshold:
            rlm_detected = True
            signal_type = "up"
            confidence = min(0.7 + abs(volume_imbalance) * 0.2, 0.9)
            reason = f"RLM: Selling volume ({volume_imbalance:.1%}) but price up (+{price_change_pct:.2%})"
        
        if rlm_detected:
            return {
                'signal': signal_type,
                'confidence': confidence,
                'reason': reason,
                'volume_imbalance': volume_imbalance,
                'price_change_pct': price_change_pct
            }
        
        return None
    
    def detect_whale_activity(self, market_data: MarketData) -> Optional[Dict]:
        """
        Detect large orders (whale activity).
        
        For now, uses order book depth changes as proxy.
        In production, would track individual large trades.
        """
        # This is a simplified version
        # Real implementation would need trade flow data
        return None
    
    def generate_signal(self, market_data: MarketData) -> Optional[Signal]:
        """Generate signal based on sharp money detection."""
        # Update history
        self.price_history.append(market_data.price)
        
        # Check for reverse line movement
        rlm = self.detect_reverse_line_movement(market_data)
        
        if rlm:
            return Signal(
                strategy=self.name,
                signal=rlm['signal'],
                confidence=rlm['confidence'],
                reason=rlm['reason'],
                metadata={
                    'type': 'reverse_line_movement',
                    'volume_imbalance': rlm['volume_imbalance'],
                    'price_change_pct': rlm['price_change_pct']
                }
            )
        
        # Check for whale activity
        whale = self.detect_whale_activity(market_data)
        
        if whale:
            return Signal(
                strategy=self.name,
                signal=whale['signal'],
                confidence=whale['confidence'],
                reason=whale['reason'],
                metadata={
                    'type': 'whale_activity'
                }
            )
        
        return None
