"""
AdverseSelectionFilter Strategy

Exploits the concept of adverse selection in market making. When informed
traders trade aggressively, they leave footprints in the order book and
trade flow. By detecting these signals, we can avoid being picked off and
potentially trade alongside informed flow.

Key insight: Large market orders that clear multiple price levels indicate
informed trading. The price impact of these trades contains information about
future price direction.

Reference: "When AI Trading Agents Compete: Adverse Selection" (2025)
"Market making with asymmetric information and inventory risk" - ScienceDirect
"""

from typing import Optional
from collections import deque
import statistics

from core.base_strategy import BaseStrategy, Signal, MarketData


class AdverseSelectionFilterStrategy(BaseStrategy):
    """
    Detect informed trading flow and trade alongside it.
    
    Strategy logic:
    1. Monitor for large aggressive orders (sweeping multiple levels)
    2. Detect unusual trade size relative to recent history
    3. Identify order book changes that suggest informed flow
    4. Trade in direction of detected informed flow
    
    Key signals:
    - Large market buy orders → informed trader thinks price will go up
    - Large market sell orders → informed trader thinks price will go down
    - Order book absorption patterns
    """
    
    name = "AdverseSelectionFilter"
    description = "Trade alongside detected informed order flow"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        config = config or {}
        
        # Trade size analysis
        self.trade_history = deque(maxlen=50)
        self.volume_history = deque(maxlen=20)
        
        # Large trade threshold (multiple of average)
        self.large_trade_multiplier = self.config.get('large_trade_multiplier', 3.0)
        
        # Order book change detection
        self.ob_history = deque(maxlen=10)
        self.price_history = deque(maxlen=20)
        
        # Informed flow detection thresholds
        self.imbalance_threshold = self.config.get('imbalance_threshold', 0.70)
        self.depth_clear_threshold = self.config.get('depth_clear_threshold', 0.30)
        
        # Confirmation
        self.confirmation_count = self.config.get('confirmation_count', 2)
        self.flow_count = 0
        self.last_flow_direction = None
        
        # Cooldown
        self.last_signal_time = 0
        self.cooldown_seconds = self.config.get('cooldown_seconds', 60)
        
        # Minimum volume requirement
        self.min_volume = self.config.get('min_volume', 1000)
    
    def calculate_trade_imbalance(self, data: MarketData) -> tuple:
        """
        Calculate buy/sell imbalance from recent trades if available.
        Returns (imbalance_score, buy_volume, sell_volume)
        """
        # If we have trade data, use it
        if hasattr(data, 'recent_trades') and data.recent_trades:
            trades = data.recent_trades[-20:]  # Last 20 trades
            
            buy_vol = sum(t.get('size', 0) for t in trades if t.get('side') == 'buy')
            sell_vol = sum(t.get('size', 0) for t in trades if t.get('side') == 'sell')
            total_vol = buy_vol + sell_vol
            
            if total_vol > 0:
                imbalance = (buy_vol - sell_vol) / total_vol
                return imbalance, buy_vol, sell_vol
        
        # Fallback: use order book changes as proxy
        return self._estimate_imbalance_from_ob(data)
    
    def _estimate_imbalance_from_ob(self, data: MarketData) -> tuple:
        """
        Estimate trade imbalance from order book changes.
        """
        if not data.order_book:
            return 0.0, 0.0, 0.0
        
        bids = data.order_book.get('bids', [])
        asks = data.order_book.get('asks', [])
        
        if not bids or not asks:
            return 0.0, 0.0, 0.0
        
        # Calculate volume at different depth levels
        bid_vol_l1 = float(bids[0].get('size', 0)) if bids else 0
        ask_vol_l1 = float(asks[0].get('size', 0)) if asks else 0
        
        bid_vol_deep = sum(float(b.get('size', 0)) for b in bids[1:5])
        ask_vol_deep = sum(float(a.get('size', 0)) for a in asks[1:5])
        
        # If L1 is thin relative to deep levels, suggests recent absorption
        total_bid = bid_vol_l1 + bid_vol_deep
        total_ask = ask_vol_l1 + ask_vol_deep
        
        if total_bid + total_ask == 0:
            return 0.0, 0.0, 0.0
        
        # Thin L1 on ask side suggests buying pressure
        # Thin L1 on bid side suggests selling pressure
        ask_thin_ratio = 1 - (ask_vol_l1 / total_ask) if total_ask > 0 else 0
        bid_thin_ratio = 1 - (bid_vol_l1 / total_bid) if total_bid > 0 else 0
        
        # Imbalance: positive = more buying pressure
        imbalance = (ask_thin_ratio - bid_thin_ratio)
        
        # Estimate volumes
        est_buy_vol = max(0, total_ask * ask_thin_ratio)
        est_sell_vol = max(0, total_bid * bid_thin_ratio)
        
        return imbalance, est_buy_vol, est_sell_vol
    
    def detect_aggressive_flow(self, data: MarketData) -> tuple:
        """
        Detect aggressive (informed) order flow.
        
        Returns: (is_aggressive, direction, strength)
        """
        imbalance, buy_vol, sell_vol = self.calculate_trade_imbalance(data)
        total_vol = buy_vol + sell_vol
        
        if total_vol < self.min_volume:
            return False, "neutral", 0.0
        
        # Check for strong imbalance
        if abs(imbalance) > self.imbalance_threshold:
            direction = "up" if imbalance > 0 else "down"
            strength = abs(imbalance)
            return True, direction, strength
        
        # Check for depth clearing pattern
        if data.order_book:
            depth_signal = self._check_depth_clearing(data)
            if depth_signal[0]:
                return depth_signal
        
        return False, "neutral", 0.0
    
    def _check_depth_clearing(self, data: MarketData) -> tuple:
        """
        Check if recent price movement cleared significant depth.
        """
        if len(self.price_history) < 3:
            return False, "neutral", 0.0
        
        prices = list(self.price_history)
        recent_change = (prices[-1] - prices[-3]) / prices[-3] if prices[-3] > 0 else 0
        
        # Large move in short time suggests aggressive flow
        if abs(recent_change) > 0.01:  # 1% move
            direction = "up" if recent_change > 0 else "down"
            strength = min(abs(recent_change) / 0.02, 1.0)  # Normalize to 2%
            return True, direction, strength
        
        return False, "neutral", 0.0
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_time = data.timestamp
        
        # Cooldown check
        if current_time - self.last_signal_time < self.cooldown_seconds:
            return None
        
        # Update history
        self.price_history.append(data.price)
        if hasattr(data, 'volume') and data.volume:
            self.volume_history.append(data.volume)
        if data.order_book:
            self.ob_history.append({
                'timestamp': current_time,
                'bid': data.bid,
                'ask': data.ask,
                'mid': data.mid
            })
        
        # Detect aggressive flow
        is_aggressive, direction, strength = self.detect_aggressive_flow(data)
        
        if is_aggressive:
            # Track consecutive flow
            if self.last_flow_direction == direction:
                self.flow_count += 1
            else:
                self.flow_count = 1
                self.last_flow_direction = direction
            
            if self.flow_count >= self.confirmation_count:
                # Calculate confidence
                base_conf = 0.60
                strength_boost = min(strength * 0.15, 0.15)
                confirmation_boost = min((self.flow_count - 1) * 0.03, 0.06)
                
                confidence = min(base_conf + strength_boost + confirmation_boost, 0.85)
                
                imbalance, buy_vol, sell_vol = self.calculate_trade_imbalance(data)
                
                self.last_signal_time = current_time
                
                return Signal(
                    strategy=self.name,
                    signal=direction,
                    confidence=confidence,
                    reason=f"Informed flow detected: {direction} (strength: {strength:.2f}, imbalance: {imbalance:.2f})",
                    metadata={
                        'direction': direction,
                        'strength': strength,
                        'imbalance': imbalance,
                        'buy_volume': buy_vol,
                        'sell_volume': sell_vol,
                        'flow_count': self.flow_count
                    }
                )
        else:
            # Reset flow tracking
            self.flow_count = 0
            self.last_flow_direction = None
        
        return None
