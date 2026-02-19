"""
OrderBookImbalance Strategy

Exploits order book microstructure to predict short-term price movements.
Based on the well-documented relationship between order book imbalance (OBI)
and future price changes.

Key insight: When bid volume significantly exceeds ask volume (OBI > 0.6),
upward price pressure is likely. Conversely, when ask volume exceeds bid
volume (OBI < -0.6), downward pressure is likely.

Reference: Cont et al. (2014) - Order book imbalance explains ~65% of 
short-interval price variance in equity markets. Similar dynamics apply
to prediction markets.
"""

from typing import Optional
from collections import deque
import statistics

from core.base_strategy import BaseStrategy, Signal, MarketData


class OrderBookImbalanceStrategy(BaseStrategy):
    """
    Trade based on order book imbalance signals.
    
    OBI = (BidVolume - AskVolume) / (BidVolume + AskVolume)
    
    When OBI > 0.65: Buy pressure dominates, expect price increase
    When OBI < -0.65: Sell pressure dominates, expect price decrease
    
    Strategy uses multi-level order book (top 5 levels) for better
    prediction accuracy and includes momentum confirmation.
    """
    
    name = "OrderBookImbalance"
    description = "Order book imbalance microstructure alpha"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        
        # Order book levels to consider
        self.depth_levels = self.config.get('depth_levels', 5)
        
        # Imbalance thresholds
        self.imbalance_threshold = self.config.get('imbalance_threshold', 0.60)
        self.strong_imbalance = self.config.get('strong_imbalance', 0.75)
        
        # Volume-weighted price calculation
        self.use_vwap = self.config.get('use_vwap', True)
        
        # Momentum confirmation
        self.use_momentum = self.config.get('use_momentum', True)
        self.momentum_window = self.config.get('momentum_window', 5)
        
        # History tracking
        self.obi_history = deque(maxlen=20)
        self.price_history = deque(maxlen=20)
        self.last_signal_time = 0
        self.cooldown_seconds = self.config.get('cooldown_seconds', 60)
        
        # Minimum volume requirement
        self.min_total_volume = self.config.get('min_total_volume', 1000)
    
    def calculate_obi(self, data: MarketData) -> tuple:
        """
        Calculate order book imbalance.
        Returns (obi_score, total_volume, bid_volume, ask_volume)
        """
        if not data.order_book:
            return 0.0, 0.0, 0.0, 0.0
        
        bids = data.order_book.get('bids', [])
        asks = data.order_book.get('asks', [])
        
        if not bids or not asks:
            return 0.0, 0.0, 0.0, 0.0
        
        # Calculate volume at specified depth levels
        bid_volume = sum(float(b.get('size', 0)) for b in bids[:self.depth_levels])
        ask_volume = sum(float(a.get('size', 0)) for a in asks[:self.depth_levels])
        
        total_volume = bid_volume + ask_volume
        
        if total_volume < self.min_total_volume:
            return 0.0, total_volume, bid_volume, ask_volume
        
        # Calculate imbalance: positive = more bids, negative = more asks
        obi = (bid_volume - ask_volume) / total_volume
        
        return obi, total_volume, bid_volume, ask_volume
    
    def calculate_vamp(self, data: MarketData) -> float:
        """
        Calculate Volume-Adjusted Mid Price.
        VAMP weights price by liquidity on opposite side.
        """
        if not data.order_book:
            return data.mid
        
        bids = data.order_book.get('bids', [])
        asks = data.order_book.get('asks', [])
        
        if not bids or not asks:
            return data.mid
        
        best_bid = float(bids[0].get('price', data.bid))
        best_ask = float(asks[0].get('price', data.ask))
        
        bid_vol = sum(float(b.get('size', 0)) for b in bids[:self.depth_levels])
        ask_vol = sum(float(a.get('size', 0)) for a in asks[:self.depth_levels])
        
        total_vol = bid_vol + ask_vol
        if total_vol == 0:
            return data.mid
        
        # VAMP formula: (P_bid * Q_ask + P_ask * Q_bid) / (Q_bid + Q_ask)
        vamp = (best_bid * ask_vol + best_ask * bid_vol) / total_vol
        
        return vamp
    
    def get_price_momentum(self) -> float:
        """Calculate recent price momentum."""
        if len(self.price_history) < self.momentum_window:
            return 0.0
        
        prices = list(self.price_history)
        recent = prices[-self.momentum_window:]
        
        if len(recent) < 2:
            return 0.0
        
        # Simple momentum: (latest - earliest) / earliest
        momentum = (recent[-1] - recent[0]) / recent[0] if recent[0] > 0 else 0.0
        return momentum
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_time = data.timestamp
        
        # Cooldown check
        if current_time - self.last_signal_time < self.cooldown_seconds:
            return None
        
        # Update price history
        self.price_history.append(data.price)
        
        # Calculate OBI
        obi, total_vol, bid_vol, ask_vol = self.calculate_obi(data)
        self.obi_history.append(obi)
        
        # Need minimum volume
        if total_vol < self.min_total_volume:
            return None
        
        # Need OBI history for confirmation
        if len(self.obi_history) < 3:
            return None
        
        # Calculate average OBI over recent periods
        recent_obi = statistics.mean(list(self.obi_history)[-3:])
        
        # Calculate VAMP for price reference
        vamp = self.calculate_vamp(data) if self.use_vwap else data.mid
        
        signal = None
        confidence = 0.0
        reason = ""
        
        # Strong bid imbalance -> expect price increase
        if recent_obi > self.imbalance_threshold:
            # Confirm with momentum if enabled
            momentum_ok = True
            if self.use_momentum and len(self.price_history) >= self.momentum_window:
                momentum = self.get_price_momentum()
                momentum_ok = momentum > -0.001  # Not strongly against us
            
            if momentum_ok:
                # Higher confidence for stronger imbalance
                base_confidence = 0.60
                imbalance_boost = min(abs(recent_obi) * 0.2, 0.15)
                
                confidence = base_confidence + imbalance_boost
                
                # Extra boost for very strong imbalance
                if recent_obi > self.strong_imbalance:
                    confidence += 0.05
                
                confidence = min(confidence, 0.85)
                signal = "up"
                reason = f"OBI {recent_obi:.2f} (bid vol: {bid_vol:.0f}, ask vol: {ask_vol:.0f})"
        
        # Strong ask imbalance -> expect price decrease
        elif recent_obi < -self.imbalance_threshold:
            # Confirm with momentum if enabled
            momentum_ok = True
            if self.use_momentum and len(self.price_history) >= self.momentum_window:
                momentum = self.get_price_momentum()
                momentum_ok = momentum < 0.001  # Not strongly against us
            
            if momentum_ok:
                # Higher confidence for stronger imbalance
                base_confidence = 0.60
                imbalance_boost = min(abs(recent_obi) * 0.2, 0.15)
                
                confidence = base_confidence + imbalance_boost
                
                # Extra boost for very strong imbalance
                if recent_obi < -self.strong_imbalance:
                    confidence += 0.05
                
                confidence = min(confidence, 0.85)
                signal = "down"
                reason = f"OBI {recent_obi:.2f} (bid vol: {bid_vol:.0f}, ask vol: {ask_vol:.0f})"
        
        if signal and confidence >= self.min_confidence:
            self.last_signal_time = current_time
            
            return Signal(
                strategy=self.name,
                signal=signal,
                confidence=confidence,
                reason=reason,
                metadata={
                    'obi': recent_obi,
                    'raw_obi': obi,
                    'bid_volume': bid_vol,
                    'ask_volume': ask_vol,
                    'total_volume': total_vol,
                    'vamp': vamp,
                    'mid': data.mid,
                    'depth_levels': self.depth_levels
                }
            )
        
        return None
