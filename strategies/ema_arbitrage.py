from typing import Optional, Dict, List
from collections import deque
import statistics

from core.base_strategy import BaseStrategy, Signal, MarketData


class EMAArbitrageStrategy(BaseStrategy):
    """
    EMA Crossover + RSI + ROC Arbitrage Strategy
    
    Based on the $427K PNL arbitrage bot from @TVS_Kolia.
    
    Signal generation (every 10 seconds):
    - EMA(5) vs EMA(15) crossover
    - RSI(14) 
    - Rate of Change (ROC)
    
    Entry: When 2 out of 3 indicators match
    - UP signal → Buy YES token
    - DOWN signal → Buy NO token
    
    Position sizing: Fractional Kelly Criterion (25%)
    """
    
    name = "EMAArbitrage"
    description = "EMA crossover + RSI + ROC arbitrage strategy"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        
        # Price history for EMA calculation
        self.price_history: deque = deque(maxlen=50)  # Need at least 15 for EMA(15)
        self.ema_fast_period = 5
        self.ema_slow_period = 15
        self.rsi_period = 14
        self.roc_period = 10
        
        # Thresholds
        self.rsi_overbought = self.config.get('rsi_overbought', 70)
        self.rsi_oversold = self.config.get('rsi_oversold', 30)
        self.roc_threshold = self.config.get('roc_threshold', 0.1)  # 0.1% ROC threshold
        
        # Kelly criterion fraction
        self.kelly_fraction = self.config.get('kelly_fraction', 0.25)
        
        # Track last signal to avoid churn
        self.last_signal_time = 0
        self.min_signal_interval = 10  # 10 seconds between signals
    
    def calculate_ema(self, prices: List[float], period: int) -> float:
        """Calculate Exponential Moving Average."""
        if len(prices) < period:
            return sum(prices) / len(prices)  # Use SMA until enough data
        
        multiplier = 2 / (period + 1)
        ema = sum(prices[:period]) / period  # Start with SMA
        
        for price in prices[period:]:
            ema = (price - ema) * multiplier + ema
        
        return ema
    
    def calculate_rsi(self, prices: List[float], period: int = 14) -> float:
        """Calculate Relative Strength Index."""
        if len(prices) < period + 1:
            return 50  # Neutral if not enough data
        
        gains = []
        losses = []
        
        for i in range(1, len(prices)):
            change = prices[i] - prices[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        # Use only last `period` values
        gains = gains[-period:]
        losses = losses[-period:]
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            return 100 if avg_gain > 0 else 50
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def calculate_roc(self, prices: List[float], period: int = 10) -> float:
        """Calculate Rate of Change."""
        if len(prices) < period + 1:
            return 0
        
        current = prices[-1]
        past = prices[-(period + 1)]
        
        if past == 0:
            return 0
        
        roc = ((current - past) / past) * 100
        return roc
    
    def calculate_kelly_size(self, win_rate: float, avg_win: float, avg_loss: float) -> float:
        """Calculate Kelly Criterion bet size."""
        if avg_loss == 0:
            return 0.1  # Default small size
        
        # Kelly formula: (bp - q) / b
        # where b = avg_win/avg_loss, p = win_rate, q = 1-p
        b = avg_win / avg_loss
        p = win_rate
        q = 1 - p
        
        kelly = (b * p - q) / b if b != 0 else 0
        
        # Apply fractional Kelly (25%)
        return max(0, kelly * self.kelly_fraction)
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        # Rate limit signals
        current_time = data.timestamp
        if current_time - self.last_signal_time < self.min_signal_interval:
            return None
        
        # Store price
        self.price_history.append(data.price)
        
        # Need minimum data
        min_required = max(self.ema_slow_period, self.rsi_period, self.roc_period) + 5
        if len(self.price_history) < min_required:
            return None
        
        prices = list(self.price_history)
        
        # Calculate indicators
        ema_fast = self.calculate_ema(prices, self.ema_fast_period)
        ema_slow = self.calculate_ema(prices, self.ema_slow_period)
        rsi = self.calculate_rsi(prices, self.rsi_period)
        roc = self.calculate_roc(prices, self.roc_period)
        
        # Generate individual signals
        signals = {
            'ema': None,
            'rsi': None,
            'roc': None
        }
        
        # EMA signal: Fast above slow = UP, Fast below slow = DOWN
        if ema_fast > ema_slow * 1.001:
            signals['ema'] = 'up'
        elif ema_fast < ema_slow * 0.999:
            signals['ema'] = 'down'
        
        # RSI signal: Oversold = UP (bounce), Overbought = DOWN (pullback)
        if rsi < self.rsi_oversold:
            signals['rsi'] = 'up'
        elif rsi > self.rsi_overbought:
            signals['rsi'] = 'down'
        
        # ROC signal: Positive = UP, Negative = DOWN
        if roc > self.roc_threshold:
            signals['roc'] = 'up'
        elif roc < -self.roc_threshold:
            signals['roc'] = 'down'
        
        # Count matching signals
        up_count = sum(1 for s in signals.values() if s == 'up')
        down_count = sum(1 for s in signals.values() if s == 'down')
        
        # Need at least 2 out of 3 indicators to match
        final_signal = None
        confidence = 0.0
        reason = ""
        
        if up_count >= 2:
            final_signal = 'up'
            confidence = 0.5 + (up_count - 2) * 0.15 + abs(roc) * 0.01
            reason = f"EMA:{signals['ema']}, RSI:{rsi:.1f}, ROC:{roc:.2f}% | {up_count}/3 UP"
        elif down_count >= 2:
            final_signal = 'down'
            confidence = 0.5 + (down_count - 2) * 0.15 + abs(roc) * 0.01
            reason = f"EMA:{signals['ema']}, RSI:{rsi:.1f}, ROC:{roc:.2f}% | {down_count}/3 DOWN"
        
        if final_signal:
            self.last_signal_time = current_time
            
            return Signal(
                strategy=self.name,
                signal=final_signal,
                confidence=min(confidence, 0.9),
                reason=reason,
                metadata={
                    'ema_fast': ema_fast,
                    'ema_slow': ema_slow,
                    'rsi': rsi,
                    'roc': roc,
                    'signals_matched': up_count if final_signal == 'up' else down_count
                }
            )
        
        return None
