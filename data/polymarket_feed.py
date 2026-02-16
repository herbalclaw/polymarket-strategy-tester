"""
Polymarket Data Feed for Paper Trading - Fixed Version
Properly connects to Polymarket CLOB for BTC 5-minute markets
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
    GAMMA_API = "https://gamma-api.polymarket.com"
    
    def __init__(self, data_collector_path: str = "/root/.openclaw/workspace/polymarket-data-collector"):
        self.data_collector_path = data_collector_path
        self.db_path = self._get_current_db_path()
        self.conn = None
        self.last_price: Optional[PolymarketPrice] = None
        self.session = requests.Session()
        
        # Token IDs for BTC 5-min market (will be fetched dynamically)
        self.up_token_id = None
        self.down_token_id = None
        self.token_window = 0  # Track which window tokens belong to
        
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
    
    def _get_token_ids(self) -> bool:
        """Fetch token IDs for current BTC 5-min market."""
        # Check if we need to refresh (new window)
        current_window = (int(time.time()) // 300) * 300
        if self.token_window != current_window:
            # New window, clear cached tokens
            self.up_token_id = None
            self.down_token_id = None
            self.token_window = current_window
        
        if self.up_token_id and self.down_token_id:
            return True
        
        if not self._ensure_connection():
            return False
        
        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT up_token_id, down_token_id FROM markets ORDER BY timestamp DESC LIMIT 1')
            row = cursor.fetchone()
            if row:
                self.up_token_id = row[0]
                self.down_token_id = row[1]
                return True
        except Exception as e:
            print(f"Error fetching token IDs: {e}")
        
        return False
    
    def get_latest_price(self) -> Optional[PolymarketPrice]:
        """Get latest price from Polymarket CLOB API."""
        if not self._get_token_ids():
            return None
        
        try:
            # Fetch order book for UP token
            resp = self.session.get(
                f"{self.REST_API}/book",
                params={"token_id": self.up_token_id},
                timeout=5
            )
            resp.raise_for_status()
            book = resp.json()
            
            bids = book.get('bids', [])
            asks = book.get('asks', [])
            
            if not bids or not asks:
                return None
            
            best_bid = float(bids[0]['price'])
            best_ask = float(asks[0]['price'])
            mid = (best_bid + best_ask) / 2
            spread_bps = int((best_ask - best_bid) / mid * 10000)
            
            # Calculate depth (sum of top 5 levels)
            bid_depth = sum(float(b['price']) * float(b['size']) for b in bids[:5])
            ask_depth = sum(float(a['price']) * float(a['size']) for a in asks[:5])
            
            price = PolymarketPrice(
                timestamp_ms=int(time.time() * 1000),
                bid=best_bid,
                ask=best_ask,
                mid=mid,
                vwap=mid,  # Use mid as VWAP for now
                spread_bps=spread_bps,
                bid_depth=bid_depth,
                ask_depth=ask_depth
            )
            self.last_price = price
            return price
            
        except Exception as e:
            print(f"Error fetching Polymarket price: {e}")
        
        return self.last_price
    
    def walk_order_book(self, side: str, size_dollars: float, book: Dict) -> Tuple[float, float]:
        """
        Walk the order book to find fill price for a given size.
        
        Args:
            side: 'up' (buy UP token) or 'down' (buy DOWN token)
            size_dollars: Size in dollars to fill
            book: Order book from Polymarket API
            
        Returns:
            (average_fill_price, slippage_bps)
        """
        if not book:
            return 0.5, 0
        
        # For UP token:
        # - Buying UP = going long (pay ask)
        # - Selling UP = going short (receive bid)
        # For DOWN token (inverse of UP):
        # - Buying DOWN = going short
        # - Selling DOWN = going long
        
        if side == 'up':
            # Buying UP token - walk through asks
            orders = book.get('asks', [])
            orders.sort(key=lambda x: float(x['price']))
        else:
            # For DOWN token, we need to fetch its book separately
            # For now, approximate using UP token bids (inverse)
            orders = book.get('bids', [])
            orders.sort(key=lambda x: float(x['price']), reverse=True)
        
        if not orders:
            return 0.5, 0
        
        best_price = float(orders[0]['price'])
        
        remaining = size_dollars
        total_cost = 0.0
        total_shares = 0.0
        
        for order in orders:
            price = float(order['price'])
            size = float(order['size'])
            order_cost = size * price
            
            if remaining <= order_cost:
                shares_to_buy = remaining / price
                total_cost += remaining
                total_shares += shares_to_buy
                remaining = 0
                break
            else:
                total_cost += order_cost
                total_shares += size
                remaining -= order_cost
        
        if total_shares == 0:
            return best_price, 0
        
        avg_fill_price = total_cost / total_shares
        
        if side == 'up':
            slippage_bps = int((avg_fill_price - best_price) / best_price * 10000)
        else:
            slippage_bps = int((best_price - avg_fill_price) / best_price * 10000)
        
        return avg_fill_price, max(0, slippage_bps)
    
    def simulate_fill(self, side: str, size_dollars: float) -> Tuple[float, float, str]:
        """
        Simulate a realistic fill on Polymarket by walking the order book.
        
        Args:
            side: 'up' or 'down'
            size_dollars: Position size in dollars
            
        Returns:
            (fill_price, slippage_bps, fill_status)
        """
        if not self._get_token_ids():
            return 0.5, 0, "no_tokens"
        
        try:
            # Fetch order book
            token_id = self.up_token_id if side == 'up' else self.down_token_id
            resp = self.session.get(
                f"{self.REST_API}/book",
                params={"token_id": token_id},
                timeout=5
            )
            resp.raise_for_status()
            book = resp.json()
            
            if not book:
                return 0.5, 0, "no_book"
            
            # Walk the order book
            fill_price, slippage = self.walk_order_book(side, size_dollars, book)
            
            # Determine fill status
            if slippage > 100:
                status = "high_slippage"
            elif slippage > 50:
                status = "medium_slippage"
            else:
                status = "good_fill"
            
            return fill_price, slippage, status
            
        except Exception as e:
            print(f"Error simulating fill: {e}")
            return 0.5, 0, "error"
    
    def get_strike_price(self) -> Optional[float]:
        """Get strike price for current BTC 5-min market."""
        try:
            current_window = (int(time.time()) // 300) * 300
            slug = f"btc-updown-5m-{current_window}"
            
            resp = self.session.get(
                f"{self.GAMMA_API}/events",
                params={"slug": slug},
                timeout=5
            )
            resp.raise_for_status()
            data = resp.json()
            
            if data and len(data) > 0:
                event = data[0]
                # Strike price is typically in the description or title
                # For BTC up/down, it's the current BTC price at market open
                description = event.get('description', '')
                # Extract strike from description like "Will BTC be above $97,500 at 12:05 PM?"
                import re
                match = re.search(r'\$([\d,]+(?:\.\d+)?)', description)
                if match:
                    return float(match.group(1).replace(',', ''))
            
            # Fallback: use current BTC price from Coinbase or similar
            return self._get_external_btc_price()
        except Exception as e:
            print(f"Error getting strike price: {e}")
            return None
    
    def _get_external_btc_price(self) -> Optional[float]:
        """Get external BTC price as fallback."""
        try:
            resp = self.session.get(
                "https://api.coinbase.com/v2/exchange-rates?currency=BTC",
                timeout=5
            )
            resp.raise_for_status()
            data = resp.json()
            # BTC price in USD
            btc_usd = float(data['data']['rates']['USD'])
            return btc_usd
        except Exception as e:
            print(f"Error getting external BTC price: {e}")
            return None
    
    def get_settlement_price(self, market_window: int) -> Optional[float]:
        """
        Get BTC price at settlement for a specific window.
        
        NOTE: This currently uses external API which may not be accurate.
        For true settlement, we need historical BTC price at window close.
        
        Returns None to disable automatic expiry settlement until proper data available.
        """
        try:
            # Check if window has actually closed
            current_time = int(time.time())
            window_close = market_window + 300
            
            if current_time < window_close:
                return None  # Window hasn't closed yet
            
            # TEMPORARY: Disable automatic expiry settlement
            # We don't have reliable historical BTC price data
            # Positions should be exited manually or will be marked as stale
            return None
            
        except Exception as e:
            print(f"Error getting settlement price: {e}")
            return None
    
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
