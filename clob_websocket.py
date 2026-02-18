"""
CLOB WebSocket client for real-time price updates.
Provides sub-50ms price updates for YES/NO tokens.
"""
import asyncio
import json
import logging
import time
from typing import Callable, Dict, Optional, Set
import websockets

logger = logging.getLogger(__name__)


class ClobWebSocketClient:
    """
    WebSocket client for Polymarket CLOB real-time data.
    
    Features:
    - Auto-reconnect on disconnect
    - Subscribe to multiple markets
    - Callback-based price updates
    - Heartbeat/ping handling
    """

    CLOB_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.subscribed_markets: Set[str] = set()
        self.price_callbacks: Dict[str, Callable] = {}
        self.running = False
        self.reconnect_delay = 1.0
        self.max_reconnect_delay = 60.0
        self._lock = asyncio.Lock()

    async def connect(self) -> bool:
        """Connect to WebSocket server"""
        try:
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            self.ws = await websockets.connect(
                self.CLOB_WS_URL,
                extra_headers=headers,
                ping_interval=30,
                ping_timeout=10
            )
            
            logger.info("Connected to CLOB WebSocket")
            self.reconnect_delay = 1.0  # Reset on successful connect
            
            # Re-subscribe to previously subscribed markets
            async with self._lock:
                for market_id in self.subscribed_markets:
                    await self._subscribe(market_id)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to CLOB WebSocket: {e}")
            return False

    async def disconnect(self) -> None:
        """Disconnect from WebSocket server"""
        self.running = False
        if self.ws:
            try:
                await self.ws.close()
            except Exception as e:
                logger.warning(f"Error closing WebSocket: {e}")
            finally:
                self.ws = None

    async def subscribe(self, market_id: str, callback: Callable) -> bool:
        """
        Subscribe to market updates.
        
        Args:
            market_id: Market ID (token_id for YES/NO)
            callback: Function to call with price updates
        """
        async with self._lock:
            self.subscribed_markets.add(market_id)
            self.price_callbacks[market_id] = callback

        if self.ws and self.ws.open:
            return await self._subscribe(market_id)
        return True  # Will subscribe after connect

    async def _subscribe(self, market_id: str) -> bool:
        """Send subscription message"""
        try:
            subscribe_msg = {
                "type": "subscribe",
                "market": market_id,
                "channels": ["book", "price_change", "trade"]
            }
            await self.ws.send(json.dumps(subscribe_msg))
            logger.info(f"Subscribed to market: {market_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to subscribe to {market_id}: {e}")
            return False

    async def unsubscribe(self, market_id: str) -> bool:
        """Unsubscribe from market updates"""
        async with self._lock:
            self.subscribed_markets.discard(market_id)
            self.price_callbacks.pop(market_id, None)

        if self.ws and self.ws.open:
            try:
                unsubscribe_msg = {
                    "type": "unsubscribe",
                    "market": market_id
                }
                await self.ws.send(json.dumps(unsubscribe_msg))
                return True
            except Exception as e:
                logger.error(f"Failed to unsubscribe from {market_id}: {e}")
                return False
        return True

    async def run(self) -> None:
        """Main loop for receiving messages"""
        self.running = True

        while self.running:
            if not self.ws or not self.ws.open:
                logger.info(f"Reconnecting in {self.reconnect_delay}s...")
                await asyncio.sleep(self.reconnect_delay)
                
                if await self.connect():
                    continue
                else:
                    # Exponential backoff
                    self.reconnect_delay = min(
                        self.reconnect_delay * 2,
                        self.max_reconnect_delay
                    )
                    continue

            try:
                message = await self.ws.recv()
                await self._handle_message(message)
                
            except websockets.exceptions.ConnectionClosed:
                logger.warning("WebSocket connection closed")
                self.ws = None
                
            except Exception as e:
                logger.error(f"Error in WebSocket loop: {e}")
                await asyncio.sleep(1)

    async def _handle_message(self, message: str) -> None:
        """Handle incoming WebSocket message"""
        try:
            data = json.loads(message)
            msg_type = data.get("type")
            
            if msg_type == "book":
                await self._handle_book_update(data)
            elif msg_type == "price_change":
                await self._handle_price_change(data)
            elif msg_type == "trade":
                await self._handle_trade(data)
            elif msg_type == "pong":
                pass  # Heartbeat response
            else:
                logger.debug(f"Unknown message type: {msg_type}")
                
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON received: {message[:200]}")
        except Exception as e:
            logger.error(f"Error handling message: {e}")

    async def _handle_book_update(self, data: Dict) -> None:
        """Handle order book update"""
        market_id = data.get("market")
        if market_id in self.price_callbacks:
            callback = self.price_callbacks[market_id]
            
            # Extract best bid/ask
            bids = data.get("bids", [])
            asks = data.get("asks", [])
            
            update = {
                "type": "book",
                "timestamp": time.time(),
                "bid": float(bids[0]["price"]) if bids else None,
                "ask": float(asks[0]["price"]) if asks else None,
                "bid_size": float(bids[0]["size"]) if bids else 0,
                "ask_size": float(asks[0]["size"]) if asks else 0,
            }
            
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(market_id, update)
                else:
                    callback(market_id, update)
            except Exception as e:
                logger.error(f"Error in price callback: {e}")

    async def _handle_price_change(self, data: Dict) -> None:
        """Handle price change update"""
        market_id = data.get("market")
        if market_id in self.price_callbacks:
            callback = self.price_callbacks[market_id]
            
            update = {
                "type": "price_change",
                "timestamp": time.time(),
                "price": data.get("price"),
                "side": data.get("side"),
                "size": data.get("size"),
            }
            
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(market_id, update)
                else:
                    callback(market_id, update)
            except Exception as e:
                logger.error(f"Error in price callback: {e}")

    async def _handle_trade(self, data: Dict) -> None:
        """Handle trade execution update"""
        market_id = data.get("market")
        if market_id in self.price_callbacks:
            callback = self.price_callbacks[market_id]
            
            update = {
                "type": "trade",
                "timestamp": time.time(),
                "price": data.get("price"),
                "size": data.get("size"),
                "side": data.get("side"),
                "taker": data.get("taker_address"),
            }
            
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(market_id, update)
                else:
                    callback(market_id, update)
            except Exception as e:
                logger.error(f"Error in price callback: {e}")


