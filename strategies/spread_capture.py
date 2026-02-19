"""
Spread Capture Market Making Strategy

Pure market making strategy focused on capturing bid-ask spread.
Unlike directional strategies, this profits from providing liquidity
on both sides of the market.

Key concepts from professional market making:
1. Queue position optimization
2. Spread capture when both sides fill
3. Dynamic spread adjustment based on volatility
4. Inventory skew management

Reference: Stoikov market making model, professional CLOB market making
"""

from typing import Optional
from collections import deque
import statistics

from core.base_strategy import BaseStrategy, Signal, MarketData


class SpreadCaptureStrategy(BaseStrategy):
    """
    Market making by capturing bid-ask spread.
    
    This strategy doesn't predict direction - it profits from the
    natural spread between bid and ask prices by attempting to
    buy at bid and sell at ask.
    
    For BTC 5-min markets, we simulate this by:
    - Entering when spread is wide enough
    - Exiting when spread compresses or at expiry
    """
    
    name = "SpreadCapture"
    description = "Capture bid-ask spread through market making"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        
        # Minimum spread to trade (in price terms)
        self.min_spread = self.config.get('min_spread', 0.02)  # 2 cents
        self.target_spread = self.config.get('target_spread', 0.04)  # 4 cents
        
        # Maximum spread (avoid chaotic markets)
        self.max_spread = self.config.get('max_spread', 0.10)  # 10 cents
        
        # Volatility filter - avoid high vol markets
        self.max_volatility = self.config.get('max_volatility', 0.03)  # 3%
        
        # Volume requirement
        self.min_volume_24h = self.config.get('min_volume_24h', 50000)  # $50K
        
        # Price history for volatility calc
        self.price_history: deque = deque(maxlen=50)
        self.spread_history: deque = deque(maxlen=20)
        
        # Track if we have an open position
        self.has_position = False
        self.entry_spread = 0.0
        self.entry_price = 0.0
        self.position_side = None
        
    def calculate_volatility(self) -> float:
        """Calculate recent price volatility."""
        if len(self.price_history) < 10:
            return float('inf')
        
        recent = list(self.price_history)[-20:]
        if len(recent) < 10:
            return float('inf')
        
        try:
            return statistics.stdev(recent) / (sum(recent) / len(recent))
        except:
            return float('inf')
    
    def get_spread_stats(self) -> dict:
        """Get spread statistics."""
        if len(self.spread_history) < 5:
            return {'avg': 0, 'current': 0, 'percentile': 50}
        
        spreads = list(self.spread_history)
        current = spreads[-1]
        avg = sum(spreads) / len(spreads)
        
        # Calculate percentile of current spread
        sorted_spreads = sorted(spreads)
        percentile = sum(1 for s in sorted_spreads if s <= current) / len(sorted_spreads) * 100
        
        return {
            'avg': avg,
            'current': current,
            'percentile': percentile
        }
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        # Need order book data
        if not data.order_book:
            return None
        
        bids = data.order_book.get('bids', [])
        asks = data.order_book.get('asks', [])
        
        if not bids or not asks:
            return None
        
        best_bid = float(bids[0]['price']) if bids else 0
        best_ask = float(asks[0]['price']) if asks else 0
        
        if best_bid <= 0 or best_ask <= 0:
            return None
        
        # Calculate spread
        spread = best_ask - best_bid
        mid_price = (best_bid + best_ask) / 2
        
        # Store data
        self.price_history.append(mid_price)
        self.spread_history.append(spread)
        
        # Check volatility
        volatility = self.calculate_volatility()
        if volatility > self.max_volatility:
            return None
        
        # Check volume
        if data.volume_24h < self.min_volume_24h:
            return None
        
        spread_stats = self.get_spread_stats()
        
        # Entry condition: spread is wide and above average
        if spread >= self.min_spread and spread >= spread_stats['avg'] * 0.8:
            # Determine which side to take based on inventory/imbalance
            # For simplicity, take the side with better queue position
            # (simulate by choosing the side with more depth)
            
            bid_depth = sum(float(b.get('size', 0)) for b in bids[:3])
            ask_depth = sum(float(a.get('size', 0)) for a in asks[:3])
            
            # Take the side with less competition (less depth = better fill probability)
            if bid_depth > ask_depth * 1.2:
                # More bids = harder to get filled on buy
                # Take ask side (sell/short)
                signal = "down"
                confidence = min(0.55 + (spread - self.min_spread) * 2, 0.75)
                reason = f"Spread capture: Wide spread {spread:.3f} (avg {spread_stats['avg']:.3f}), taking ask side"
            elif ask_depth > bid_depth * 1.2:
                # More asks = harder to get filled on sell
                # Take bid side (buy/long)
                signal = "up"
                confidence = min(0.55 + (spread - self.min_spread) * 2, 0.75)
                reason = f"Spread capture: Wide spread {spread:.3f} (avg {spread_stats['avg']:.3f}), taking bid side"
            else:
                # Balanced - take direction based on price position
                if mid_price > 0.5:
                    signal = "down"  # Fade high prices
                    reason = f"Spread capture: Balanced book, fading high price {mid_price:.3f}"
                else:
                    signal = "up"  # Fade low prices
                    reason = f"Spread capture: Balanced book, fading low price {mid_price:.3f}"
                confidence = 0.60
            
            return Signal(
                strategy=self.name,
                signal=signal,
                confidence=confidence,
                reason=reason,
                metadata={
                    'spread': spread,
                    'avg_spread': spread_stats['avg'],
                    'best_bid': best_bid,
                    'best_ask': best_ask,
                    'mid_price': mid_price,
                    'bid_depth': bid_depth,
                    'ask_depth': ask_depth,
                    'volatility': volatility
                }
            )
        
        return None
