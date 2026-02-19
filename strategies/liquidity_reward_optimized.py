"""
LiquidityRewardOptimized Strategy

Maximizes Polymarket liquidity rewards by optimizing order placement
according to the reward formula mechanics. Unlike simple market making,
this strategy specifically targets the reward calculation parameters.

Key insights from research:
1. Rewards use quadratic spread function - heavily penalizes quotes away from midpoint
2. Adjusted Midpoint filters out tiny dust orders (< minimum incentive size)
3. Single-sided penalty factor (~1/3) means two-sided liquidity is 3x more efficient
4. Near extremes (prob < 0.10 or > 0.90), both sides are REQUIRED

Reference: "Reverse Engineering Polymarket Liquidity Rewards" - Wang (2025)
"""

from typing import Optional
from collections import deque
import statistics
import time

from core.base_strategy import BaseStrategy, Signal, MarketData


class LiquidityRewardOptimizedStrategy(BaseStrategy):
    """
    Optimize for Polymarket liquidity rewards while capturing spread.
    
    Strategy mechanics:
    1. Quote as close to adjusted midpoint as possible
    2. Maintain minimum incentive size to qualify
    3. Keep two-sided quotes to avoid 1/3 penalty
    4. Adjust for inventory skew but stay within bounds
    5. Exit positions that risk hitting max inventory
    
    Edge comes from:
    - Daily USDC liquidity rewards
    - Spread capture on fills
    - Lower effective fees as maker
    """
    
    name = "LiquidityRewardOptimized"
    description = "Optimize for Polymarket liquidity rewards and spread capture"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        config = config or {}
        
        # Reward optimization parameters
        self.target_spread_bps = self.config.get('target_spread_bps', 20)  # Tight spread near mid
        self.min_incentive_size = self.config.get('min_incentive_size', 100)  # Minimum to qualify
        self.max_spread_bps = self.config.get('max_spread_bps', 50)  # Don't quote if spread too wide
        
        # Inventory management
        self.max_inventory = self.config.get('max_inventory', 500)  # Max position
        self.inventory_skew_limit = self.config.get('inventory_skew_limit', 0.3)  # 30% max skew
        self.inventory_adjustment = self.config.get('inventory_adjustment', 0.02)  # 2% price adjust
        
        # Market conditions
        self.min_volume_24h = self.config.get('min_volume_24h', 50000)  # $50K min volume
        self.max_volatility = self.config.get('max_volatility', 0.25)  # 25% max vol
        
        # Tracking
        self.spread_history = deque(maxlen=30)
        self.fill_history = deque(maxlen=20)
        self.inventory = 0  # Positive = long YES, Negative = short YES (long NO)
        
        # Cooldown
        self.last_signal_time = 0
        self.cooldown_seconds = self.config.get('cooldown_seconds', 30)
        
        # Reward tracking
        self.estimated_daily_rewards = 0.0
        self.reward_qualifying_time = 0
    
    def calculate_reward_score(self, spread_bps: float, distance_from_mid: float) -> float:
        """
        Estimate reward score based on distance from adjusted midpoint.
        Quadratic penalty: closer to mid = exponentially higher rewards.
        """
        # Quadratic penalty formula approximation
        # Score ∝ 1 / (distance^2) when within qualifying range
        if distance_from_mid <= 0:
            return 1.0
        
        # Normalize: at target spread, score = 0.5
        normalized_distance = distance_from_mid / (self.target_spread_bps / 10000)
        score = 1.0 / (1.0 + normalized_distance ** 2)
        
        return score
    
    def get_inventory_skew(self) -> float:
        """Calculate inventory skew: -1 to 1, where 0 is neutral."""
        if self.max_inventory == 0:
            return 0.0
        return self.inventory / self.max_inventory
    
    def adjust_quotes_for_inventory(self, bid: float, ask: float) -> tuple:
        """
        Adjust quotes based on inventory skew.
        If long (positive inventory), lower bid and ask to sell more.
        If short (negative inventory), raise bid and ask to buy more.
        """
        skew = self.get_inventory_skew()
        
        if abs(skew) > self.inventory_skew_limit:
            # Strong skew - need to reduce inventory aggressively
            adjustment = skew * self.inventory_adjustment * 2
        else:
            # Normal skew - gentle adjustment
            adjustment = skew * self.inventory_adjustment
        
        # Adjust: if long (skew > 0), we want to sell more (lower prices)
        # If short (skew < 0), we want to buy more (higher prices)
        adjusted_bid = bid - adjustment
        adjusted_ask = ask - adjustment
        
        # Ensure valid prices
        adjusted_bid = max(0.01, min(0.99, adjusted_bid))
        adjusted_ask = max(0.01, min(0.99, adjusted_ask))
        
        return adjusted_bid, adjusted_ask, skew
    
    def check_market_conditions(self, data: MarketData) -> tuple:
        """
        Check if market conditions are suitable for liquidity provision.
        Returns: (is_suitable, reason)
        """
        # Check volume
        if data.volume_24h < self.min_volume_24h:
            return False, f"Low volume: ${data.volume_24h:,.0f} < ${self.min_volume_24h:,.0f}"
        
        # Check spread
        spread = data.ask - data.bid
        mid = data.mid
        spread_bps = (spread / mid * 10000) if mid > 0 else 0
        
        if spread_bps > self.max_spread_bps:
            return False, f"Wide spread: {spread_bps:.0f} bps > {self.max_spread_bps:.0f} bps"
        
        # Check if near extremes (both sides required for rewards)
        if data.price < 0.10 or data.price > 0.90:
            # Near extremes - can still trade but need both sides
            pass
        
        return True, "Conditions suitable"
    
    def generate_signal(self, data: MarketData) -> Optional[Signal]:
        current_time = data.timestamp
        
        # Cooldown check
        if current_time - self.last_signal_time < self.cooldown_seconds:
            return None
        
        # Check market conditions
        is_suitable, reason = self.check_market_conditions(data)
        if not is_suitable:
            return None
        
        # Calculate spread metrics
        spread = data.ask - data.bid
        mid = data.mid
        spread_bps = (spread / mid * 10000) if mid > 0 else 0
        
        self.spread_history.append(spread_bps)
        
        # Calculate optimal quote prices
        half_spread = self.target_spread_bps / 10000 / 2
        target_bid = mid - half_spread
        target_ask = mid + half_spread
        
        # Adjust for inventory
        adj_bid, adj_ask, skew = self.adjust_quotes_for_inventory(target_bid, target_ask)
        
        # Determine if we should provide liquidity or take a directional position
        # If inventory is near limits, we need to reduce
        if abs(skew) > 0.8:
            # Near inventory limit - take directional trade to reduce
            if skew > 0:
                # Too long - sell
                signal_type = "down"
                confidence = 0.70
                reason = f"Inventory reduction: skew {skew:.1%}, exiting long"
            else:
                # Too short - buy
                signal_type = "up"
                confidence = 0.70
                reason = f"Inventory reduction: skew {skew:.1%}, covering short"
        else:
            # Normal operation - capture spread with slight directional bias
            # Prefer the side that helps inventory balance
            if skew > 0.2:
                # Slightly long - prefer selling
                signal_type = "down"
                confidence = 0.62
                reason = f"Liquidity provision: spread {spread_bps:.0f}bps, skew {skew:.1%}, favor sell"
            elif skew < -0.2:
                # Slightly short - prefer buying
                signal_type = "up"
                confidence = 0.62
                reason = f"Liquidity provision: spread {spread_bps:.0f}bps, skew {skew:.1%}, favor buy"
            else:
                # Balanced - take either side based on microstructure
                # Check if price is closer to bid or ask
                price_position = (data.price - data.bid) / spread if spread > 0 else 0.5
                
                if price_position < 0.4:
                    signal_type = "up"
                    confidence = 0.60
                    reason = f"Liquidity provision: price near bid, buying for spread capture"
                elif price_position > 0.6:
                    signal_type = "down"
                    confidence = 0.60
                    reason = f"Liquidity provision: price near ask, selling for spread capture"
                else:
                    # Price at mid - no strong signal
                    return None
        
        self.last_signal_time = current_time
        
        return Signal(
            strategy=self.name,
            signal=signal_type,
            confidence=confidence,
            reason=reason,
            metadata={
                'spread_bps': spread_bps,
                'target_bid': adj_bid,
                'target_ask': adj_ask,
                'inventory': self.inventory,
                'skew': skew,
                'reward_score': self.calculate_reward_score(spread_bps, half_spread)
            }
        )
    
    def on_trade_complete(self, trade_result: dict):
        """Update inventory tracking."""
        side = trade_result.get('side', '').upper()
        size = trade_result.get('size', 0)
        
        if side == 'UP':
            self.inventory += size
        elif side == 'DOWN':
            self.inventory -= size
        
        self.fill_history.append({
            'side': side,
            'size': size,
            'inventory_after': self.inventory
        })
