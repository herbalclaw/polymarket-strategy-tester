"""
FlowToxicityStrategy - VPIN-Based Order Flow Analysis

Measures order flow toxicity using Volume-Synchronized Probability of 
Informed Trading (VPIN). High VPIN indicates toxic flow (informed traders)
which predicts volatility and adverse selection for market makers.

Key insight: When VPIN exceeds threshold, market makers are being adversely
selected, suggesting informed trading. This predicts:
1. Increased volatility
2. Directional price moves
3. Wider spreads as MM protect themselves

Reference: Easley, Lopez de Prado, O'Hara (2012) - VPIN paper
"""

from typing import Optional
from collections import deque
import statistics
import time

from core.base_strategy import BaseStrategy, Signal, MarketData


class FlowToxicityStrategy(BaseStrategy):
    """
    Trade based on order flow toxicity (VPIN).
    
    VPIN measures the probability that order flow is informed.
    High VPIN (>0.6) suggests informed trading and predicts volatility.
    
    Strategy:
    - High VPIN + buy imbalance = expect upward move (follow informed)
    - High VPIN + sell imbalance = expect downward move (follow informed)
    """
    
    name = "FlowToxicity"
    description = "VPIN-based order flow toxicity detection"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        
        # VPIN calculation parameters
        self.volume_buckets = self.config.get('volume_buckets', 50)  # Number of volume buckets
        self.bucket_size = self.config.get('bucket_size', 1000)  # USDC per bucket
        
        # Toxicity thresholds
        self.vpin_threshold = self.config.get('vpin_threshold', 0.55)
        self.high_vpin = self.config.get('high_vpin', 0.70)
        
        # Imbalance thresholds
        self.imbalance_threshold = self.config.get('imbalance_threshold', 0.60)
        
        # Data storage
        self.trade_history = deque(maxlen=500)  # (timestamp, price, size, side)
        self.volume_running = 0.0
        self.current_bucket_buys = 0.0
        self.current_bucket_sells = 0.0
        self.buckets = deque(maxlen=self.volume_buckets)
        
        # Signal timing
        self.last_signal_time = 0
        self.cooldown_seconds = self.config.get('cooldown_seconds', 90)
        
        # Minimum data requirements
        self.min_buckets_for_signal = self.config.get('min_buckets_for_signal', 20)
    
    def _classify_trade(self, price: float, bid: float, ask: float) -> str:
        """
        Classify trade as buy or sell using tick rule.
        Returns 'buy', 'sell', or 'unknown'
        """
        if price >= ask * 0.999:  # Near or at ask
            return 'buy'
        elif price <= bid * 1.001:  # Near or at bid
            return 'sell'
        else:
            # Use mid price comparison
            mid = (bid + ask) / 2
            return 'buy' if price >= mid else 'sell'
    
    def _add_trade(self, timestamp: float, price: float, size: float, side: str):
        """Add trade to current volume bucket."""
        if side == 'buy':
            self.current_bucket_buys += size
        else:
            self.current_bucket_sells += size
        
        self.volume_running += size
        
        # Check if bucket is full
        while self.volume_running >= self.bucket_size:
            # Complete current bucket
            bucket_volume = self.current_bucket_buys + self.current_bucket_sells
            if bucket_volume > 0:
                bucket_imbalance = abs(self.current_bucket_buys - self.current_bucket_sells) / bucket_volume
                self.buckets.append({
                    'buys': self.current_bucket_buys,
                    'sells': self.current_bucket_sells,
                    'volume': bucket_volume,
                    'imbalance': bucket_imbalance
                })
            
            # Start new bucket
            overflow = self.volume_running - self.bucket_size
            if self.current_bucket_buys > self.current_bucket_sells:
                self.current_bucket_buys = overflow * (self.current_bucket_buys / bucket_volume) if bucket_volume > 0 else 0
                self.current_bucket_sells = 0
            else:
                self.current_bucket_sells = overflow * (self.current_bucket_sells / bucket_volume) if bucket_volume > 0 else 0
                self.current_bucket_buys = 0
            
            self.volume_running = overflow
    
    def _calculate_vpin(self) -> tuple:
        """
        Calculate VPIN and net imbalance.
        Returns (vpin, net_imbalance, buy_volume, sell_volume)
        """
        if len(self.buckets) < self.min_buckets_for_signal:
            return 0.0, 0.0, 0.0, 0.0
        
        total_volume = sum(b['volume'] for b in self.buckets)
        total_imbalance = sum(b['imbalance'] * b['volume'] for b in self.buckets)
        
        if total_volume == 0:
            return 0.0, 0.0, 0.0, 0.0
        
        vpin = total_imbalance / total_volume
        
        # Calculate net imbalance direction
        total_buys = sum(b['buys'] for b in self.buckets)
        total_sells = sum(b['sells'] for b in self.buckets)
        
        if total_buys + total_sells > 0:
            net_imbalance = (total_buys - total_sells) / (total_buys + total_sells)
        else:
            net_imbalance = 0.0
        
        return vpin, net_imbalance, total_buys, total_sells
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_time = data.timestamp
        
        # Cooldown check
        if current_time - self.last_signal_time < self.cooldown_seconds:
            return None
        
        # Need order book for trade classification
        if not data.order_book:
            return None
        
        # Classify current price as trade
        side = self._classify_trade(data.price, data.bid, data.ask)
        if side == 'unknown':
            return None
        
        # Add to volume bucket (use mid price as proxy for size)
        # In real implementation, would use actual trade size
        estimated_size = data.volume_24h / 86400 * 5  # Assume 5 seconds of volume
        self._add_trade(current_time, data.price, estimated_size, side)
        
        # Calculate VPIN
        vpin, net_imbalance, buy_vol, sell_vol = self._calculate_vpin()
        
        # Need enough buckets
        if len(self.buckets) < self.min_buckets_for_signal:
            return None
        
        signal = None
        confidence = 0.0
        reason = ""
        
        # High VPIN indicates toxic flow - follow the informed traders
        if vpin >= self.vpin_threshold:
            # Determine direction from net imbalance
            if net_imbalance > self.imbalance_threshold:
                # Buy flow is toxic - expect upward move
                base_confidence = 0.60
                vpin_boost = min((vpin - self.vpin_threshold) * 0.3, 0.15)
                imbalance_boost = min(abs(net_imbalance) * 0.1, 0.05)
                
                confidence = base_confidence + vpin_boost + imbalance_boost
                confidence = min(confidence, 0.85)
                signal = 'up'
                reason = f"Toxic buy flow: VPIN {vpin:.2f}, imbalance {net_imbalance:.2f}"
                
            elif net_imbalance < -self.imbalance_threshold:
                # Sell flow is toxic - expect downward move
                base_confidence = 0.60
                vpin_boost = min((vpin - self.vpin_threshold) * 0.3, 0.15)
                imbalance_boost = min(abs(net_imbalance) * 0.1, 0.05)
                
                confidence = base_confidence + vpin_boost + imbalance_boost
                confidence = min(confidence, 0.85)
                signal = 'down'
                reason = f"Toxic sell flow: VPIN {vpin:.2f}, imbalance {net_imbalance:.2f}"
        
        if signal and confidence >= self.min_confidence:
            self.last_signal_time = current_time
            
            return Signal(
                strategy=self.name,
                signal=signal,
                confidence=confidence,
                reason=reason,
                metadata={
                    'vpin': vpin,
                    'net_imbalance': net_imbalance,
                    'buy_volume': buy_vol,
                    'sell_volume': sell_vol,
                    'buckets_used': len(self.buckets),
                    'threshold': self.vpin_threshold
                }
            )
        
        return None
