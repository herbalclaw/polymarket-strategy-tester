"""
Layering Detection Strategy

Detects and exploits layering manipulation in the CLOB.
Layering is when a trader places multiple non-bona fide orders at different price levels
to create false impression of supply/demand, then trades against the resulting price move.

Economic Rationale:
- Layering is a common manipulation technique (38% of market abuse fines globally)
- Creates temporary price distortions that reverse when fake orders are cancelled
- In BTC 5-min markets with retail flow, layering can move prices significantly
- Edge comes from detecting the pattern and fading the manipulation

Validation:
- No lookahead: Uses order book dynamics and cancellation patterns
- No overfit: Based on regulatory research on market manipulation
- Works on single market: Detects manipulation within one order book

Detection Method:
1. Large orders appear at multiple price levels on one side
2. These orders get cancelled quickly without executing
3. Price moves in direction of fake pressure
4. When layers are pulled, price reverses
"""

import time
import numpy as np
from typing import Optional, Dict, List, Tuple
from collections import deque, defaultdict
from core.base_strategy import BaseStrategy, Signal, MarketData


class LayeringDetectionStrategy(BaseStrategy):
    """
    Detects layering manipulation and trades the reversal.
    
    Layering Pattern:
    - Multiple large orders placed at progressively better prices
    - Orders are cancelled within seconds without filling
    - Creates false depth that pushes price in manipulated direction
    - When manipulation stops, price reverts
    
    Strategy: Detect layering, fade the move, profit on reversal.
    """
    
    name = "LayeringDetection"
    version = "1.0.0"
    
    def __init__(self, config: Dict = None):
        super().__init__(config)
        
        # Parameters
        self.order_book_history_len = 30  # 30 snapshots
        self.layer_threshold = 3  # At least 3 levels to be layering
        self.min_size_ratio = 3.0  # Layer size must be 3x average
        self.max_layer_age_seconds = 3  # Layers last < 3 seconds
        self.price_impact_threshold = 0.002  # 0.2% move from layering
        
        self.cooldown_seconds = 30  # Don't trade same manipulation twice
        
        # State
        self.ob_history: deque = deque(maxlen=self.order_book_history_len)
        self.timestamp_history: deque = deque(maxlen=self.order_book_history_len)
        self.last_signal_time = 0
        self.detected_layers: List[Dict] = []
        
    def _analyze_order_book_structure(self, ob: Dict) -> Dict:
        """Analyze order book for layering patterns."""
        
        bids = ob.get('bids', [])
        asks = ob.get('asks', [])
        
        if not bids or not asks:
            return {'has_layering': False}
        
        # Calculate average order size
        all_sizes = [level[1] for level in bids[:5]] + [level[1] for level in asks[:5]]
        avg_size = np.mean(all_sizes) if all_sizes else 1
        
        # Check for layering on bid side (large orders at multiple levels)
        bid_layers = []
        for i, (price, size) in enumerate(bids[:5]):
            if size > avg_size * self.min_size_ratio:
                bid_layers.append({
                    'level': i,
                    'price': price,
                    'size': size,
                    'size_ratio': size / avg_size
                })
        
        # Check for layering on ask side
        ask_layers = []
        for i, (price, size) in enumerate(asks[:5]):
            if size > avg_size * self.min_size_ratio:
                ask_layers.append({
                    'level': i,
                    'price': price,
                    'size': size,
                    'size_ratio': size / avg_size
                })
        
        return {
            'has_layering': len(bid_layers) >= self.layer_threshold or len(ask_layers) >= self.layer_threshold,
            'bid_layers': bid_layers,
            'ask_layers': ask_layers,
            'avg_size': avg_size,
            'bid_layer_count': len(bid_layers),
            'ask_layer_count': len(ask_layers)
        }
    
    def _detect_layering_cancellation(self, current: Dict, previous: Dict, dt: float) -> Optional[str]:
        """
        Detect if layers were cancelled (indicates manipulation).
        Returns 'bid' if bid layers cancelled, 'ask' if ask layers cancelled, None otherwise.
        """
        if dt > self.max_layer_age_seconds:
            return None
        
        # Check for sudden disappearance of large orders
        prev_bids = {level['price']: level['size'] for level in previous.get('bid_layers', [])}
        curr_bids = {level[0]: level[1] for level in current.get('bids', [])}
        
        prev_asks = {level['price']: level['size'] for level in previous.get('ask_layers', [])}
        curr_asks = {level[0]: level[1] for level in current.get('asks', [])}
        
        # Bid layers disappeared
        bid_cancelled = False
        for price, size in prev_bids.items():
            if price not in curr_bids or curr_bids[price] < size * 0.3:
                bid_cancelled = True
                break
        
        # Ask layers disappeared
        ask_cancelled = False
        for price, size in prev_asks.items():
            if price not in curr_asks or curr_asks[price] < size * 0.3:
                ask_cancelled = True
                break
        
        if bid_cancelled and not ask_cancelled:
            return 'bid'
        elif ask_cancelled and not bid_cancelled:
            return 'ask'
        
        return None
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        """Generate signal based on layering detection."""
        
        current_time = time.time()
        
        # Cooldown
        if current_time - self.last_signal_time < self.cooldown_seconds:
            return None
        
        # Need order book
        if not data.order_book:
            return None
        
        ob = data.order_book
        
        # Analyze current structure
        analysis = self._analyze_order_book_structure(ob)
        
        # Store history
        self.ob_history.append({
            'analysis': analysis,
            'mid': (data.bid + data.ask) / 2,
            'spread_bps': (data.ask - data.bid) / ((data.bid + data.ask) / 2) * 10000
        })
        self.timestamp_history.append(current_time)
        
        # Need history
        if len(self.ob_history) < 3:
            return None
        
        # Check for layering pattern
        if not analysis['has_layering']:
            return None
        
        # Look for recent cancellation of layers
        prev_ob = self.ob_history[-2]
        prev_time = self.timestamp_history[-2]
        dt = current_time - prev_time
        
        cancellation = self._detect_layering_cancellation(ob, prev_ob['analysis'], dt)
        
        if not cancellation:
            return None
        
        # Layers were cancelled - manipulation detected
        # Trade against the manipulation (fade the move)
        
        # Calculate price impact
        current_mid = (data.bid + data.ask) / 2
        price_history = [h['mid'] for h in list(self.ob_history)[-5:]]
        
        if len(price_history) < 2:
            return None
        
        price_change = (current_mid - price_history[0]) / price_history[0]
        
        # If bid layers were cancelled, price was pushed down artificially -> buy (up)
        # If ask layers were cancelled, price was pushed up artificially -> sell (down)
        
        signal = None
        confidence = 0.0
        reason = ""
        
        if cancellation == 'bid' and price_change < -self.price_impact_threshold:
            # Bid layers cancelled, price dropped -> reversal up
            signal = 'up'
            confidence = min(0.9, 0.65 + abs(price_change) * 50)
            reason = f"Bid layering cancelled, artificial drop {price_change:.3f}, fading"
            
        elif cancellation == 'ask' and price_change > self.price_impact_threshold:
            # Ask layers cancelled, price rose -> reversal down
            signal = 'down'
            confidence = min(0.9, 0.65 + abs(price_change) * 50)
            reason = f"Ask layering cancelled, artificial rise {price_change:.3f}, fading"
        
        if signal:
            self.last_signal_time = current_time
            return Signal(
                strategy=self.name,
                signal=signal,
                confidence=confidence,
                reason=reason,
                metadata={
                    'cancellation_side': cancellation,
                    'price_change': price_change,
                    'bid_layers': analysis['bid_layer_count'],
                    'ask_layers': analysis['ask_layer_count'],
                    'layer_age_seconds': dt
                }
            )
        
        return None
