"""
Polymarket Data Feed for Paper Trading
Reads real-time data from the data collector's database
"""

import sqlite3
import time
from typing import Optional, Dict
from dataclasses import dataclass

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.base_strategy import MarketData


@dataclass
class PolymarketPrice:
    """Price data from Polymarket."""
    timestamp_ms: int
    bid: float
    ask: float
    mid: float
    vwap: float
    spread_bps: int
    bid_depth: float
    ask_depth: float
    volume_24h: float = 0


class PolymarketDataFeed:
    """Read real-time Polymarket data from collector database."""
    
    def __init__(self, data_collector_path: str = "../polymarket-data-collector"):
        self.data_collector_path = data_collector_path
        self.db_path = self._get_current_db_path()
        self.conn = None
        self.last_price: Optional[PolymarketPrice] = None
        
    def _get_current_db_path(self) -> str:
        """Get path to current database file."""
        from datetime import datetime
        now = datetime.now()
        period = "AM" if now.hour < 12 else "PM"
        return f"{self.data_collector_path}/data/raw/btc_hf_{now:%Y-%m-%d}_{period}.db"
    
    def _ensure_connection(self):
        """Ensure database connection is active."""
        current_db = self._get_current_db_path()
        
        # Reconnect if database changed (AM/PM switch)
        if current_db != self.db_path or self.conn is None:
            if self.conn:
                self.conn.close()
            self.db_path = current_db
            if os.path.exists(self.db_path):
                self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
                self.conn.execute("PRAGMA query_only = ON")
        
        if not os.path.exists(self.db_path):
            return False
        
        if self.conn is None:
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.execute("PRAGMA query_only = ON")
        
        return True
    
    def get_latest_price(self) -> Optional[PolymarketPrice]:
        """Get latest price from Polymarket."""
        if not self._ensure_connection():
            return None
        
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT timestamp_ms, bid, ask, mid, spread_bps, bid_depth, ask_depth
                FROM price_updates
                ORDER BY timestamp_ms DESC
                LIMIT 1
            ''')
            row = cursor.fetchone()
            
            if row:
                # Calculate VWAP from recent trades (last 100 updates)
                cursor.execute('''
                    SELECT mid FROM price_updates
                    ORDER BY timestamp_ms DESC
                    LIMIT 100
                ''')
                mids = [r[0] for r in cursor.fetchall()]
                vwap = sum(mids) / len(mids) if mids else row[3]
                
                price = PolymarketPrice(
                    timestamp_ms=row[0],
                    bid=row[1] / 10000,  # Convert from integer cents
                    ask=row[2] / 10000,
                    mid=row[3] / 10000,
                    vwap=vwap / 10000,
                    spread_bps=row[4],
                    bid_depth=row[5] or 0,
                    ask_depth=row[6] or 0
                )
                self.last_price = price
                return price
            
        except Exception as e:
            print(f"Error reading Polymarket data: {e}")
        
        return self.last_price
    
    def get_order_book(self) -> Optional[Dict]:
        """Get current order book snapshot."""
        price = self.get_latest_price()
        if not price:
            return None
        
        return {
            'best_bid': price.bid,
            'best_ask': price.ask,
            'mid': price.mid,
            'spread_bps': price.spread_bps,
            'bid_depth': price.bid_depth,
            'ask_depth': price.ask_depth,
            'vwap': price.vwap
        }
    
    def fetch_data(self) -> Optional[MarketData]:
        """Fetch market data for strategies."""
        price = self.get_latest_price()
        if not price:
            return None
        
        return MarketData(
            timestamp=time.time(),
            asset='BTC',
            price=price.mid,
            bid=price.bid,
            ask=price.ask,
            mid=price.mid,
            vwap=price.vwap,
            spread_bps=price.spread_bps,
            volume_24h=price.volume_24h,
            exchange_prices={},
            order_book=self.get_order_book(),
            sentiment='neutral',
            sentiment_confidence=0.5
        )
    
    def simulate_fill(self, side: str, size: float) -> tuple[float, float]:
        """
        Simulate a realistic fill on Polymarket.
        
        Args:
            side: 'up' or 'down'
            size: position size in dollars
            
        Returns:
            (fill_price, slippage_bps)
        """
        price = self.get_latest_price()
        if not price:
            return 0.5, 0  # Default fallback
        
        # Base price from order book
        if side == 'up':
            base_price = price.ask  # Buy at ask
            depth = price.ask_depth
        else:
            base_price = price.bid  # Sell at bid
            depth = price.bid_depth
        
        # Calculate slippage based on size vs depth
        # If size is large relative to depth, more slippage
        if depth > 0:
            depth_ratio = size / depth
            slippage_bps = min(100, int(depth_ratio * 50))  # Max 1% slippage
        else:
            slippage_bps = 10  # Default 10 bps if no depth data
        
        # Apply slippage
        slippage_pct = slippage_bps / 10000
        if side == 'up':
            fill_price = base_price * (1 + slippage_pct)
        else:
            fill_price = base_price * (1 - slippage_pct)
        
        # Clamp to valid range [0.01, 0.99]
        fill_price = max(0.01, min(0.99, fill_price))
        
        return fill_price, slippage_bps
