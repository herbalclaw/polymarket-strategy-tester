"""
Data feeds for price and sentiment.
"""

import asyncio
import aiohttp
from typing import Dict, List
from dataclasses import dataclass

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.base_strategy import MarketData


@dataclass
class ExchangePrice:
    exchange: str
    price: float
    bid: float
    ask: float
    bid_depth: float
    ask_depth: float
    latency_ms: float


class MultiExchangeFeed:
    """Fetch prices from multiple exchanges."""
    
    EXCHANGES = {
        'binance': {
            'url': 'https://api.binance.com/api/v3/ticker/bookTicker',
            'params': {'symbol': 'BTCUSDT'},
            'parser': lambda d: ExchangePrice(
                'Binance', float(d['bidPrice']), float(d['bidPrice']),
                float(d['askPrice']), 0, 0, 0
            )
        },
        'coinbase': {
            'url': 'https://api.exchange.coinbase.com/products/BTC-USD/ticker',
            'params': {},
            'parser': lambda d: ExchangePrice(
                'Coinbase', float(d['price']), float(d['bid']),
                float(d['ask']), 0, 0, 0
            )
        },
    }
    
    async def fetch_exchange(self, session: aiohttp.ClientSession, name: str, config: dict):
        """Fetch from single exchange."""
        try:
            async with session.get(
                config['url'],
                params=config.get('params', {}),
                timeout=aiohttp.ClientTimeout(total=3)
            ) as resp:
                data = await resp.json()
                return config['parser'](data)
        except Exception as e:
            print(f"Error fetching {name}: {e}")
            return None
    
    async def fetch_data(self) -> MarketData:
        """Fetch aggregated market data."""
        async with aiohttp.ClientSession() as session:
            tasks = [
                self.fetch_exchange(session, name, config)
                for name, config in self.EXCHANGES.items()
            ]
            
            results = await asyncio.gather(*tasks)
            
            exchange_data = {}
            prices = []
            
            for result in results:
                if result:
                    exchange_data[result.exchange] = {
                        'price': result.price,
                        'bid': result.bid,
                        'ask': result.ask,
                        'bid_depth': result.bid_depth,
                        'ask_depth': result.ask_depth
                    }
                    prices.append(result.price)
            
            # Calculate aggregated metrics
            if prices:
                import statistics
                vwap = statistics.mean(prices)
                mid = vwap
                spread = 0
            else:
                vwap = mid = 0
                spread = 0
            
            import time
            return MarketData(
                timestamp=time.time(),
                asset='BTC',
                price=mid,
                bid=mid * 0.999,
                ask=mid * 1.001,
                mid=mid,
                vwap=vwap,
                spread_bps=spread,
                volume_24h=0,
                exchange_prices=exchange_data,
                sentiment='neutral',
                sentiment_confidence=0.5
            )


class SentimentFeed:
    """Fetch sentiment data."""
    
    async def fetch_data(self) -> Dict:
        """Fetch sentiment from APIs."""
        try:
            # Try fear & greed index
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    'https://api.alternative.me/fng/?limit=1',
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        item = data['data'][0]
                        value = int(item['value'])
                        
                        # Convert to sentiment
                        if value < 25:
                            return {'sentiment': 'bullish', 'confidence': 0.8}  # Extreme fear = buy
                        elif value > 75:
                            return {'sentiment': 'bearish', 'confidence': 0.8}  # Extreme greed = sell
                        else:
                            return {'sentiment': 'neutral', 'confidence': 0.5}
        except:
            pass
        
        return {'sentiment': 'neutral', 'confidence': 0.5}
