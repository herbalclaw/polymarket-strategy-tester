"""
AdverseSelectionFilter Strategy

Filters trades based on adverse selection risk - the risk that you're
trading against someone with better information. Uses bid-ask bounce
patterns and trade flow toxicity to avoid toxic fills.

Key insight: In prediction markets, informed traders often trade
aggressively when they have edge. By measuring the "toxicity" of
recent trades, we can avoid entering when adverse selection is high.

Reference: "The Cost of Immediacy" - Hendershott and Mendelson (2000)
"""

from typing import Optional
from collections import deque
from statistics import mean, stdev
import math

from core.base_strategy import BaseStrategy, Signal, MarketData


class AdverseSelectionFilterStrategy(BaseStrategy):
    """
    Filter trades based on adverse selection risk.
    
    Strategy logic:
    1. Measure recent trade toxicity using VPIN-like metrics
    2. Calculate bid-ask bounce frequency (high = uninformed flow)
    3. Only trade when adverse selection risk is low
    4. Use as overlay - enhances other signals by filtering bad entries
    
    This is primarily a filter, but can generate standalone signals
    when combined with extreme adverse selection readings (contrarian).
    """
    
    name = "AdverseSelectionFilter"
    description = "Filter trades based on adverse selection risk"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        config = config or {}
        
        # Trade flow tracking
        self.price_history = deque(maxlen=50)
        self.return_history = deque(maxlen=50)
        self.tick_history = deque(maxlen=100)  # +1 for up, -1 for down
        
        # Adverse selection metrics
        self.toxicity_window = self.config.get('toxicity_window', 20)
        self.bounce_threshold = self.config.get('bounce_threshold', 0.6)  # 60% bounce rate = low toxicity
        
        # Volatility tracking
        self.volatility_history = deque(maxlen=30)
        
        # Spread tracking
        self.spread_history = deque(maxlen=20)
        
        # Signal generation
        self.min_confidence = self.config.get('min_confidence', 0.62)
        
        # Cooldown
        self.last_signal_time = 0
        self.cooldown_seconds = self.config.get('cooldown_seconds', 90)
        
        # Consecutive signal tracking
        self.consecutive_same_direction = 0
        self.last_direction = None
    
    def calculate_bounce_rate(self) -> float:
        """
        Calculate bid-ask bounce rate.
        High bounce rate = price oscillating between bid/ask = uninformed flow
        Low bounce rate = directional = informed flow
        
        Returns bounce rate between 0 and 1
        """
        if len(self.tick_history) < 10:
            return 0.5
        
        ticks = list(self.tick_history)
        bounces = 0
        
        for i in range(1, len(ticks)):
            if ticks[i] != ticks[i-1]:
                bounces += 1
        
        return bounces / (len(ticks) - 1) if len(ticks) > 1 else 0.5
    
    def calculate_trade_toxicity(self) -> float:
        """
        Calculate trade toxicity using VPIN-like metric.
        High toxicity = high probability of informed trading
        
        Returns toxicity score between 0 and 1
        """
        if len(self.return_history) < self.toxicity_window:
            return 0.5
        
        returns = list(self.return_history)[-self.toxicity_window:]
        
        # Calculate return autocorrelation
        if len(returns) < 2:
            return 0.5
        
        # High absolute returns with low autocorrelation = toxic
        abs_returns = [abs(r) for r in returns]
        avg_abs_return = mean(abs_returns)
        
        # Calculate autocorrelation
        autocorr = 0.0
        if len(returns) > 1:
            mean_ret = mean(returns)
            numerator = sum((returns[i] - mean_ret) * (returns[i-1] - mean_ret) 
                          for i in range(1, len(returns)))
            denominator = sum((r - mean_ret) ** 2 for r in returns)
            autocorr = numerator / denominator if denominator != 0 else 0
        
        # Toxicity: high volatility + negative autocorrelation
        # Negative autocorrelation = reversal pattern = market making against informed flow
        toxicity = avg_abs_return * 10 * (1 - max(0, autocorr))
        
        return min(toxicity, 1.0)
    
    def calculate_volatility_regime(self) -> tuple:
        """
        Calculate current volatility regime.
        Returns (regime, current_vol, avg_vol)
        """
        if len(self.volatility_history) < 10:
            return "normal", 0.01, 0.01
        
        current_vol = self.volatility_history[-1] if self.volatility_history else 0.01
        avg_vol = mean(list(self.volatility_history)[-10:])
        
        if current_vol > avg_vol * 1.5:
            return "high", current_vol, avg_vol
        elif current_vol < avg_vol * 0.7:
            return "low", current_vol, avg_vol
        return "normal", current_vol, avg_vol
    
    def calculate_spread_regime(self) -> str:
        """
        Calculate spread regime.
        Widening spreads = adverse selection increasing
        """
        if len(self.spread_history) < 10:
            return "normal"
        
        recent_spread = mean(list(self.spread_history)[-3:])
        avg_spread = mean(list(self.spread_history))
        
        if recent_spread > avg_spread * 1.3:
            return "widening"
        elif recent_spread < avg_spread * 0.8:
            return "narrowing"
        return "normal"
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_time = data.timestamp
        current_price = data.price
        
        # Update price history
        self.price_history.append(current_price)
        
        # Calculate return
        if len(self.price_history) >= 2:
            prev_price = list(self.price_history)[-2]
            ret = (current_price - prev_price) / prev_price if prev_price > 0 else 0
            self.return_history.append(ret)
            
            # Track tick direction
            if ret > 0.0001:
                self.tick_history.append(1)
            elif ret < -0.0001:
                self.tick_history.append(-1)
            else:
                # No change - use previous or neutral
                if self.tick_history:
                    self.tick_history.append(self.tick_history[-1])
                else:
                    self.tick_history.append(0)
        
        # Update volatility
        if len(self.return_history) >= 5:
            recent_returns = list(self.return_history)[-5:]
            vol = stdev(recent_returns) if len(recent_returns) > 1 else 0
            self.volatility_history.append(vol)
        
        # Update spread history
        spread_bps = (data.ask - data.bid) / data.mid * 10000 if data.mid > 0 else 0
        self.spread_history.append(spread_bps)
        
        # Cooldown check
        if current_time - self.last_signal_time < self.cooldown_seconds:
            return None
        
        # Need enough data
        if len(self.return_history) < self.toxicity_window:
            return None
        
        # Calculate metrics
        bounce_rate = self.calculate_bounce_rate()
        toxicity = self.calculate_trade_toxicity()
        vol_regime, current_vol, avg_vol = self.calculate_volatility_regime()
        spread_regime = self.calculate_spread_regime()
        
        signal = None
        confidence = 0.0
        reason = ""
        
        # Low toxicity + high bounce rate = safe to trade with trend
        if toxicity < 0.4 and bounce_rate > self.bounce_threshold:
            # Uninformed flow dominates - trade with recent momentum
            if len(self.return_history) >= 5:
                recent_returns = list(self.return_history)[-5:]
                avg_return = mean(recent_returns)
                
                if avg_return > 0.001:  # Positive momentum
                    confidence = min(0.60 + (self.bounce_threshold - toxicity) * 0.2, 0.80)
                    signal = "up"
                    reason = f"Low toxicity ({toxicity:.2f}), high bounce ({bounce_rate:.2f}), positive flow"
                elif avg_return < -0.001:  # Negative momentum
                    confidence = min(0.60 + (self.bounce_threshold - toxicity) * 0.2, 0.80)
                    signal = "down"
                    reason = f"Low toxicity ({toxicity:.2f}), high bounce ({bounce_rate:.2f}), negative flow"
        
        # High toxicity + widening spreads = adverse selection risk
        # Generate contrarian signal (trade against toxic flow)
        elif toxicity > 0.6 and spread_regime == "widening":
            # High adverse selection - fade the move
            if len(self.return_history) >= 5:
                recent_returns = list(self.return_history)[-5:]
                avg_return = mean(recent_returns)
                
                if avg_return > 0.002:  # Strong up move - likely toxic, fade it
                    confidence = min(0.58 + toxicity * 0.2, 0.78)
                    signal = "down"
                    reason = f"High toxicity ({toxicity:.2f}), widening spreads, fade up move"
                elif avg_return < -0.002:  # Strong down move - likely toxic, fade it
                    confidence = min(0.58 + toxicity * 0.2, 0.78)
                    signal = "up"
                    reason = f"High toxicity ({toxicity:.2f}), widening spreads, fade down move"
        
        if signal and confidence >= self.min_confidence:
            self.last_signal_time = current_time
            
            # Track consecutive signals
            if signal == self.last_direction:
                self.consecutive_same_direction += 1
            else:
                self.consecutive_same_direction = 1
                self.last_direction = signal
            
            return Signal(
                strategy=self.name,
                signal=signal,
                confidence=confidence,
                reason=reason,
                metadata={
                    'toxicity': toxicity,
                    'bounce_rate': bounce_rate,
                    'vol_regime': vol_regime,
                    'spread_regime': spread_regime,
                    'current_vol': current_vol,
                    'avg_vol': avg_vol
                }
            )
        
        return None
