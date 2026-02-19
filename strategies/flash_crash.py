"""
FlashCrashStrategy - Volatility Spike Capture

Captures sudden price drops (flash crashes) in BTC 5-minute markets.
Based on the observation that sharp drops are often overreactions that
revert partially within the same window.

Key insight: When price drops >15% in <10 seconds, it often represents
panic selling or liquidity gaps rather than fundamental repricing.
Buying these dips with tight risk management yields positive expected value.

Reference: Research on Polymarket shows flash crash strategies can be
profitable when combined with proper risk controls and quick execution.
"""

from typing import Optional
from collections import deque
import time

from core.base_strategy import BaseStrategy, Signal, MarketData


class FlashCrashStrategy(BaseStrategy):
    """
    Flash crash capture strategy.
    
    Monitors for sudden price drops and buys the dip, expecting
    partial reversion within the same trading window.
    
    Key parameters:
    - drop_threshold: Minimum % drop to trigger (default 0.15 = 15%)
    - detection_window: Seconds to measure drop (default 10)
    - hold_time: Maximum seconds to hold position (default 120)
    """
    
    name = "FlashCrash"
    description = "Captures flash crashes and volatility spikes"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        
        # Flash crash detection parameters
        self.drop_threshold = self.config.get('drop_threshold', 0.15)  # 15% drop
        self.detection_window = self.config.get('detection_window', 10)  # 10 seconds
        self.hold_time = self.config.get('hold_time', 120)  # 2 minutes max hold
        
        # Risk management
        self.max_daily_trades = self.config.get('max_daily_trades', 10)
        self.cooldown_seconds = self.config.get('cooldown_seconds', 60)
        
        # Position tracking
        self.price_history = deque(maxlen=100)
        self.timestamp_history = deque(maxlen=100)
        self.daily_trade_count = 0
        self.last_trade_date = None
        self.last_signal_time = 0
        self.active_position = None
        
        # Minimum liquidity requirement
        self.min_spread_bps = self.config.get('min_spread_bps', 50)  # 0.5%
        self.max_spread_bps = self.config.get('max_spread_bps', 500)  # 5%
    
    def _reset_daily_count(self):
        """Reset daily trade counter."""
        current_date = time.strftime('%Y-%m-%d')
        if self.last_trade_date != current_date:
            self.daily_trade_count = 0
            self.last_trade_date = current_date
    
    def _calculate_drop(self, current_price: float, current_time: float) -> tuple:
        """
        Calculate price drop over detection window.
        Returns (drop_pct, reference_price, time_elapsed)
        """
        if len(self.price_history) < 2:
            return 0.0, current_price, 0.0
        
        # Find price from detection_window seconds ago
        reference_price = None
        reference_time = None
        
        for i in range(len(self.timestamp_history) - 1, -1, -1):
            if current_time - self.timestamp_history[i] >= self.detection_window:
                reference_price = self.price_history[i]
                reference_time = self.timestamp_history[i]
                break
        
        if reference_price is None or reference_price == 0:
            return 0.0, current_price, 0.0
        
        time_elapsed = current_time - reference_time
        drop_pct = (reference_price - current_price) / reference_price
        
        return drop_pct, reference_price, time_elapsed
    
    def _check_recovery_potential(self, current_price: float) -> float:
        """
        Assess recovery potential based on recent price action.
        Returns confidence score 0-1.
        """
        if len(self.price_history) < 5:
            return 0.5
        
        recent_prices = list(self.price_history)[-10:]
        
        # Check if price has stabilized or started recovering
        if len(recent_prices) >= 3:
            # Look for stabilization (smaller price changes)
            recent_changes = [
                abs(recent_prices[i] - recent_prices[i-1]) / recent_prices[i-1]
                for i in range(1, len(recent_prices))
            ]
            avg_change = sum(recent_changes) / len(recent_changes) if recent_changes else 0
            
            # Lower volatility after drop suggests stabilization
            if avg_change < 0.005:  # Less than 0.5% average change
                return 0.8
            elif avg_change < 0.01:  # Less than 1% average change
                return 0.65
        
        return 0.55
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_time = data.timestamp
        current_price = data.price
        
        # Reset daily counter if needed
        self._reset_daily_count()
        
        # Check daily trade limit
        if self.daily_trade_count >= self.max_daily_trades:
            return None
        
        # Cooldown check
        if current_time - self.last_signal_time < self.cooldown_seconds:
            return None
        
        # Update history
        self.price_history.append(current_price)
        self.timestamp_history.append(current_time)
        
        # Check spread is reasonable
        if not (self.min_spread_bps <= data.spread_bps <= self.max_spread_bps):
            return None
        
        # Calculate price drop
        drop_pct, reference_price, time_elapsed = self._calculate_drop(current_price, current_time)
        
        # Check for flash crash condition
        if drop_pct >= self.drop_threshold and time_elapsed >= self.detection_window * 0.8:
            # Assess recovery potential
            recovery_confidence = self._check_recovery_potential(current_price)
            
            # Calculate confidence based on drop magnitude and recovery potential
            base_confidence = 0.60
            drop_boost = min(drop_pct * 0.5, 0.15)  # Up to 15% boost for large drops
            recovery_boost = (recovery_confidence - 0.5) * 0.2
            
            confidence = base_confidence + drop_boost + recovery_boost
            confidence = min(confidence, 0.85)
            
            if confidence >= self.min_confidence:
                self.last_signal_time = current_time
                self.daily_trade_count += 1
                
                return Signal(
                    strategy=self.name,
                    signal='up',  # Buy the dip
                    confidence=confidence,
                    reason=f"Flash crash: {drop_pct:.1%} drop in {time_elapsed:.0f}s",
                    metadata={
                        'drop_pct': drop_pct,
                        'reference_price': reference_price,
                        'current_price': current_price,
                        'detection_window': self.detection_window,
                        'recovery_confidence': recovery_confidence,
                        'daily_trade_count': self.daily_trade_count
                    }
                )
        
        return None
