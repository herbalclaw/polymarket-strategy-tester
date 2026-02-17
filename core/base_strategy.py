from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from dataclasses import dataclass


@dataclass
class Signal:
    """Trading signal output."""
    strategy: str
    signal: str  # 'up', 'down', or 'neutral'
    confidence: float  # 0.0 to 1.0
    reason: str
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass  
class MarketData:
    """Standardized market data input."""
    timestamp: float
    asset: str
    
    # Price data
    price: float
    bid: float
    ask: float
    mid: float
    vwap: float
    
    # Market metrics
    spread_bps: float
    volume_24h: float
    
    # Multi-exchange data
    exchange_prices: Dict[str, Dict] = None
    
    # Order book data
    order_book: Dict[str, Any] = None
    
    # Sentiment data
    sentiment: str = "neutral"
    sentiment_confidence: float = 0.5
    
    # Historical price data for strategy calculations
    historical_prices: List[Dict] = None
    
    def __post_init__(self):
        if self.exchange_prices is None:
            self.exchange_prices = {}
        if self.order_book is None:
            self.order_book = {}
        if self.historical_prices is None:
            self.historical_prices = []


class BaseStrategy(ABC):
    """Base class for all trading strategies."""
    
    name: str = "base_strategy"
    version: str = "1.0.0"
    
    # Strategy parameters (override in subclass)
    min_confidence: float = 0.6
    max_positions: int = 1
    
    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.state = {}
        self.history: List[Signal] = []
        
    @abstractmethod
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        """
        Generate trading signal from market data.
        
        Args:
            data: MarketData object with current market state
            
        Returns:
            Signal object or None if no signal
        """
        pass
    
    def on_trade_open(self, signal: Signal, entry_price: float):
        """Called when a trade is opened based on this strategy's signal."""
        self.state['active_trade'] = {
            'signal': signal,
            'entry_price': entry_price,
            'open_time': data.timestamp if 'data' in dir() else None
        }
    
    def on_trade_close(self, exit_price: float, pnl: float, reason: str):
        """Called when a trade is closed."""
        if 'active_trade' in self.state:
            trade = self.state.pop('active_trade')
            trade['exit_price'] = exit_price
            trade['pnl'] = pnl
            trade['close_reason'] = reason
            self.history.append(trade)
    
    def get_performance(self) -> Dict:
        """Get strategy performance metrics."""
        if not self.history:
            return {
                'total_trades': 0,
                'win_rate': 0.0,
                'avg_pnl': 0.0,
                'total_pnl': 0.0
            }
        
        total = len(self.history)
        wins = sum(1 for t in self.history if t.get('pnl', 0) > 0)
        total_pnl = sum(t.get('pnl', 0) for t in self.history)
        
        return {
            'total_trades': total,
            'win_rate': wins / total if total > 0 else 0.0,
            'avg_pnl': total_pnl / total if total > 0 else 0.0,
            'total_pnl': total_pnl
        }
    
    def reset(self):
        """Reset strategy state."""
        self.state = {}
        self.history = []
