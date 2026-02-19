"""
VolumeWeightedMicroprice Strategy

Exploits the relationship between order book depth and price discovery.
The Volume-Weighted Microprice (VWMP) is a more accurate fair value
estimator than the mid-price, especially in markets with asymmetric
liquidity.

Key insight: When VWMP diverges from mid-price, it signals informed
order flow. Trade in the direction of VWMP when the divergence is
significant.

Reference: "The Micro-Price: A High Frequency Estimator of Future Prices"
- Stoikov (2018)
"""

from typing import Optional
from collections import deque
import statistics

from core.base_strategy import BaseStrategy, Signal, MarketData


class VolumeWeightedMicropriceStrategy(BaseStrategy):
    """
    Trade based on Volume-Weighted Microprice divergence.
    
    VWMP weights each price level by the liquidity on the OPPOSITE side
    of the book. This captures the idea that heavy ask volume creates
    resistance to upward moves (hence weighting bids lower).
    
    When VWMP > Mid: Buyers are more aggressive, expect upward pressure
    When VWMP < Mid: Sellers are more aggressive, expect downward pressure
    
    Strategy enters when divergence exceeds threshold and momentum confirms.
    """
    
    name = "VolumeWeightedMicroprice"
    description = "Volume-weighted microprice divergence alpha"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        config = config or {}
        
        # Depth levels for calculation
        self.depth_levels = self.config.get('depth_levels', 3)
        
        # Divergence threshold (in cents)
        self.divergence_threshold = self.config.get('divergence_threshold', 0.005)  # 0.5 cents
        self.strong_divergence = self.config.get('strong_divergence', 0.010)  # 1.0 cent
        
        # Minimum liquidity requirement
        self.min_liquidity = self.config.get('min_liquidity', 500)
        
        # Momentum confirmation
        self.use_momentum = self.config.get('use_momentum', True)
        self.momentum_window = self.config.get('momentum_window', 5)
        
        # History tracking
        self.vwmp_history = deque(maxlen=20)
        self.mid_history = deque(maxlen=20)
        self.divergence_history = deque(maxlen=10)
        
        # Cooldown
        self.last_signal_time = 0
        self.cooldown_seconds = self.config.get('cooldown_seconds', 45)
        
        # Consecutive divergence requirement
        self.min_consecutive = self.config.get('min_consecutive', 2)
        self.consecutive_count = 0
        self.last_divergence_direction = None
    
    def calculate_vwmp(self, data: MarketData) -> float:
        """
        Calculate Volume-Weighted Microprice.
        
        VWMP = (BestBid * AskVolume + BestAsk * BidVolume) / (BidVolume + AskVolume)
        
        This weights each side by the OPPOSITE side's volume, capturing
        the pressure from the contra-side.
        """
        if not data.order_book:
            return data.mid
        
        bids = data.order_book.get('bids', [])
        asks = data.order_book.get('asks', [])
        
        if not bids or not asks:
            return data.mid
        
        best_bid = float(bids[0].get('price', data.bid))
        best_ask = float(asks[0].get('price', data.ask))
        
        # Sum volumes at specified depth
        bid_volume = sum(float(b.get('size', 0)) for b in bids[:self.depth_levels])
        ask_volume = sum(float(a.get('size', 0)) for a in asks[:self.depth_levels])
        
        total_volume = bid_volume + ask_volume
        
        if total_volume < self.min_liquidity:
            return data.mid
        
        # VWMP formula: weight each price by opposite side volume
        vwmp = (best_bid * ask_volume + best_ask * bid_volume) / total_volume
        
        return vwmp
    
    def calculate_weighted_depth_price(self, data: MarketData) -> float:
        """
        Alternative: Weighted-Depth Order Book Price.
        Weights each level by its own volume (different from VWMP).
        """
        if not data.order_book:
            return data.mid
        
        bids = data.order_book.get('bids', [])
        asks = data.order_book.get('asks', [])
        
        if not bids or not asks:
            return data.mid
        
        # Calculate weighted prices
        bid_weighted_sum = sum(float(b.get('price', 0)) * float(b.get('size', 0)) 
                               for b in bids[:self.depth_levels])
        ask_weighted_sum = sum(float(a.get('price', 0)) * float(a.get('size', 0)) 
                               for a in asks[:self.depth_levels])
        
        bid_volume = sum(float(b.get('size', 0)) for b in bids[:self.depth_levels])
        ask_volume = sum(float(a.get('size', 0)) for a in asks[:self.depth_levels])
        
        total_volume = bid_volume + ask_volume
        
        if total_volume < self.min_liquidity:
            return data.mid
        
        weighted_price = (bid_weighted_sum + ask_weighted_sum) / total_volume
        return weighted_price
    
    def get_momentum(self) -> float:
        """Calculate price momentum from history."""
        if len(self.mid_history) < self.momentum_window:
            return 0.0
        
        prices = list(self.mid_history)
        recent = prices[-self.momentum_window:]
        
        if len(recent) < 2 or recent[0] == 0:
            return 0.0
        
        return (recent[-1] - recent[0]) / recent[0]
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_time = data.timestamp
        
        # Cooldown check
        if current_time - self.last_signal_time < self.cooldown_seconds:
            return None
        
        # Calculate VWMP
        vwmp = self.calculate_vwmp(data)
        mid = data.mid
        
        # Update history
        self.vwmp_history.append(vwmp)
        self.mid_history.append(mid)
        
        # Calculate divergence
        divergence = vwmp - mid  # Positive = VWMP above mid
        self.divergence_history.append(divergence)
        
        # Need minimum history
        if len(self.vwmp_history) < 3:
            return None
        
        # Track consecutive divergences
        current_direction = None
        if divergence > self.divergence_threshold:
            current_direction = "up"
        elif divergence < -self.divergence_threshold:
            current_direction = "down"
        
        if current_direction == self.last_divergence_direction and current_direction is not None:
            self.consecutive_count += 1
        else:
            self.consecutive_count = 1 if current_direction else 0
        
        self.last_divergence_direction = current_direction
        
        signal = None
        confidence = 0.0
        reason = ""
        
        # VWMP > Mid: Buyers more aggressive, expect up move
        if divergence > self.divergence_threshold and self.consecutive_count >= self.min_consecutive:
            momentum_ok = True
            if self.use_momentum:
                momentum = self.get_momentum()
                momentum_ok = momentum > -0.002  # Not strongly against
            
            if momentum_ok:
                base_confidence = 0.58
                div_boost = min(abs(divergence) * 20, 0.12)  # Cap at 0.12
                consecutive_boost = min((self.consecutive_count - 1) * 0.03, 0.06)
                
                confidence = base_confidence + div_boost + consecutive_boost
                
                # Extra boost for strong divergence
                if divergence > self.strong_divergence:
                    confidence += 0.05
                
                confidence = min(confidence, 0.82)
                signal = "up"
                reason = f"VWMP {vwmp:.3f} > Mid {mid:.3f}, div={divergence:.3f}"
        
        # VWMP < Mid: Sellers more aggressive, expect down move
        elif divergence < -self.divergence_threshold and self.consecutive_count >= self.min_consecutive:
            momentum_ok = True
            if self.use_momentum:
                momentum = self.get_momentum()
                momentum_ok = momentum < 0.002  # Not strongly against
            
            if momentum_ok:
                base_confidence = 0.58
                div_boost = min(abs(divergence) * 20, 0.12)
                consecutive_boost = min((self.consecutive_count - 1) * 0.03, 0.06)
                
                confidence = base_confidence + div_boost + consecutive_boost
                
                # Extra boost for strong divergence
                if divergence < -self.strong_divergence:
                    confidence += 0.05
                
                confidence = min(confidence, 0.82)
                signal = "down"
                reason = f"VWMP {vwmp:.3f} < Mid {mid:.3f}, div={divergence:.3f}"
        
        if signal and confidence >= self.min_confidence:
            self.last_signal_time = current_time
            
            return Signal(
                strategy=self.name,
                signal=signal,
                confidence=confidence,
                reason=reason,
                metadata={
                    'vwmp': vwmp,
                    'mid': mid,
                    'divergence': divergence,
                    'consecutive': self.consecutive_count,
                    'momentum': self.get_momentum() if self.use_momentum else None
                }
            )
        
        return None
