"""
Scalping Strategy Family - Based on 0.5 entry, 0.6 target edge
Different hold times and stop losses to find profitable variants
"""

from typing import Optional, Tuple, Any, Dict
from core.base_strategy import BaseStrategy, MarketData
from core.base_strategy import Signal as BaseSignal


class ScalperQuickExit(BaseStrategy):
    """
    Quick scalper: Enter at 0.50, target 0.55 (10% gain), stop at 0.48 (4% loss)
    Hold time: 1-2 minutes max
    """
    
    name: str = "ScalperQuickExit"
    
    def __init__(self):
        super().__init__()
        self.entry_threshold = 0.50
        self.target = 0.55
        self.stop_loss = 0.48
        self.max_hold_seconds = 120
        
    def generate_signal(self, data: MarketData) -> Optional[BaseSignal]:
        price = data.best_bid if hasattr(data, 'best_bid') else 0.5
        
        # Enter near 0.50
        if abs(price - self.entry_threshold) < 0.02:
            return BaseSignal(
                strategy=self.name,
                signal="up",
                confidence=0.7,
                reason=f"Quick scalp: entry {price:.3f}, target {self.target}, stop {self.stop_loss}",
                metadata={"target": self.target, "stop": self.stop_loss}
            )
        return None
    
    def check_exit(self, data: MarketData, entry_price: float) -> Tuple[bool, str]:
        price = data.best_bid if hasattr(data, 'best_bid') else entry_price
        
        if price >= self.target:
            return True, f"Target hit: {price:.3f} >= {self.target}"
        if price <= self.stop_loss:
            return True, f"Stop loss: {price:.3f} <= {self.stop_loss}"
        return False, ""


class ScalperMediumHold(BaseStrategy):
    """
    Medium scalper: Enter at 0.50, target 0.58 (16% gain), stop at 0.45 (10% loss)
    Hold time: 3-5 minutes
    """
    
    name: str = "ScalperMediumHold"
    
    def __init__(self):
        super().__init__()
        self.entry_threshold = 0.50
        self.target = 0.58
        self.stop_loss = 0.45
        self.max_hold_seconds = 300
        
    def generate_signal(self, data: MarketData) -> Optional[BaseSignal]:
        price = data.best_bid if hasattr(data, 'best_bid') else 0.5
        
        if abs(price - self.entry_threshold) < 0.025:
            return BaseSignal(
                strategy=self.name,
                signal="up",
                confidence=0.65,
                reason=f"Medium scalp: entry {price:.3f}, target {self.target}, stop {self.stop_loss}",
                metadata={"target": self.target, "stop": self.stop_loss}
            )
        return None
    
    def check_exit(self, data: MarketData, entry_price: float) -> Tuple[bool, str]:
        price = data.best_bid if hasattr(data, 'best_bid') else entry_price
        
        if price >= self.target:
            return True, f"Target hit: {price:.3f} >= {self.target}"
        if price <= self.stop_loss:
            return True, f"Stop loss: {price:.3f} <= {self.stop_loss}"
        return False, ""


class ScalperAggressive(BaseStrategy):
    """
    Aggressive scalper: Enter at 0.50, target 0.60 (20% gain), stop at 0.42 (16% loss)
    Hold time: 5-10 minutes
    """
    
    name: str = "ScalperAggressive"
    
    def __init__(self):
        super().__init__()
        self.entry_threshold = 0.50
        self.target = 0.60
        self.stop_loss = 0.42
        self.max_hold_seconds = 600
        
    def generate_signal(self, data: MarketData) -> Optional[BaseSignal]:
        price = data.best_bid if hasattr(data, 'best_bid') else 0.5
        
        if abs(price - self.entry_threshold) < 0.03:
            return BaseSignal(
                strategy=self.name,
                signal="up",
                confidence=0.6,
                reason=f"Aggressive scalp: entry {price:.3f}, target {self.target}, stop {self.stop_loss}",
                metadata={"target": self.target, "stop": self.stop_loss}
            )
        return None
    
    def check_exit(self, data: MarketData, entry_price: float) -> Tuple[bool, str]:
        price = data.best_bid if hasattr(data, 'best_bid') else entry_price
        
        if price >= self.target:
            return True, f"Target hit: {price:.3f} >= {self.target}"
        if price <= self.stop_loss:
            return True, f"Stop loss: {price:.3f} <= {self.stop_loss}"
        return False, ""


class ScalperTightStop(BaseStrategy):
    """
    Tight stop scalper: Enter at 0.50, target 0.53 (6% gain), stop at 0.49 (2% loss)
    Hold time: 30-60 seconds
    """
    
    name: str = "ScalperTightStop"
    
    def __init__(self):
        super().__init__()
        self.entry_threshold = 0.50
        self.target = 0.53
        self.stop_loss = 0.49
        self.max_hold_seconds = 60
        
    def generate_signal(self, data: MarketData) -> Optional[BaseSignal]:
        price = data.best_bid if hasattr(data, 'best_bid') else 0.5
        
        if abs(price - self.entry_threshold) < 0.015:
            return BaseSignal(
                strategy=self.name,
                signal="up",
                confidence=0.75,
                reason=f"Tight scalp: entry {price:.3f}, target {self.target}, stop {self.stop_loss}",
                metadata={"target": self.target, "stop": self.stop_loss}
            )
        return None
    
    def check_exit(self, data: MarketData, entry_price: float) -> Tuple[bool, str]:
        price = data.best_bid if hasattr(data, 'best_bid') else entry_price
        
        if price >= self.target:
            return True, f"Target hit: {price:.3f} >= {self.target}"
        if price <= self.stop_loss:
            return True, f"Stop loss: {price:.3f} <= {self.stop_loss}"
        return False, ""


class ScalperWideTarget(BaseStrategy):
    """
    Wide target scalper: Enter at 0.50, target 0.65 (30% gain), stop at 0.40 (20% loss)
    Hold time: 10-15 minutes
    """
    
    name: str = "ScalperWideTarget"
    
    def __init__(self):
        super().__init__()
        self.entry_threshold = 0.50
        self.target = 0.65
        self.stop_loss = 0.40
        self.max_hold_seconds = 900
        
    def generate_signal(self, data: MarketData) -> Optional[BaseSignal]:
        price = data.best_bid if hasattr(data, 'best_bid') else 0.5
        
        if abs(price - self.entry_threshold) < 0.035:
            return BaseSignal(
                strategy=self.name,
                signal="up",
                confidence=0.55,
                reason=f"Wide scalp: entry {price:.3f}, target {self.target}, stop {self.stop_loss}",
                metadata={"target": self.target, "stop": self.stop_loss}
            )
        return None
    
    def check_exit(self, data: MarketData, entry_price: float) -> Tuple[bool, str]:
        price = data.best_bid if hasattr(data, 'best_bid') else entry_price
        
        if price >= self.target:
            return True, f"Target hit: {price:.3f} >= {self.target}"
        if price <= self.stop_loss:
            return True, f"Stop loss: {price:.3f} <= {self.stop_loss}"
        return False, ""
