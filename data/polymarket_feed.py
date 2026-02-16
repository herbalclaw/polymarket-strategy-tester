"""
Polymarket Data Feed for Paper Trading with Realistic Order Book Walking
"""

import sqlite3
import time
import requests
from typing import Optional, Dict, List, Tuple
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
    """Read real-time Polymarket data and simulate realistic fills."""
    
    REST_API = "https://clob.polymarket.com"
    
    def __init__(self, data_collector_path: str = "../polymarket-data-collector"):
        self.data_collector_path = data_collector_path
        self.db_path = self._get_current_db_path()
        self.conn = None
        self.last_price: Optional[PolymarketPrice] = None
        self.session = requests.Session()
        
        # Cache for order book to reduce API calls
        self.last_book_fetch = 0
        self.cached_book: Optional[Dict] = None
        
    def _get_current_db_path(self) -> str:
        """Get path to current database file."""
        from datetime import datetime
        now = datetime.now()
        period = "AM" if now.hour < 12 else "PM"
        return f"{self.data_collector_path}/data/raw/btc_hf_{now:%Y-%m-%d}_{period}.db"
    
    def _ensure_connection(self):
        """Ensure database connection is active."""
        current_db = self._get_current_db_path()
        
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
                # Calculate VWAP from recent trades
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
    
    def fetch_live_order_book(self, token_id: str) -> Optional[Dict]:
        """Fetch live order book from Polymarket API."""
        try:
            resp = self.session.get(
                f"{self.REST_API}/book",
                params={"token_id": token_id},
                timeout=5
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"Error fetching order book: {e}")
            return None
    
    def walk_order_book(self, side: str, size_dollars: float, book: Dict) -> Tuple[float, float]:
        """
        Walk the order book to find fill price for a given size.
        
        Args:
            side: 'up' (buy) or 'down' (sell)
            size_dollars: Size in dollars to fill
            book: Order book from Polymarket API
            
        Returns:
            (average_fill_price, slippage_bps)
        """
        if not book:
            return 0.5, 0
        
        if side == 'up':
            # Buying - walk through asks
            orders = book.get('asks', [])
            orders.sort(key=lambda x: float(x['price']))  # Lowest first
        else:
            # Selling - walk through bids
            orders = book.get('bids', [])
            orders.sort(key=lambda x: float(x['price']), reverse=True)  # Highest first
        
        if not orders:
            return 0.5, 0
        
        # Best available price
        best_price = float(orders[0]['price'])
        
        remaining = size_dollars
        total_cost = 0.0
        total_shares = 0.0
        
        for order in orders:
            price = float(order['price'])
            size = float(order['size'])
            
            # Cost to buy all shares at this level
            order_cost = size * price
            
            if remaining <= order_cost:
                # Partial fill at this level
                shares_to_buy = remaining / price
                total_cost += remaining
                total_shares += shares_to_buy
                remaining = 0
                break
            else:
                # Full fill at this level
                total_cost += order_cost
                total_shares += size
                remaining -= order_cost
        
        if total_shares == 0:
            return best_price, 0
        
        # Average fill price
        avg_fill_price = total_cost / total_shares
        
        # Calculate slippage vs best price
        if side == 'up':
            slippage_bps = int((avg_fill_price - best_price) / best_price * 10000)
        else:
            slippage_bps = int((best_price - avg_fill_price) / best_price * 10000)
        
        # If not fully filled, mark as partial
        fill_ratio = (size_dollars - remaining) / size_dollars if size_dollars > 0 else 0
        if fill_ratio < 0.99:  # Less than 99% filled
            print(f"Warning: Partial fill only {fill_ratio:.1%} of order")
        
        return avg_fill_price, max(0, slippage_bps)
    
    def simulate_fill(self, side: str, size_dollars: float, token_id: str = None) -> Tuple[float, float, str]:
        """
        Simulate a realistic fill on Polymarket by walking the order book.
        
        Args:
            side: 'up' or 'down'
            size_dollars: Position size in dollars
            token_id: Market token ID (optional, will fetch from DB if None)
            
        Returns:
            (fill_price, slippage_bps, fill_status)
        """
        # Get token ID from database if not provided
        if token_id is None:
            if not self._ensure_connection():
                return 0.5, 0, "no_data"
            try:
                cursor = self.conn.cursor()
                cursor.execute('SELECT up_token_id FROM markets LIMIT 1')
                row = cursor.fetchone()
                if row:
                    token_id = row[0]
                else:
                    return 0.5, 0, "no_market"
            except:
                return 0.5, 0, "db_error"
        
        # Fetch live order book
        book = self.fetch_live_order_book(token_id)
        if not book:
            # Fallback to last known price
            price = self.get_latest_price()
            if price:
                fill_price = price.ask if side == 'up' else price.bid
                return fill_price, 0, "cached"
            return 0.5, 0, "no_book"
        
        # Walk the order book
        fill_price, slippage = self.walk_order_book(side, size_dollars, book)
        
        # Determine fill status
        if slippage > 100:  # More than 1% slippage
            status = "high_slippage"
        elif slippage > 50:
            status = "medium_slippage"
        else:
            status = "good_fill"
        
        return fill_price, slippage, status
    
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
