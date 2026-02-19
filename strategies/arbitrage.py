from typing import Optional
import statistics

from core.base_strategy import BaseStrategy, Signal, MarketData


class ArbitrageStrategy(BaseStrategy):
    """
    Cross-Exchange Arbitrage Strategy
    
    Exploits price discrepancies between exchanges.
    Bets on price convergence when exchanges are misaligned.
    """
    
    name = "arbitrage"
    description = "Exploit price discrepancies between exchanges"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        config = config or {}
        self.min_arb_pct = self.config.get('min_arb_pct', 0.1)
        self.max_arb_pct = self.config.get('max_arb_pct', 1.0)
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        if not data.exchange_prices or len(data.exchange_prices) < 2:
            return None
        
        prices = [ep['price'] for ep in data.exchange_prices.values()]
        
        if len(prices) < 2:
            return None
        
        max_price = max(prices)
        min_price = min(prices)
        mean_price = statistics.mean(prices)
        
        arb_pct = (max_price - min_price) / mean_price * 100
        
        # Only trade if arbitrage is within reasonable bounds
        if arb_pct < self.min_arb_pct or arb_pct > self.max_arb_pct:
            return None
        
        # Find which exchanges are outliers
        max_exchange = max(data.exchange_prices.items(), key=lambda x: x[1]['price'])
        min_exchange = min(data.exchange_prices.items(), key=lambda x: x[1]['price'])
        
        # Bet on convergence to mean
        if max_price > mean_price * 1.001:
            return Signal(
                strategy=self.name,
                signal="down",
                confidence=min(arb_pct * 2, 0.8),
                reason=f"{max_exchange[0]} overpriced by {arb_pct:.3f}% vs others",
                metadata={
                    'arbitrage_pct': arb_pct,
                    'max_exchange': max_exchange[0],
                    'min_exchange': min_exchange[0],
                    'mean_price': mean_price
                }
            )
        elif min_price < mean_price * 0.999:
            return Signal(
                strategy=self.name,
                signal="up",
                confidence=min(arb_pct * 2, 0.8),
                reason=f"{min_exchange[0]} underpriced by {arb_pct:.3f}% vs others",
                metadata={
                    'arbitrage_pct': arb_pct,
                    'max_exchange': max_exchange[0],
                    'min_exchange': min_exchange[0],
                    'mean_price': mean_price
                }
            )
        
        return None
