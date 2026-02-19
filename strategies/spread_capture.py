"""
SpreadCapture Strategy

Captures the bid-ask spread in Polymarket's CLOB by:
1. Detecting when spread widens beyond normal levels
2. Trading at favorable prices within the spread
3. Capturing micro-inefficiencies in price formation

Key insight: In prediction markets, spreads often widen during:
- High volatility periods
- Low liquidity periods
- Information events

The strategy acts as a micro-market maker, providing liquidity
when spreads are wide and capturing the edge when they narrow.

Reference: Market making research - "Make the spread when it's wide"
"""

from typing import Optional
from collections import deque
import statistics

from core.base_strategy import BaseStrategy, Signal, MarketData


class SpreadCaptureStrategy(BaseStrategy):
    """
    Capture bid-ask spread expansion and contraction.
    
    Strategy logic:
    1. Track normal spread levels for the market
    2. When spread widens > 1.5x normal + price near mid:
       - Buy at bid if we expect spread to narrow
       - Sell at ask if we expect spread to narrow
    3. Capture the spread contraction edge
    
    Also detects "spread skew" - when bid or ask side is
    significantly larger, indicating directional pressure.
    """
    
    name = "SpreadCapture"
    description = "Capture bid-ask spread micro-inefficiencies"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        
        # Spread tracking
        self.spread_history = deque(maxlen=50)
        self.spread_threshold_mult = self.config.get('spread_threshold_mult', 1.5)
        self.min_spread_bps = self.config.get('min_spread_bps', 10)  # 0.1%
        self.max_spread_bps = self.config.get('max_spread_bps', 100)  # 1.0%
        
        # Price position within spread
        self.mid_proximity_threshold = self.config.get('mid_proximity_threshold', 0.3)
        
        # Volume imbalance for directional bias
        self.imbalance_threshold = self.config.get('imbalance_threshold', 0.6)
        
        # Recent trade tracking
        self.price_history = deque(maxlen=20)
        self.trade_history = deque(maxlen=20)
        
        # Cooldown
        self.last_signal_time = 0
        self.cooldown_seconds = self.config.get('cooldown_seconds', 45)
        
        # Consecutive signals tracking
        self.consecutive_signals = 0
        self.last_signal_side = None
    
    def calculate_spread_bps(self, data: MarketData) -> float:
        """Calculate spread in basis points."""
        if data.mid <= 0:
            return 0
        return ((data.ask - data.bid) / data.mid) * 10000
    
    def get_average_spread(self) -> float:
        """Get average historical spread."""
        if len(self.spread_history) < 10:
            return 20  # Default 20 bps
        return statistics.mean(list(self.spread_history)[-20:])
    
    def get_spread_std(self) -> float:
        """Get spread standard deviation."""
        if len(self.spread_history) < 10:
            return 5
        try:
            return statistics.stdev(list(self.spread_history)[-20:])
        except:
            return 5
    
    def calculate_price_position(self, data: MarketData) -> float:
        """
        Calculate where price is within the spread.
        Returns 0.0 at bid, 1.0 at ask, 0.5 at mid.
        """
        spread = data.ask - data.bid
        if spread <= 0:
            return 0.5
        
        position = (data.price - data.bid) / spread
        return max(0, min(1, position))
    
    def calculate_imbalance(self, data: MarketData) -> float:
        """
        Calculate order book imbalance.
        Returns positive for bid-heavy, negative for ask-heavy.
        """
        if not data.order_book:
            return 0.0
        
        bids = data.order_book.get('bids', [])
        asks = data.order_book.get('asks', [])
        
        if not bids or not asks:
            return 0.0
        
        bid_vol = sum(float(b.get('size', 0)) for b in bids[:5])
        ask_vol = sum(float(a.get('size', 0)) for a in asks[:5])
        
        total = bid_vol + ask_vol
        if total == 0:
            return 0.0
        
        return (bid_vol - ask_vol) / total
    
    def detect_volatility_regime(self) -> str:
        """Detect if we're in high or low volatility regime."""
        if len(self.price_history) < 10:
            return "normal"
        
        prices = list(self.price_history)
        try:
            volatility = statistics.stdev(prices) / statistics.mean(prices)
        except:
            return "normal"
        
        if volatility > 0.03:
            return "high"
        elif volatility < 0.01:
            return "low"
        return "normal"
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_time = data.timestamp
        
        # Cooldown check
        if current_time - self.last_signal_time < self.cooldown_seconds:
            return None
        
        # Update histories
        self.price_history.append(data.price)
        
        # Calculate spread metrics
        spread_bps = self.calculate_spread_bps(data)
        self.spread_history.append(spread_bps)
        
        # Need enough spread history
        if len(self.spread_history) < 10:
            return None
        
        avg_spread = self.get_average_spread()
        spread_std = self.get_spread_std()
        
        # Skip if spread is too small or too large
        if spread_bps < self.min_spread_bps or spread_bps > self.max_spread_bps:
            return None
        
        # Check if spread is abnormally wide
        spread_ratio = spread_bps / avg_spread if avg_spread > 0 else 1.0
        is_wide_spread = spread_ratio > self.spread_threshold_mult
        
        # Calculate price position within spread
        price_position = self.calculate_price_position(data)
        near_mid = abs(price_position - 0.5) < self.mid_proximity_threshold
        
        # Calculate order book imbalance
        imbalance = self.calculate_imbalance(data)
        
        # Get volatility regime
        vol_regime = self.detect_volatility_regime()
        
        signal = None
        confidence = 0.0
        reason = ""
        
        # Wide spread opportunity
        if is_wide_spread and near_mid:
            # Wide spread + near mid = opportunity to capture spread narrowing
            
            if imbalance > self.imbalance_threshold:
                # Bid-heavy: expect price to move up, spread to narrow from ask side
                confidence = min(0.60 + (spread_ratio - 1) * 0.1 + abs(imbalance) * 0.1, 0.80)
                signal = "up"
                reason = f"Wide spread {spread_bps:.0f}bps ({spread_ratio:.1f}x avg), bid-heavy {imbalance:.2f}"
            
            elif imbalance < -self.imbalance_threshold:
                # Ask-heavy: expect price to move down, spread to narrow from bid side
                confidence = min(0.60 + (spread_ratio - 1) * 0.1 + abs(imbalance) * 0.1, 0.80)
                signal = "down"
                reason = f"Wide spread {spread_bps:.0f}bps ({spread_ratio:.1f}x avg), ask-heavy {imbalance:.2f}"
            
            else:
                # Balanced book but wide spread - fade the last move
                if len(self.price_history) >= 5:
                    recent = list(self.price_history)[-5:]
                    short_term_move = recent[-1] - recent[0]
                    
                    if short_term_move > 0.005:  # Recent upward move
                        # Expect pullback
                        confidence = 0.60
                        signal = "down"
                        reason = f"Wide spread fade: {spread_bps:.0f}bps, recent up {short_term_move:.3f}"
                    elif short_term_move < -0.005:  # Recent downward move
                        # Expect bounce
                        confidence = 0.60
                        signal = "up"
                        reason = f"Wide spread fade: {spread_bps:.0f}bps, recent down {abs(short_term_move):.3f}"
        
        # Normal spread but strong imbalance
        elif abs(imbalance) > 0.7 and vol_regime != "high":
            # Strong directional pressure with normal spread
            if imbalance > 0:
                confidence = min(0.60 + (imbalance - 0.7) * 0.3, 0.75)
                signal = "up"
                reason = f"Strong bid imbalance {imbalance:.2f}, spread normal {spread_bps:.0f}bps"
            else:
                confidence = min(0.60 + (abs(imbalance) - 0.7) * 0.3, 0.75)
                signal = "down"
                reason = f"Strong ask imbalance {abs(imbalance):.2f}, spread normal {spread_bps:.0f}bps"
        
        if signal and confidence >= self.min_confidence:
            self.last_signal_time = current_time
            
            return Signal(
                strategy=self.name,
                signal=signal,
                confidence=confidence,
                reason=reason,
                metadata={
                    'spread_bps': spread_bps,
                    'avg_spread_bps': avg_spread,
                    'spread_ratio': spread_ratio,
                    'price_position': price_position,
                    'imbalance': imbalance,
                    'vol_regime': vol_regime
                }
            )
        
        return None
