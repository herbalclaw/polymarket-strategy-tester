"""
StaleQuoteArbitrage Strategy for Polymarket BTC 5-Minute Markets

This strategy exploits stale quotes in the orderbook that haven't been updated
to reflect new market information. In fast-moving crypto markets, some liquidity
providers fail to update quotes quickly enough, creating arbitrage opportunities.

Research Basis:
- Academic research shows arbitrageurs extracted $40M from Polymarket (April 2024-April 2025)
- Top arbitrageur made $2M with 4,049 trades (avg $496/trade)
- Strategy: Simple sum-price deviations (YES + NO ≠ $1.00)

Edge: Capture mispricing when YES + NO < $1.00 (guaranteed profit at settlement).
"""

import numpy as np
from typing import Dict, Any, Optional, Tuple
from core.base_strategy import BaseStrategy


class StaleQuoteArbitrage(BaseStrategy):
    """
    Strategy that exploits stale quotes in the orderbook.
    
    In prediction markets, YES + NO should equal $1.00. When they don't,
    there's a mathematical arbitrage opportunity. This strategy identifies
    and captures these opportunities.
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        config = config or {}
        self.name = "StaleQuoteArbitrage"
        self.description = "Exploits stale quotes when YES + NO ≠ $1.00"
        
        # Strategy parameters
        self.min_arbitrage = config.get('min_arbitrage', 0.005)  # Min 0.5% arbitrage
        self.max_position_hold = config.get('max_position_hold', 240)  # Max seconds to hold
        self.min_liquidity = config.get('min_liquidity', 100)  # Min liquidity in USD
        self.position_size = config.get('position_size', 1.0)
        
        # State tracking
        self.arbitrage_history = []
        self.last_trade_time = 0
        
    def calculate_arbitrage(self, yes_price: float, no_price: float) -> Tuple[float, float]:
        """
        Calculate arbitrage opportunity.
        
        Returns:
            (sum_price, arbitrage_profit)
            sum_price = yes_price + no_price
            arbitrage_profit = 1.0 - sum_price (if positive, there's arbitrage)
        """
        sum_price = yes_price + no_price
        arbitrage = 1.0 - sum_price
        return sum_price, arbitrage
    
    def check_liquidity(self, orderbook: Dict[str, Any]) -> bool:
        """Check if there's sufficient liquidity for the trade."""
        if not orderbook:
            return False
        
        yes_liquidity = orderbook.get('yes_liquidity', 0)
        no_liquidity = orderbook.get('no_liquidity', 0)
        
        return yes_liquidity >= self.min_liquidity and no_liquidity >= self.min_liquidity
    
    def generate_signal(self, data) -> Optional[Dict[str, Any]]:
        """
        Generate trading signal based on arbitrage opportunity.
        
        Args:
            data: Market data including yes_price, no_price, orderbook
            
        Returns:
            Signal dict or None
        """
        # Handle both dict and MarketData objects
        if hasattr(data, 'metadata'):
            # MarketData object - extract from metadata
            yes_price = data.metadata.get('yes_price', 0.5) if data.metadata else 0.5
            no_price = data.metadata.get('no_price', 0.5) if data.metadata else 0.5
            orderbook = data.order_book or {}
            current_time = data.timestamp
        else:
            # Dict object
            yes_price = data.get('yes_price', 0.5) if isinstance(data, dict) else 0.5
            no_price = data.get('no_price', 0.5) if isinstance(data, dict) else 0.5
            orderbook = data.get('orderbook', {}) if isinstance(data, dict) else {}
            current_time = data.get('timestamp', 0) if isinstance(data, dict) else 0
        
        # Calculate arbitrage
        sum_price, arbitrage = self.calculate_arbitrage(yes_price, no_price)
        
        # Track history
        self.arbitrage_history.append({
            'timestamp': current_time,
            'sum_price': sum_price,
            'arbitrage': arbitrage
        })
        
        if len(self.arbitrage_history) > 50:
            self.arbitrage_history.pop(0)
        
        # Check if arbitrage opportunity exists
        if arbitrage < self.min_arbitrage:
            return None
        
        # Check liquidity
        if not self.check_liquidity(orderbook):
            return None
        
        # Rate limiting - don't trade too frequently
        if current_time - self.last_trade_time < 30:
            return None
        
        # Calculate expected return
        # Buy both sides, hold to settlement
        investment = yes_price + no_price
        payout = 1.0  # One side will pay $1
        profit = payout - investment
        return_pct = profit / investment
        
        # Determine which side to trade (if we can only trade one)
        # Trade the side with better price relative to probability
        if yes_price < no_price:
            side = 'UP'
            entry = yes_price
            edge = arbitrage / 2  # Approximate edge
        else:
            side = 'DOWN'
            entry = no_price
            edge = arbitrage / 2
        
        return {
            'side': side,
            'confidence': 0.95,  # High confidence for arbitrage
            'edge': edge,
            'expected_return': return_pct,
            'arbitrage': arbitrage,
            'sum_price': sum_price,
            'entry_price': entry,
            'timestamp': current_time
        }
    
    def calculate_position_size(self, signal: Dict[str, Any]) -> float:
        """Calculate position size based on arbitrage size."""
        base_size = self.position_size
        
        # Scale with arbitrage size - larger arb = larger position
        arbitrage = signal.get('arbitrage', 0.005)
        size_multiplier = min(arbitrage / self.min_arbitrage, 3.0)
        
        return base_size * size_multiplier
    
    def should_exit(self, current_price: float, position: Dict[str, Any], 
                    data: Dict[str, Any]) -> bool:
        """Determine if position should be exited."""
        current_time = data.get('timestamp', 0)
        entry_time = position.get('entry_time', current_time)
        time_held = current_time - entry_time
        
        # Exit if held too long (arbitrage should resolve quickly)
        if time_held > self.max_position_hold:
            return True
        
        # Exit if arbitrage has closed
        yes_price = data.get('yes_price', 0.5)
        no_price = data.get('no_price', 0.5)
        _, arbitrage = self.calculate_arbitrage(yes_price, no_price)
        
        # If arbitrage is gone, exit
        if arbitrage < self.min_arbitrage * 0.5:
            return True
        
        # Take profit if we've captured most of the arbitrage
        entry_price = position.get('entry_price', current_price)
        side = position.get('side', 'UP')
        
        if side == 'UP':
            profit = current_price - entry_price
        else:
            profit = entry_price - current_price
        
        expected_edge = position.get('expected_edge', 0.01)
        if profit > expected_edge * 0.8:
            return True
        
        return False
    
    def get_arbitrage_stats(self) -> Dict[str, float]:
        """Get statistics on arbitrage opportunities."""
        if not self.arbitrage_history:
            return {}
        
        arbitrages = [a['arbitrage'] for a in self.arbitrage_history]
        return {
            'avg_arbitrage': np.mean(arbitrages),
            'max_arbitrage': np.max(arbitrages),
            'min_arbitrage': np.min(arbitrages),
            'opportunities': sum(1 for a in arbitrages if a > self.min_arbitrage)
        }
    
    def get_params(self) -> Dict[str, Any]:
        """Get strategy parameters for optimization."""
        return {
            'min_arbitrage': self.min_arbitrage,
            'max_position_hold': self.max_position_hold,
            'min_liquidity': self.min_liquidity,
            'position_size': self.position_size
        }
    
    def set_params(self, params: Dict[str, Any]):
        """Set strategy parameters."""
        self.min_arbitrage = params.get('min_arbitrage', self.min_arbitrage)
        self.max_position_hold = params.get('max_position_hold', self.max_position_hold)
        self.min_liquidity = params.get('min_liquidity', self.min_liquidity)
        self.position_size = params.get('position_size', self.position_size)
