from typing import Optional, Dict, List
from collections import deque
import statistics

from core.base_strategy import BaseStrategy, Signal, MarketData


class MicrostructureScalperStrategy(BaseStrategy):
    """
    Order Book Microstructure Scalping Strategy
    
    Exploits short-term order book imbalances and micro-price movements.
    High-frequency scalping with tight risk controls.
    
    Key signals:
    1. Bid/ask imbalance (heavy side gets hit)
    2. Micro-price momentum (short-term direction)
    3. Spread compression/expansion cycles
    4. Volume at bid vs ask (aggressive buyers/sellers)
    """
    
    name = "MicrostructureScalper"
    description = "High-frequency scalping based on order book microstructure"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        # Price history for micro-momentum
        self.price_history: deque = deque(maxlen=20)
        self.bid_ask_history: deque = deque(maxlen=10)
        
        # Configurable thresholds (aggressive defaults)
        self.imbalance_threshold = self.config.get('imbalance_threshold', 1.2)  # 1.2x more volume on one side
        self.spread_threshold = self.config.get('spread_threshold', 0.02)  # 2 cent spread max for entry
        self.momentum_window = self.config.get('momentum_window', 3)  # 3 samples for momentum
        self.min_confidence = self.config.get('min_confidence', 0.55)  # Lower confidence = more trades
        
        # Risk management
        self.max_trades_per_window = self.config.get('max_trades_per_window', 3)
        self.trades_this_window = 0
        self.current_window = None
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        # Reset trade counter for new window
        window = int(data.timestamp // 300) * 300
        if window != self.current_window:
            self.current_window = window
            self.trades_this_window = 0
        
        # Don't exceed max trades per window
        if self.trades_this_window >= self.max_trades_per_window:
            return None
        
        # Need order book data
        if not data.orderbook:
            return None
        
        bids = data.orderbook.get('bids', [])
        asks = data.orderbook.get('asks', [])
        
        if not bids or not asks:
            return None
        
        best_bid = float(bids[0]['price']) if bids else 0
        best_ask = float(asks[0]['price']) if asks else 0
        
        if best_bid == 0 or best_ask == 0:
            return None
        
        # Calculate spread
        spread = best_ask - best_bid
        mid_price = (best_bid + best_ask) / 2
        spread_pct = spread / mid_price
        
        # Calculate bid/ask volume imbalance
        bid_volume = sum(float(b['size']) for b in bids[:5])  # Top 5 levels
        ask_volume = sum(float(a['size']) for a in asks[:5])
        
        if bid_volume == 0 or ask_volume == 0:
            return None
        
        imbalance = bid_volume / ask_volume
        
        # Store history
        self.price_history.append(mid_price)
        self.bid_ask_history.append({
            'bid': best_bid,
            'ask': best_ask,
            'spread': spread,
            'imbalance': imbalance,
            'bid_vol': bid_volume,
            'ask_vol': ask_volume
        })
        
        # Calculate micro-momentum
        momentum_signal = 0
        if len(self.price_history) >= self.momentum_window:
            recent_prices = list(self.price_history)[-self.momentum_window:]
            price_change = (recent_prices[-1] - recent_prices[0]) / recent_prices[0] * 100
            
            if abs(price_change) > 0.01:  # 0.01% minimum move
                momentum_signal = 1 if price_change > 0 else -1
        
        # Generate signal based on combined factors
        signal = None
        confidence = 0.0
        reason = ""
        
        # Case 1: Heavy bid imbalance + upward momentum = BUY
        if imbalance > self.imbalance_threshold and momentum_signal >= 0:
            if spread_pct <= self.spread_threshold:
                confidence = min(0.5 + (imbalance - 1) * 0.2 + abs(momentum_signal) * 0.1, 0.85)
                if confidence >= self.min_confidence:
                    signal = "up"
                    reason = f"Bid heavy {imbalance:.2f}x + momentum {momentum_signal}, spread {spread_pct:.3f}%"
        
        # Case 2: Heavy ask imbalance + downward momentum = SELL
        elif imbalance < (1 / self.imbalance_threshold) and momentum_signal <= 0:
            if spread_pct <= self.spread_threshold:
                confidence = min(0.5 + ((1/imbalance) - 1) * 0.2 + abs(momentum_signal) * 0.1, 0.85)
                if confidence >= self.min_confidence:
                    signal = "down"
                    reason = f"Ask heavy {1/imbalance:.2f}x + momentum {momentum_signal}, spread {spread_pct:.3f}%"
        
        # Case 3: Spread compression with volume = imminent move
        if signal is None and len(self.bid_ask_history) >= 3:
            recent = list(self.bid_ask_history)[-3:]
            spreads = [r['spread'] for r in recent]
            
            if statistics.stdev(spreads) < 0.001:  # Tight spread range
                if imbalance > 1.3:  # Strong bid imbalance
                    confidence = 0.6
                    signal = "up"
                    reason = f"Spread compression + bid imbalance {imbalance:.2f}x"
                elif imbalance < 0.77:  # Strong ask imbalance
                    confidence = 0.6
                    signal = "down"
                    reason = f"Spread compression + ask imbalance {1/imbalance:.2f}x"
        
        if signal:
            self.trades_this_window += 1
            return Signal(
                strategy=self.name,
                signal=signal,
                confidence=confidence,
                reason=reason,
                metadata={
                    'imbalance': imbalance,
                    'spread_pct': spread_pct,
                    'momentum': momentum_signal,
                    'bid_vol': bid_volume,
                    'ask_vol': ask_volume,
                    'trades_in_window': self.trades_this_window
                }
            )
        
        return None
