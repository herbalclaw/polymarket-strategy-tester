"""
TimeWeightedMicrostructure Strategy

Exploits time-weighted order book imbalances and microstructure patterns.
Combines order flow toxicity (VPIN) with time-weighted average price (TWAP)
deviations to identify informed trading activity.

Key insight: Informed traders leave footprints in the order book through:
1. Persistent order flow imbalance (more aggressive buys than sells)
2. Time-weighted volume concentration at specific price levels
3. VPIN (Volume-synchronized Probability of Informed Trading) spikes

This strategy detects these footprints and trades in the direction of
informed flow before prices fully adjust.

Reference: "Flow Toxicity and Volatility in a High Frequency World" - Easley et al.
"""

from typing import Optional, Dict, List
from collections import deque
from statistics import mean, stdev
import math

from core.base_strategy import BaseStrategy, Signal, MarketData


class TimeWeightedMicrostructureStrategy(BaseStrategy):
    """
    Exploits time-weighted order book patterns and informed trading footprints.
    
    Strategy components:
    1. VPIN calculation: Volume-synchronized probability of informed trading
    2. Order flow toxicity: Buy vs sell volume imbalance over time
    3. Time-weighted depth: Where volume accumulates over time
    4. Microprice deviation: Weighted mid-price vs simple mid-price
    
    Trade when VPIN exceeds threshold AND order flow confirms direction.
    """
    
    name = "TimeWeightedMicrostructure"
    description = "Time-weighted order book microstructure and VPIN"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        config = config or {}
        
        # VPIN parameters
        self.vpin_buckets = self.config.get('vpin_buckets', 50)  # Volume buckets
        self.vpin_threshold = self.config.get('vpin_threshold', 0.35)  # VPIN > 0.35 = toxic flow
        
        # Order flow tracking
        self.flow_window = self.config.get('flow_window', 20)
        self.flow_history: deque = deque(maxlen=100)
        
        # Volume tracking
        self.volume_history: deque = deque(maxlen=50)
        self.buy_volume_history: deque = deque(maxlen=50)
        self.sell_volume_history: deque = deque(maxlen=50)
        
        # Price history
        self.price_history: deque = deque(maxlen=50)
        self.microprice_history: deque = deque(maxlen=50)
        
        # Time-weighted metrics
        self.time_weighted_bid_depth: deque = deque(maxlen=30)
        self.time_weighted_ask_depth: deque = deque(maxlen=30)
        
        # Thresholds
        self.flow_imbalance_threshold = self.config.get('flow_imbalance_threshold', 0.20)
        self.min_volume = self.config.get('min_volume', 1000)
        
        # Cooldown
        self.cooldown_periods = self.config.get('cooldown_periods', 5)
        self.last_signal_period = -self.cooldown_periods
        self.period_count = 0
        
        # Bucket volume for VPIN
        self.current_bucket_volume = 0
        self.bucket_buys = 0
        self.bucket_sells = 0
        self.bucket_size = self.config.get('bucket_size', 1000)  # Volume per bucket
    
    def calculate_microprice(self, order_book: Dict) -> Optional[float]:
        """
        Calculate microprice (volume-weighted mid-price).
        
        Microprice = (P_ask * V_bid + P_bid * V_ask) / (V_bid + V_ask)
        
        This weights the mid-price by liquidity on the opposite side,
        giving more weight to the side with less liquidity (more likely to move).
        """
        if not order_book:
            return None
        
        bids = order_book.get('bids', [])
        asks = order_book.get('asks', [])
        
        if not bids or not asks:
            return None
        
        best_bid = float(bids[0].get('price', 0))
        best_ask = float(asks[0].get('price', 0))
        bid_size = float(bids[0].get('size', 0))
        ask_size = float(asks[0].get('size', 0))
        
        if best_bid <= 0 or best_ask <= 0 or bid_size + ask_size == 0:
            return None
        
        # Volume-weighted microprice
        microprice = (best_ask * bid_size + best_bid * ask_size) / (bid_size + ask_size)
        
        return microprice
    
    def calculate_vpin(self) -> float:
        """
        Calculate Volume-synchronized Probability of Informed Trading.
        
        VPIN = |Buy_volume - Sell_volume| / Total_volume
        
        Higher VPIN = more toxic flow (informed trading likely).
        """
        if len(self.flow_history) < self.vpin_buckets:
            return 0.0
        
        recent_flows = list(self.flow_history)[-self.vpin_buckets:]
        
        total_volume = sum(abs(f['buy_vol']) + abs(f['sell_vol']) for f in recent_flows)
        if total_volume == 0:
            return 0.0
        
        imbalance = sum(abs(f['buy_vol'] - f['sell_vol']) for f in recent_flows)
        
        vpin = imbalance / total_volume
        return vpin
    
    def calculate_flow_imbalance(self) -> float:
        """
        Calculate order flow imbalance.
        
        Returns value between -1 (all selling) and +1 (all buying).
        """
        if len(self.flow_history) < self.flow_window:
            return 0.0
        
        recent = list(self.flow_history)[-self.flow_window:]
        
        total_buy = sum(f['buy_vol'] for f in recent)
        total_sell = sum(f['sell_vol'] for f in recent)
        total = total_buy + total_sell
        
        if total == 0:
            return 0.0
        
        imbalance = (total_buy - total_sell) / total
        return imbalance
    
    def update_bucket(self, buy_vol: float, sell_vol: float):
        """Update VPIN volume bucket."""
        self.current_bucket_volume += buy_vol + sell_vol
        self.bucket_buys += buy_vol
        self.bucket_sells += sell_vol
        
        # Check if bucket is full
        if self.current_bucket_volume >= self.bucket_size:
            # Record bucket
            self.flow_history.append({
                'buy_vol': self.bucket_buys,
                'sell_vol': self.bucket_buys,
                'total': self.current_bucket_volume
            })
            
            # Reset bucket
            self.current_bucket_volume = 0
            self.bucket_buys = 0
            self.bucket_sells = 0
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_price = data.price
        self.period_count += 1
        
        # Update price history
        self.price_history.append(current_price)
        
        # Calculate microprice
        microprice = self.calculate_microprice(data.order_book)
        if microprice:
            self.microprice_history.append(microprice)
        
        # Estimate buy/sell volume from price movement
        # This is a simplification - real implementation would use trade data
        if len(self.price_history) >= 2:
            prev_price = list(self.price_history)[-2]
            price_change = current_price - prev_price
            
            # Estimate volume split based on price direction
            estimated_volume = data.volume if hasattr(data, 'volume') and data.volume else 100
            
            if price_change > 0:
                buy_vol = estimated_volume * (0.5 + abs(price_change) * 5)
                sell_vol = estimated_volume - buy_vol
            elif price_change < 0:
                sell_vol = estimated_volume * (0.5 + abs(price_change) * 5)
                buy_vol = estimated_volume - sell_vol
            else:
                buy_vol = sell_vol = estimated_volume / 2
            
            buy_vol = max(0, buy_vol)
            sell_vol = max(0, sell_vol)
            
            self.update_bucket(buy_vol, sell_vol)
            self.buy_volume_history.append(buy_vol)
            self.sell_volume_history.append(sell_vol)
        
        # Check cooldown
        if self.period_count - self.last_signal_period < self.cooldown_periods:
            return None
        
        # Need enough data
        if len(self.flow_history) < self.vpin_buckets // 2:
            return None
        
        # Calculate metrics
        vpin = self.calculate_vpin()
        flow_imbalance = self.calculate_flow_imbalance()
        
        # Check VPIN threshold (toxic flow detection)
        if vpin < self.vpin_threshold:
            return None
        
        # Check flow imbalance
        if abs(flow_imbalance) < self.flow_imbalance_threshold:
            return None
        
        # Generate signal in direction of flow
        signal = None
        confidence = 0.0
        reason = ""
        metadata = {}
        
        if flow_imbalance > 0:
            # Buy flow dominates
            base_conf = 0.62
            vpin_boost = min((vpin - self.vpin_threshold) * 0.3, 0.12)
            flow_boost = min((flow_imbalance - self.flow_imbalance_threshold) * 0.3, 0.12)
            
            confidence = base_conf + vpin_boost + flow_boost
            confidence = min(confidence, 0.85)
            
            if confidence >= self.min_confidence:
                signal = "up"
                reason = f"Toxic buy flow: VPIN={vpin:.3f}, imbalance={flow_imbalance:.3f}"
                metadata = {
                    'vpin': vpin,
                    'flow_imbalance': flow_imbalance,
                    'microprice': microprice,
                    'price': current_price
                }
        
        else:
            # Sell flow dominates
            base_conf = 0.62
            vpin_boost = min((vpin - self.vpin_threshold) * 0.3, 0.12)
            flow_boost = min((abs(flow_imbalance) - self.flow_imbalance_threshold) * 0.3, 0.12)
            
            confidence = base_conf + vpin_boost + flow_boost
            confidence = min(confidence, 0.85)
            
            if confidence >= self.min_confidence:
                signal = "down"
                reason = f"Toxic sell flow: VPIN={vpin:.3f}, imbalance={flow_imbalance:.3f}"
                metadata = {
                    'vpin': vpin,
                    'flow_imbalance': flow_imbalance,
                    'microprice': microprice,
                    'price': current_price
                }
        
        if signal and confidence >= self.min_confidence:
            self.last_signal_period = self.period_count
            
            return Signal(
                strategy=self.name,
                signal=signal,
                confidence=confidence,
                reason=reason,
                metadata=metadata
            )
        
        return None