class PriceAggregator:
    """
    Aggregates price updates from WebSocket and provides latest prices.
    """

    def __init__(self):
        self.prices: Dict[str, Dict] = {}
        self.ws_client = ClobWebSocketClient()
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Start WebSocket connection"""
        asyncio.create_task(self.ws_client.run())

    async def stop(self) -> None:
        """Stop WebSocket connection"""
        await self.ws_client.disconnect()

    async def subscribe_market(self, market_id: str) -> None:
        """Subscribe to a market and track its prices"""
        await self.ws_client.subscribe(market_id, self._on_price_update)

    async def _on_price_update(self, market_id: str, update: Dict) -> None:
        """Internal callback for price updates"""
        async with self._lock:
            if market_id not in self.prices:
                self.prices[market_id] = {}
            
            self.prices[market_id].update(update)
            self.prices[market_id]["last_update"] = time.time()

    def get_price(self, market_id: str) -> Optional[Dict]:
        """Get latest price for a market"""
        return self.prices.get(market_id)

    def get_best_bid_ask(self, market_id: str) -> tuple:
        """Get best bid and ask for a market"""
        price_data = self.prices.get(market_id, {})
        return (price_data.get("bid"), price_data.get("ask"))

    def get_spread(self, market_id: str) -> Optional[float]:
        """Get spread for a market"""
        bid, ask = self.get_best_bid_ask(market_id)
        if bid is not None and ask is not None:
            return ask - bid
        return None
