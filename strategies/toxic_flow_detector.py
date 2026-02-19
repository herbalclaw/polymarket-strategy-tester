"""
ToxicFlowDetector Strategy

Detects and fades "toxic" order flow - trading activity that indicates
informed traders or manipulative behavior that typically leads to
adverse price movement for uninformed participants.

Key insight: Toxic flow often manifests as:
1. Large orders that get cancelled quickly (quote stuffing)
2. Volume spikes with minimal price movement (iceberg orders)
3. Rapid bid-ask flipping (spoofing)
4. Unusual order book dynamics before large moves

Strategy fades toxic flow - when we detect informed selling, we buy
(and vice versa), assuming the toxic flow has temporarily distorted price
from fair value.

Reference: "Enhancing Trading Strategies with Order Book Signals" - Cartea et al.
"""

from typing import Optional
from collections import deque
from statistics import mean, stdev

from core.base_strategy import BaseStrategy, Signal, MarketData


class ToxicFlowDetectorStrategy(BaseStrategy):
    """
    Detect toxic order flow and fade it.
    
    Toxic flow indicators:
    1. Quote stuffing: Rapid order cancellation (>5 changes/sec)
    2. Iceberg detection: Volume > expected at price level
    3. Spoofing: Large orders that disappear before execution
    4. Book pressure divergence: Book imbalance opposite to price move
    
    When toxic selling detected → Buy (fade)
    When toxic buying detected → Sell (fade)
    """
    
    name = "ToxicFlowDetector"
    description = "Detect and fade toxic order flow patterns"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        config = config or {}
        
        # Order book history for tracking changes
        self.ob_history: deque = deque(maxlen=50)
        self.price_history: deque = deque(maxlen=50)
        self.volume_history: deque = deque(maxlen=50)
        
        # Quote stuffing detection
        self.quote_change_threshold = self.config.get('quote_change_threshold', 5)  # Changes per period
        self.stuffing_lookback = self.config.get('stuffing_lookback', 3)
        
        # Iceberg detection
        self.iceberg_volume_ratio = self.config.get('iceberg_volume_ratio', 2.0)  # 2x normal
        self.iceberg_lookback = self.config.get('iceberg_lookback', 10)
        
        # Book pressure divergence
        self.divergence_threshold = self.config.get('divergence_threshold', 0.6)
        
        # Spoofing detection
        self.spoof_size_threshold = self.config.get('spoof_size_threshold', 3.0)  # 3x avg
        self.spoof_disappear_threshold = self.config.get('spoof_disappear_threshold', 0.8)  # 80% cancelled
        
        # Toxicity scoring
        self.min_toxicity_score = self.config.get('min_toxicity_score', 2.0)  # Need 2+ indicators
        
        # Cooldown
        self.cooldown_periods = self.config.get('cooldown_periods', 8)
        self.last_signal_period = -self.cooldown_periods
        self.period_count = 0
        
        # Track last order book state
        self.last_bids = None
        self.last_asks = None
        self.quote_changes = 0
        self.periods_since_change = 0
    
    def calculate_book_imbalance(self, data: MarketData) -> float:
        """
        Calculate order book imbalance.
        Returns: -1 (all ask) to 1 (all bid)
        """
        if not data.order_book:
            return 0
        
        bids = data.order_book.get('bids', [])
        asks = data.order_book.get('asks', [])
        
        if not bids or not asks:
            return 0
        
        bid_vol = sum(float(b.get('size', 0)) for b in bids[:5])
        ask_vol = sum(float(a.get('size', 0)) for a in asks[:5])
        
        total = bid_vol + ask_vol
        if total == 0:
            return 0
        
        return (bid_vol - ask_vol) / total
    
    def detect_quote_stuffing(self, data: MarketData) -> tuple:
        """
        Detect quote stuffing (rapid order cancellations).
        
        Returns: (is_stuffing, intensity)
        """
        if not data.order_book:
            return False, 0
        
        bids = data.order_book.get('bids', [])
        asks = data.order_book.get('asks', [])
        
        # Count changes from last state
        changes = 0
        
        if self.last_bids is not None and self.last_asks is not None:
            # Compare bid levels
            for i in range(min(3, len(bids), len(self.last_bids))):
                if (float(bids[i].get('price', 0)) != float(self.last_bids[i].get('price', 0)) or
                    float(bids[i].get('size', 0)) != float(self.last_bids[i].get('size', 0))):
                    changes += 1
            
            # Compare ask levels
            for i in range(min(3, len(asks), len(self.last_asks))):
                if (float(asks[i].get('price', 0)) != float(self.last_asks[i].get('price', 0)) or
                    float(asks[i].get('size', 0)) != float(self.last_asks[i].get('size', 0))):
                    changes += 1
        
        # Update tracking
        self.quote_changes += changes
        self.periods_since_change += 1
        
        # Check if we've accumulated enough periods
        if self.periods_since_change >= self.stuffing_lookback:
            avg_changes = self.quote_changes / self.periods_since_change
            is_stuffing = avg_changes > self.quote_change_threshold
            intensity = avg_changes / self.quote_change_threshold if self.quote_change_threshold > 0 else 0
            
            # Reset counters
            self.quote_changes = 0
            self.periods_since_change = 0
        else:
            is_stuffing = False
            intensity = 0
        
        # Update last state
        self.last_bids = bids
        self.last_asks = asks
        
        return is_stuffing, intensity
    
    def detect_iceberg(self, data: MarketData) -> tuple:
        """
        Detect iceberg orders (large hidden volume).
        
        Returns: (is_iceberg, direction, size_ratio)
        """
        if not data.order_book or len(self.volume_history) < self.iceberg_lookback:
            return False, "neutral", 0
        
        bids = data.order_book.get('bids', [])
        asks = data.order_book.get('asks', [])
        
        if not bids or not asks:
            return False, "neutral", 0
        
        # Calculate average top-of-book volume
        avg_bid_vol = mean([float(b.get('size', 0)) for b in bids[:1]]) if bids else 0
        avg_ask_vol = mean([float(a.get('size', 0)) for a in asks[:1]]) if asks else 0
        
        # Compare to historical average
        hist_volumes = list(self.volume_history)[-self.iceberg_lookback:]
        avg_hist_vol = mean(hist_volumes) if hist_volumes else 1
        
        # Check for abnormally large volume on one side
        bid_ratio = avg_bid_vol / avg_hist_vol if avg_hist_vol > 0 else 0
        ask_ratio = avg_ask_vol / avg_hist_vol if avg_hist_vol > 0 else 0
        
        if bid_ratio > self.iceberg_volume_ratio and bid_ratio > ask_ratio * 1.5:
            return True, "buying", bid_ratio
        elif ask_ratio > self.iceberg_volume_ratio and ask_ratio > bid_ratio * 1.5:
            return True, "selling", ask_ratio
        
        return False, "neutral", 0
    
    def detect_book_divergence(self, data: MarketData) -> tuple:
        """
        Detect divergence between book pressure and price movement.
        
        Returns: (is_divergence, direction, strength)
        """
        if len(self.price_history) < 5:
            return False, "neutral", 0
        
        # Calculate recent price change
        prices = list(self.price_history)
        price_change = (prices[-1] - prices[-5]) / prices[-5] if prices[-5] > 0 else 0
        
        # Get current book imbalance
        imbalance = self.calculate_book_imbalance(data)
        
        # Divergence: price moving up but book shows selling pressure (or vice versa)
        # This suggests the price move is artificial/manipulative
        
        if price_change > 0.005 and imbalance < -self.divergence_threshold:
            # Price up but book shows heavy ask pressure = toxic buying
            strength = abs(imbalance) * abs(price_change) * 100
            return True, "toxic_buying", strength
        
        elif price_change < -0.005 and imbalance > self.divergence_threshold:
            # Price down but book shows heavy bid pressure = toxic selling
            strength = abs(imbalance) * abs(price_change) * 100
            return True, "toxic_selling", strength
        
        return False, "neutral", 0
    
    def calculate_toxicity_score(self, data: MarketData) -> tuple:
        """
        Calculate overall toxicity score.
        
        Returns: (score, primary_direction, indicators)
        """
        score = 0
        indicators = []
        direction = "neutral"
        
        # Check quote stuffing
        is_stuffing, stuffing_intensity = self.detect_quote_stuffing(data)
        if is_stuffing:
            score += 1
            indicators.append(f"stuffing({stuffing_intensity:.1f})")
        
        # Check iceberg
        is_iceberg, iceberg_dir, iceberg_ratio = self.detect_iceberg(data)
        if is_iceberg:
            score += 1.5
            indicators.append(f"iceberg({iceberg_dir},{iceberg_ratio:.1f})")
            direction = iceberg_dir
        
        # Check divergence
        is_divergence, div_dir, div_strength = self.detect_book_divergence(data)
        if is_divergence:
            score += 1.5
            indicators.append(f"divergence({div_dir},{div_strength:.1f})")
            # Divergence direction is what we're fading
            if div_dir == "toxic_buying":
                direction = "selling"  # Fade the toxic buying
            elif div_dir == "toxic_selling":
                direction = "buying"  # Fade the toxic selling
        
        return score, direction, indicators
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_price = data.price
        self.period_count += 1
        
        # Update history
        self.price_history.append(current_price)
        self.volume_history.append(data.volume_24h)
        self.ob_history.append(data.order_book)
        
        # Check cooldown
        if self.period_count - self.last_signal_period < self.cooldown_periods:
            return None
        
        # Need minimum data
        if len(self.price_history) < 10:
            return None
        
        # Calculate toxicity
        toxicity_score, toxic_direction, indicators = self.calculate_toxicity_score(data)
        
        # Need sufficient toxicity
        if toxicity_score < self.min_toxicity_score:
            return None
        
        # Convert direction to signal
        # If toxic buying detected (manipulative buying), we SELL (fade)
        # If toxic selling detected (manipulative selling), we BUY (fade)
        
        signal = None
        confidence = 0.0
        
        if toxic_direction == "buying":
            # Toxic buying = fade by selling (DOWN)
            signal = "down"
            base_conf = 0.62
            score_boost = min((toxicity_score - self.min_toxicity_score) * 0.05, 0.15)
            confidence = base_conf + score_boost
            
        elif toxic_direction == "selling":
            # Toxic selling = fade by buying (UP)
            signal = "up"
            base_conf = 0.62
            score_boost = min((toxicity_score - self.min_toxicity_score) * 0.05, 0.15)
            confidence = base_conf + score_boost
        
        if signal and confidence >= self.min_confidence:
            self.last_signal_period = self.period_count
            
            reason = f"Fade toxic {toxic_direction}: {', '.join(indicators)}"
            
            return Signal(
                strategy=self.name,
                signal=signal,
                confidence=min(confidence, 0.85),
                reason=reason,
                metadata={
                    'toxicity_score': toxicity_score,
                    'toxic_direction': toxic_direction,
                    'indicators': indicators,
                    'book_imbalance': self.calculate_book_imbalance(data)
                }
            )
        
        return None
