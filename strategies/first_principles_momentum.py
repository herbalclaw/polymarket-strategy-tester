"""
FirstPrinciplesMomentumStrategy - Based on fundamental market structure

Key insight from data analysis:
- Binary options start at ~0.50 and converge to 0.01 or 0.99
- Early window (prices near 0.50): momentum works because price discovery is ongoing
- Late window (prices extreme): momentum fails because outcome is nearly certain

This strategy ONLY trades in the early window when price discovery is active.
"""

from typing import Optional, Dict, List
import numpy as np
from collections import deque
from core.base_strategy import BaseStrategy, Signal, MarketData


class FirstPrinciplesMomentumStrategy(BaseStrategy):
    """
    Trade momentum ONLY when price discovery is active.
    
    Fundamental principle: Binary options have 3 phases:
    1. Discovery (0.45-0.55): Prices adjust to true probability
    2. Trending (0.20-0.45 or 0.55-0.80): Momentum persists  
    3. Certainty (<0.20 or >0.80): Outcome nearly decided
    
    We only trade in phases 1 and 2 where momentum works.
    """
    
    def __init__(self,
                 discovery_range: tuple = (0.45, 0.55),
                 trending_range: tuple = (0.20, 0.80),
                 momentum_threshold: float = 0.02,
                 lookback: int = 3):
        super().__init__()
        self.name = "FirstPrinciplesMomentum"
        self.discovery_range = discovery_range
        self.trending_range = trending_range
        self.momentum_threshold = momentum_threshold
        
        self.price_history = deque(maxlen=lookback)
        
    def get_market_phase(self, price: float) -> str:
        """Determine which phase of price discovery we're in."""
        if self.discovery_range[0] <;= price <;= self.discovery_range[1]:
            return "discovery"
        elif price < self.trending_range[0] or price > self.trending_range[1]:
            return "certainty"
        else:
            return "trending"
    
    def calculate_momentum(self) -> Optional[float]:
        """Calculate price momentum over lookback period."""
        if len(self.price_history) < 2:
            return None
        
        prices = list(self.price_history)
        # Momentum = (current - previous) / previous
        momentum = (prices[-1] - prices[0]) / prices[0]
        return momentum
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        """Generate signal based on market phase and momentum."""
        price = data.price
        
        # Update history
        self.price_history.append(price)
        
        # Determine market phase
        phase = self.get_market_phase(price)
        
        # CRITICAL: Don't trade in certainty phase
        if phase == "certainty":
            return None
        
        # Need enough history
        if len(self.price_history) < 2:
            return None
        
        # Calculate momentum
        momentum = self.calculate_momentum()
        if momentum is None:
            return None
        
        # Generate signal based on phase and momentum
        if phase == "discovery":
            # In discovery phase, trade stronger momentum
            if abs(momentum) < self.momentum_threshold:
                return None
            
            confidence = 0.65 + min(0.25, abs(momentum) * 5)
            
            if momentum > 0:
                return Signal(
                    signal="up",
                    confidence=min(0.9, confidence),
                    strategy=self.name,
                    metadata={
                        'phase': phase,
                        'momentum': momentum,
                        'price': price
                    }
                )
            else:
                return Signal(
                    signal="down",
                    confidence=min(0.9, confidence),
                    strategy=self.name,
                    metadata={
                        'phase': phase,
                        'momentum': momentum,
                        'price': price
                    }
                )
        
        elif phase == "trending":
            # In trending phase, follow trend but with lower confidence
            if abs(momentum) < self.momentum_threshold * 0.8:
                return None
            
            confidence = 0.60 + min(0.20, abs(momentum) * 4)
            
            if momentum > 0:
                return Signal(
                    signal="up",
                    confidence=min(0.85, confidence),
                    strategy=self.name,
                    metadata={
                        'phase': phase,
                        'momentum': momentum,
                        'price': price
                    }
                )
            else:
                return Signal(
                    signal="down",
                    confidence=min(0.85, confidence),
                    strategy=self.name,
                    metadata={
                        'phase': phase,
                        'momentum': momentum,
                        'price': price
                    }
                )
        
        return None
