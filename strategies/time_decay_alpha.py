"""
TimeDecayAlpha Strategy for Polymarket BTC 5-Minute Markets

This strategy exploits the time decay of uncertainty premium in prediction markets.
As markets approach resolution, the uncertainty premium decays, creating predictable
price movements toward the true probability.

Research Basis:
- Markets far from resolution often misprice due to uncertainty premium
- Time decay creates alpha as uncertainty resolves
- Short-term markets (5-min) have accelerated decay patterns

Edge: Capture the decay of uncertainty premium as market approaches resolution.
"""

import numpy as np
from typing import Dict, Any, Optional
from core.base_strategy import BaseStrategy


class TimeDecayAlpha(BaseStrategy):
    """
    Strategy that exploits time decay of uncertainty premium.
    
    In prediction markets, prices often contain an uncertainty premium that
    decays as the resolution time approaches. This strategy identifies when
    the decay creates mispricing opportunities.
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        config = config or {}
        self.name = "TimeDecayAlpha"
        self.description = "Exploits time decay of uncertainty premium in short-term markets"
        
        # Strategy parameters
        self.time_threshold = config.get('time_threshold', 60)  # Seconds before close to activate
        self.decay_rate_threshold = config.get('decay_rate_threshold', 0.02)  # Min decay rate
        self.confidence_threshold = config.get('confidence_threshold', 0.65)  # Min confidence
        self.position_size = config.get('position_size', 1.0)
        
        # State tracking
        self.price_history = []
        self.time_history = []
        self.max_history = 20
        
    def calculate_decay_rate(self) -> float:
        """Calculate the rate of price decay toward extremes."""
        if len(self.price_history) < 5:
            return 0.0
        
        # Calculate exponential decay rate
        recent_prices = np.array(self.price_history[-5:])
        times = np.arange(len(recent_prices))
        
        # Fit exponential decay: price = a * exp(-b * t) + c
        try:
            # Simple linear approximation of log-transformed prices
            log_prices = np.log(recent_prices + 0.01)  # Add small constant to avoid log(0)
            slope = np.polyfit(times, log_prices, 1)[0]
            return abs(slope)
        except:
            return 0.0
    
    def estimate_true_probability(self, current_price: float, time_to_close: float) -> float:
        """
        Estimate true probability by adjusting for time decay.
        
        As t -> 0, price should converge to 0 or 1.
        Current price reflects: true_prob + uncertainty_premium * f(time)
        """
        if time_to_close <= 0:
            return current_price
        
        # Uncertainty premium decays with time
        # Higher time_to_close = higher uncertainty premium
        decay_factor = np.exp(-self.decay_rate_threshold * (300 - time_to_close) / 60)
        
        # Adjust price by removing estimated uncertainty premium
        if current_price > 0.5:
            # Price inflated by uncertainty
            true_prob = current_price - (current_price - 0.5) * decay_factor * 0.1
        else:
            # Price deflated by uncertainty  
            true_prob = current_price + (0.5 - current_price) * decay_factor * 0.1
        
        return np.clip(true_prob, 0.01, 0.99)
    
    def generate_signal(self, data) -> Optional[Dict[str, Any]]:
        """
        Generate trading signal based on time decay analysis.
        
        Args:
            data: Market data including price, time_to_close, orderbook
            
        Returns:
            Signal dict or None
        """
        # Handle both dict and MarketData objects
        if hasattr(data, 'price'):
            current_price = data.price
            # Calculate time to close from market_end_time if available
            if hasattr(data, 'market_end_time') and data.market_end_time:
                import time
                time_to_close = max(0, data.market_end_time - time.time())
            else:
                time_to_close = 300
        else:
            current_price = data.get('price', 0.5) if isinstance(data, dict) else 0.5
            time_to_close = data.get('time_to_close', 300) if isinstance(data, dict) else 300
        
        # Update history
        self.price_history.append(current_price)
        self.time_history.append(time_to_close)
        
        if len(self.price_history) > self.max_history:
            self.price_history.pop(0)
            self.time_history.pop(0)
        
        # Only trade near market close
        if time_to_close > self.time_threshold:
            return None
        
        # Need sufficient history
        if len(self.price_history) < 5:
            return None
        
        # Calculate decay rate
        decay_rate = self.calculate_decay_rate()
        
        if decay_rate < self.decay_rate_threshold:
            return None
        
        # Estimate true probability
        true_prob = self.estimate_true_probability(current_price, time_to_close)
        
        # Calculate edge
        edge = abs(true_prob - current_price)
        
        # Generate signal if edge is significant
        if edge > 0.05 and true_prob > self.confidence_threshold:
            return {
                'side': 'UP',
                'confidence': true_prob,
                'edge': edge,
                'expected_return': edge * (1 - current_price),
                'time_to_close': time_to_close,
                'decay_rate': decay_rate
            }
        elif edge > 0.05 and true_prob < (1 - self.confidence_threshold):
            return {
                'side': 'DOWN',
                'confidence': 1 - true_prob,
                'edge': edge,
                'expected_return': edge * current_price,
                'time_to_close': time_to_close,
                'decay_rate': decay_rate
            }
        
        return None
    
    def calculate_position_size(self, signal: Dict[str, Any]) -> float:
        """Calculate position size based on confidence and time to close."""
        base_size = self.position_size
        confidence_multiplier = signal['confidence']
        
        # Increase size as we get closer to close (more certainty)
        time_factor = 1 + (60 - signal.get('time_to_close', 60)) / 60
        
        return base_size * confidence_multiplier * min(time_factor, 2.0)
    
    def should_exit(self, current_price: float, position: Dict[str, Any], 
                    data: Dict[str, Any]) -> bool:
        """Determine if position should be exited."""
        time_to_close = data.get('time_to_close', 0)
        
        # Exit if very close to close
        if time_to_close < 10:
            return True
        
        # Exit if edge has been captured
        entry_price = position.get('entry_price', current_price)
        side = position.get('side', 'UP')
        
        if side == 'UP':
            profit = current_price - entry_price
        else:
            profit = entry_price - current_price
        
        # Take profit at 50% of expected edge
        expected_edge = position.get('expected_edge', 0.1)
        if profit > expected_edge * 0.5:
            return True
        
        # Stop loss
        if profit < -0.15:
            return True
        
        return False
    
    def get_params(self) -> Dict[str, Any]:
        """Get strategy parameters for optimization."""
        return {
            'time_threshold': self.time_threshold,
            'decay_rate_threshold': self.decay_rate_threshold,
            'confidence_threshold': self.confidence_threshold,
            'position_size': self.position_size
        }
    
    def set_params(self, params: Dict[str, Any]):
        """Set strategy parameters."""
        self.time_threshold = params.get('time_threshold', self.time_threshold)
        self.decay_rate_threshold = params.get('decay_rate_threshold', self.decay_rate_threshold)
        self.confidence_threshold = params.get('confidence_threshold', self.confidence_threshold)
        self.position_size = params.get('position_size', self.position_size)
