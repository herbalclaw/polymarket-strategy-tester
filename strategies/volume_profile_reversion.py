"""
VolumeProfileReversion Strategy

Exploits volume profile imbalances in prediction markets.
When volume is heavily skewed to one side (buying or selling),
it often indicates retail herding behavior that creates 
temporary price distortions. These distortions tend to revert
as informed traders absorb the flow.

Key insight: Volume profile analysis reveals:
1. Heavy buying volume without price follow-through = overbought
2. Heavy selling volume without price breakdown = oversold
3. Volume climax often marks turning points
4. Delta (buy volume - sell volume) divergence from price

Reference: Volume profile analysis from futures/spot markets
adapted for prediction market microstructure.
"""

from typing import Optional
from collections import deque
import statistics

from core.base_strategy import BaseStrategy, Signal, MarketData


class VolumeProfileReversionStrategy(BaseStrategy):
    """
    Trade volume profile imbalances and divergences.
    
    Strategy logic:
    1. Track buy vs sell volume (delta) over recent periods
    2. Compare volume delta to price movement
    3. Divergence = potential reversal signal:
       - Heavy buying + flat/down price = sellers absorbing = bearish
       - Heavy selling + flat/up price = buyers absorbing = bullish
    4. Volume climax detection for exhaustion trades
    
    Edge comes from fading retail herding behavior.
    """
    
    name = "VolumeProfileReversion"
    description = "Fade volume profile imbalances and divergences"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        
        # Volume tracking
        self.volume_history = deque(maxlen=30)
        self.delta_history = deque(maxlen=20)  # Buy - Sell volume
        self.price_history = deque(maxlen=30)
        
        # Thresholds
        self.delta_threshold = self.config.get('delta_threshold', 0.6)  # 60% imbalance
        self.climax_multiplier = self.config.get('climax_multiplier', 2.5)  # 2.5x avg volume
        self.divergence_threshold = self.config.get('divergence_threshold', 0.003)  # 0.3%
        
        # Analysis windows
        self.lookback_periods = self.config.get('lookback_periods', 5)
        self.volume_avg_periods = self.config.get('volume_avg_periods', 10)
        
        # Cooldown
        self.last_signal_time = 0
        self.cooldown_seconds = self.config.get('cooldown_seconds', 60)
        
        # Minimum requirements
        self.min_volume = self.config.get('min_volume', 100)
        self.min_data_points = self.config.get('min_data_points', 10)
        
        # Consecutive signal tracking
        self.consecutive_bullish_delta = 0
        self.consecutive_bearish_delta = 0
    
    def estimate_buy_sell_volume(self, data: MarketData) -> tuple:
        """
        Estimate buy vs sell volume from order book and price data.
        
        Heuristic:
        - If price closer to ask = more buying pressure
        - If price closer to bid = more selling pressure
        - Use order book imbalance as proxy for flow
        """
        if not data.order_book:
            # Fallback: use price position in recent range
            if len(self.price_history) < 2:
                return 0.5, 0.5  # Equal split
            
            prices = list(self.price_history)
            price_range = max(prices) - min(prices)
            if price_range == 0:
                return 0.5, 0.5
            
            position = (data.price - min(prices)) / price_range
            buy_ratio = position
            sell_ratio = 1 - position
            return buy_ratio, sell_ratio
        
        # Use order book imbalance
        bids = data.order_book.get('bids', [])
        asks = data.order_book.get('asks', [])
        
        if not bids or not asks:
            return 0.5, 0.5
        
        bid_vol = sum(float(b.get('size', 0)) for b in bids[:5])
        ask_vol = sum(float(a.get('size', 0)) for a in asks[:5])
        
        total = bid_vol + ask_vol
        if total == 0:
            return 0.5, 0.5
        
        # Estimate: if more bid volume, more selling pressure (hitting bids)
        # If more ask volume, more buying pressure (lifting offers)
        sell_ratio = bid_vol / total
        buy_ratio = ask_vol / total
        
        return buy_ratio, sell_ratio
    
    def calculate_volume_delta(self, data: MarketData) -> dict:
        """
        Calculate volume delta metrics.
        """
        buy_ratio, sell_ratio = self.estimate_buy_sell_volume(data)
        
        # Use 24h volume as base
        volume = data.volume_24h if data.volume_24h > 0 else self.min_volume
        
        buy_vol = volume * buy_ratio
        sell_vol = volume * sell_ratio
        delta = buy_vol - sell_vol
        delta_ratio = delta / volume if volume > 0 else 0
        
        return {
            'buy_volume': buy_vol,
            'sell_volume': sell_vol,
            'delta': delta,
            'delta_ratio': delta_ratio,
            'buy_ratio': buy_ratio,
            'sell_ratio': sell_ratio,
            'total_volume': volume
        }
    
    def detect_volume_climax(self) -> tuple:
        """
        Detect if current volume is a climax (potential reversal).
        Returns: (is_climax, direction)
        """
        if len(self.volume_history) < self.volume_avg_periods:
            return False, "neutral"
        
        volumes = list(self.volume_history)
        avg_volume = statistics.mean(volumes[:-1])  # Exclude current
        current_volume = volumes[-1]
        
        if avg_volume == 0:
            return False, "neutral"
        
        volume_ratio = current_volume / avg_volume
        
        if volume_ratio < self.climax_multiplier:
            return False, "neutral"
        
        # Climax detected - determine direction from delta
        if len(self.delta_history) >= 3:
            recent_deltas = list(self.delta_history)[-3:]
            avg_delta = statistics.mean(recent_deltas)
            
            if avg_delta > 0:
                return True, "buying_climax"  # Heavy buying = potential top
            else:
                return True, "selling_climax"  # Heavy selling = potential bottom
        
        return False, "neutral"
    
    def detect_divergence(self) -> tuple:
        """
        Detect divergence between volume delta and price.
        Returns: (has_divergence, direction, strength)
        """
        if len(self.delta_history) < self.lookback_periods or len(self.price_history) < self.lookback_periods:
            return False, "neutral", 0.0
        
        deltas = list(self.delta_history)[-self.lookback_periods:]
        prices = list(self.price_history)[-self.lookback_periods:]
        
        # Calculate trends
        delta_trend = deltas[-1] - deltas[0]
        price_trend = prices[-1] - prices[0]
        
        # Divergence: delta and price moving in opposite directions
        # or delta strong but price not following
        
        # Case 1: Strong buying delta but price flat/down
        if delta_trend > 0 and price_trend <= 0:
            strength = abs(delta_trend) / statistics.mean([abs(d) for d in deltas]) if deltas else 0
            return True, "bearish", min(strength, 1.0)
        
        # Case 2: Strong selling delta but price flat/up
        if delta_trend < 0 and price_trend >= 0:
            strength = abs(delta_trend) / statistics.mean([abs(d) for d in deltas]) if deltas else 0
            return True, "bullish", min(strength, 1.0)
        
        return False, "neutral", 0.0
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_time = data.timestamp
        
        # Cooldown check
        if current_time - self.last_signal_time < self.cooldown_seconds:
            return None
        
        # Update history
        self.price_history.append(data.price)
        
        # Calculate volume metrics
        vol_metrics = self.calculate_volume_delta(data)
        self.volume_history.append(vol_metrics['total_volume'])
        self.delta_history.append(vol_metrics['delta_ratio'])
        
        if len(self.volume_history) < self.min_data_points:
            return None
        
        signal = None
        confidence = 0.0
        reason = ""
        
        # Check for volume climax
        is_climax, climax_type = self.detect_volume_climax()
        
        if is_climax:
            if climax_type == "buying_climax":
                signal = "down"
                confidence = 0.70
                reason = f"Buying climax: vol {vol_metrics['total_volume']:,.0f} vs avg"
            elif climax_type == "selling_climax":
                signal = "up"
                confidence = 0.70
                reason = f"Selling climax: vol {vol_metrics['total_volume']:,.0f} vs avg"
        
        # Check for divergence (if no climax signal)
        if signal is None:
            has_div, div_direction, div_strength = self.detect_divergence()
            
            if has_div:
                if div_direction == "bearish":
                    signal = "down"
                    confidence = min(0.60 + div_strength * 0.15, 0.78)
                    reason = f"Bearish divergence: delta up but price flat/down (strength: {div_strength:.2f})"
                elif div_direction == "bullish":
                    signal = "up"
                    confidence = min(0.60 + div_strength * 0.15, 0.78)
                    reason = f"Bullish divergence: delta down but price flat/up (strength: {div_strength:.2f})"
        
        # Check for sustained delta imbalance
        if signal is None and len(self.delta_history) >= 3:
            recent_deltas = list(self.delta_history)[-3:]
            avg_delta = statistics.mean(recent_deltas)
            
            if abs(avg_delta) > self.delta_threshold:
                # Sustained imbalance - fade it
                if avg_delta > 0:
                    # Heavy buying - fade
                    signal = "down"
                    confidence = min(0.58 + (avg_delta - self.delta_threshold) * 0.2, 0.72)
                    reason = f"Fade buying imbalance: delta ratio {avg_delta:.2f}"
                else:
                    # Heavy selling - fade
                    signal = "up"
                    confidence = min(0.58 + (abs(avg_delta) - self.delta_threshold) * 0.2, 0.72)
                    reason = f"Fade selling imbalance: delta ratio {avg_delta:.2f}"
        
        if signal and confidence >= self.min_confidence:
            self.last_signal_time = current_time
            
            return Signal(
                strategy=self.name,
                signal=signal,
                confidence=confidence,
                reason=reason,
                metadata={
                    'delta_ratio': vol_metrics['delta_ratio'],
                    'buy_ratio': vol_metrics['buy_ratio'],
                    'total_volume': vol_metrics['total_volume'],
                    'is_climax': is_climax,
                    'has_divergence': has_div if 'has_div' in dir() else False
                }
            )
        
        return None
