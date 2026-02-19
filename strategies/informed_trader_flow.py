"""
InformedTraderFlow Strategy for Polymarket BTC 5-Minute Markets

This strategy detects informed trader flow by analyzing order flow patterns
that indicate smart money activity. Informed traders often leave footprints
in the orderbook and trade flow that can be detected and followed.

Research Basis:
- Academic research ("Unravelling the Probabilistic Forest") analyzed 86M transactions
- Top traders systematically capture pricing errors through informed flow
- Whale activity often precedes significant price movements
- Order flow toxicity indicators can predict adverse selection

Edge: Detect and follow informed trader flow before prices fully adjust.
"""

import numpy as np
from typing import Dict, Any, Optional, List
from collections import deque
from core.base_strategy import BaseStrategy


class InformedTraderFlow(BaseStrategy):
    """
    Strategy that detects and follows informed trader flow.
    
    Informed traders (whales, insiders, sophisticated algos) often trade
    in predictable patterns. This strategy uses order flow analysis to
    detect their activity and follow their trades.
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        config = config or {}
        self.name = "InformedTraderFlow"
        self.description = "Detects and follows informed trader flow patterns"
        
        # Handle None config
        config = config or {}
        
        # Strategy parameters
        self.flow_window = config.get('flow_window', 10)  # Trades to analyze
        self.min_flow_strength = config.get('min_flow_strength', 0.6)  # Min flow confidence
        self.volume_threshold = config.get('volume_threshold', 1.5)  # Relative volume
        self.position_size = config.get('position_size', 1.0)
        
        # State tracking
        self.trade_history = deque(maxlen=50)
        self.volume_history = deque(maxlen=20)
        self.flow_score_history = deque(maxlen=10)
        
        # Informed flow indicators
        self.large_trade_threshold = config.get('large_trade_threshold', 1000)  # USD
        self.aggressive_buy_ratio = 0.0
        self.aggressive_sell_ratio = 0.0
        
    def analyze_trade_flow(self) -> Dict[str, float]:
        """
        Analyze recent trade flow for informed activity.
        
        Returns:
            Dict with flow metrics
        """
        if len(self.trade_history) < self.flow_window:
            return {'flow_score': 0.0, 'confidence': 0.0}
        
        recent_trades = list(self.trade_history)[-self.flow_window:]
        
        # Calculate aggressive buy/sell ratios
        buy_volume = sum(t['size'] for t in recent_trades if t['side'] == 'buy')
        sell_volume = sum(t['size'] for t in recent_trades if t['side'] == 'sell')
        total_volume = buy_volume + sell_volume
        
        if total_volume == 0:
            return {'flow_score': 0.0, 'confidence': 0.0}
        
        buy_ratio = buy_volume / total_volume
        sell_ratio = sell_volume / total_volume
        
        # Analyze large trades (potential informed flow)
        large_buys = sum(t['size'] for t in recent_trades 
                        if t['side'] == 'buy' and t['size'] > self.large_trade_threshold)
        large_sells = sum(t['size'] for t in recent_trades 
                         if t['side'] == 'sell' and t['size'] > self.large_trade_threshold)
        
        # Calculate flow score
        # Positive = informed buying, Negative = informed selling
        flow_score = 0.0
        
        # Weight by volume imbalance
        if buy_ratio > 0.6:
            flow_score += (buy_ratio - 0.5) * 2  # Scale to 0-1
        elif sell_ratio > 0.6:
            flow_score -= (sell_ratio - 0.5) * 2
        
        # Weight by large trade activity
        large_total = large_buys + large_sells
        if large_total > 0:
            large_buy_ratio = large_buys / large_total
            if large_buy_ratio > 0.7:
                flow_score += 0.3
            elif large_buy_ratio < 0.3:
                flow_score -= 0.3
        
        # Calculate confidence based on volume
        avg_volume = np.mean(list(self.volume_history)) if self.volume_history else total_volume
        volume_confidence = min(total_volume / (avg_volume + 1), 2.0) / 2.0
        
        return {
            'flow_score': np.clip(flow_score, -1.0, 1.0),
            'confidence': volume_confidence,
            'buy_ratio': buy_ratio,
            'sell_ratio': sell_ratio,
            'large_buy_ratio': large_buys / (large_total + 1),
            'total_volume': total_volume
        }
    
    def detect_toxic_flow(self, data) -> float:
        """
        Detect toxic flow that might indicate adverse selection.
        
        Returns:
            Toxicity score (0-1, higher = more toxic)
        """
        # Handle both dict and MarketData objects
        if hasattr(data, 'order_book'):
            orderbook = data.order_book or {}
        else:
            orderbook = data.get('orderbook', {}) if isinstance(data, dict) else {}
        
        if not orderbook:
            return 0.0
        
        # Check for order book imbalance
        bid_volume = sum(b['size'] for b in orderbook.get('bids', [])[:5])
        ask_volume = sum(a['size'] for a in orderbook.get('asks', [])[:5])
        
        total = bid_volume + ask_volume
        if total == 0:
            return 0.0
        
        imbalance = abs(bid_volume - ask_volume) / total
        
        # High imbalance can indicate informed flow
        return min(imbalance, 1.0)
    
    def generate_signal(self, data) -> Optional[Dict[str, Any]]:
        """
        Generate trading signal based on informed flow detection.
        
        Args:
            data: Market data including trades, orderbook, price
            
        Returns:
            Signal dict or None
        """
        # Handle both dict and MarketData objects
        if hasattr(data, 'price'):
            current_price = data.price
            trades = data.metadata.get('trades', []) if data.metadata else []
        else:
            current_price = data.get('price', 0.5) if isinstance(data, dict) else 0.5
            trades = data.get('trades', []) if isinstance(data, dict) else []
        
        # Update trade history
        for trade in trades:
            self.trade_history.append(trade)
        
        # Update volume history
        if trades:
            total_volume = sum(t['size'] for t in trades)
            self.volume_history.append(total_volume)
        
        # Need sufficient history
        if len(self.trade_history) < self.flow_window:
            return None
        
        # Analyze flow
        flow_analysis = self.analyze_trade_flow()
        flow_score = flow_analysis['flow_score']
        confidence = flow_analysis['confidence']
        
        # Check for toxic flow
        toxicity = self.detect_toxic_flow(data)
        
        # Adjust confidence based on toxicity
        # If flow is toxic, be more confident (informed traders are active)
        adjusted_confidence = confidence * (0.5 + 0.5 * toxicity)
        
        # Track flow score
        self.flow_score_history.append(flow_score)
        
        # Generate signal if flow is strong enough
        if abs(flow_score) > self.min_flow_strength and adjusted_confidence > 0.5:
            if flow_score > 0:
                # Informed buying detected
                edge = flow_score * adjusted_confidence
                return {
                    'side': 'UP',
                    'confidence': adjusted_confidence,
                    'edge': edge,
                    'expected_return': edge * (1 - current_price),
                    'flow_score': flow_score,
                    'toxicity': toxicity,
                    'buy_ratio': flow_analysis['buy_ratio']
                }
            else:
                # Informed selling detected
                edge = abs(flow_score) * adjusted_confidence
                return {
                    'side': 'DOWN',
                    'confidence': adjusted_confidence,
                    'edge': edge,
                    'expected_return': edge * current_price,
                    'flow_score': flow_score,
                    'toxicity': toxicity,
                    'sell_ratio': flow_analysis['sell_ratio']
                }
        
        return None
    
    def calculate_position_size(self, signal: Dict[str, Any]) -> float:
        """Calculate position size based on flow strength and confidence."""
        base_size = self.position_size
        flow_score = abs(signal.get('flow_score', 0))
        confidence = signal.get('confidence', 0.5)
        
        # Scale by flow strength and confidence
        return base_size * flow_score * confidence
    
    def should_exit(self, current_price: float, position: Dict[str, Any], 
                    data: Dict[str, Any]) -> bool:
        """Determine if position should be exited."""
        # Check if flow has reversed
        flow_analysis = self.analyze_trade_flow()
        current_flow = flow_analysis['flow_score']
        
        side = position.get('side', 'UP')
        
        # Exit if flow has reversed significantly
        if side == 'UP' and current_flow < -0.3:
            return True
        if side == 'DOWN' and current_flow > 0.3:
            return True
        
        # Take profit/stop loss
        entry_price = position.get('entry_price', current_price)
        
        if side == 'UP':
            profit = current_price - entry_price
        else:
            profit = entry_price - current_price
        
        expected_edge = position.get('expected_edge', 0.1)
        
        # Take profit at 70% of expected edge
        if profit > expected_edge * 0.7:
            return True
        
        # Stop loss
        if profit < -0.1:
            return True
        
        return False
    
    def get_flow_metrics(self) -> Dict[str, Any]:
        """Get current flow metrics for monitoring."""
        flow_analysis = self.analyze_trade_flow()
        
        return {
            'current_flow_score': flow_analysis['flow_score'],
            'confidence': flow_analysis['confidence'],
            'buy_ratio': flow_analysis['buy_ratio'],
            'sell_ratio': flow_analysis['sell_ratio'],
            'total_volume': flow_analysis['total_volume'],
            'history_length': len(self.trade_history)
        }
    
    def get_params(self) -> Dict[str, Any]:
        """Get strategy parameters for optimization."""
        return {
            'flow_window': self.flow_window,
            'min_flow_strength': self.min_flow_strength,
            'volume_threshold': self.volume_threshold,
            'position_size': self.position_size,
            'large_trade_threshold': self.large_trade_threshold
        }
    
    def set_params(self, params: Dict[str, Any]):
        """Set strategy parameters."""
        self.flow_window = params.get('flow_window', self.flow_window)
        self.min_flow_strength = params.get('min_flow_strength', self.min_flow_strength)
        self.volume_threshold = params.get('volume_threshold', self.volume_threshold)
        self.position_size = params.get('position_size', self.position_size)
        self.large_trade_threshold = params.get('large_trade_threshold', self.large_trade_threshold)
