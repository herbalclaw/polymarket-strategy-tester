"""
Risk management module for trading strategies.
Provides configurable limits to prevent over-trading and large losses.
"""
import logging
from typing import Dict, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class RiskLimits:
    """Risk limit configuration"""
    max_order_size: float = 100.0          # Max $ per order
    max_position_size: float = 500.0       # Max $ per position
    max_total_exposure: float = 1000.0     # Max total exposure
    max_daily_loss: float = 100.0          # Max daily loss
    max_drawdown_pct: float = 0.20         # Max 20% drawdown
    max_trades_per_hour: int = 20          # Rate limit
    min_spread_pct: float = 0.005          # Min 0.5% spread to trade
    max_spread_pct: float = 0.10           # Max 10% spread (avoid illiquid)


class RiskManager:
    """
    Centralized risk management for all trading strategies.
    
    Tracks:
    - Position sizes
    - Daily P&L
    - Drawdown
    - Trade frequency
    - Exposure limits
    """

    def __init__(self, limits: Optional[RiskLimits] = None):
        self.limits = limits or RiskLimits()
        self.daily_pnl: float = 0.0
        self.peak_capital: float = 0.0
        self.current_exposure: float = 0.0
        self.positions: Dict[str, Dict] = {}
        self.trades_today: int = 0
        self.trade_times: list = []
        self.last_reset: datetime = datetime.now()

    def reset_daily(self) -> None:
        """Reset daily counters"""
        now = datetime.now()
        if now.date() != self.last_reset.date():
            self.daily_pnl = 0.0
            self.trades_today = 0
            self.trade_times = []
            self.last_reset = now
            logger.info("Daily risk counters reset")

    def check_order_allowed(
        self,
        strategy_name: str,
        order_size: float,
        spread_pct: float,
        current_capital: float
    ) -> tuple[bool, str]:
        """
        Check if an order is allowed under risk limits.
        
        Returns:
            (allowed: bool, reason: str)
        """
        self.reset_daily()

        # Check order size
        if order_size > self.limits.max_order_size:
            return False, f"Order size ${order_size:.2f} exceeds max ${self.limits.max_order_size}"

        # Check spread
        if spread_pct < self.limits.min_spread_pct:
            return False, f"Spread {spread_pct:.2%} below minimum {self.limits.min_spread_pct:.2%}"
        
        if spread_pct > self.limits.max_spread_pct:
            return False, f"Spread {spread_pct:.2%} above maximum {self.limits.max_spread_pct:.2%}"

        # Check daily loss limit
        if self.daily_pnl < -self.limits.max_daily_loss:
            return False, f"Daily loss ${abs(self.daily_pnl):.2f} exceeds limit ${self.limits.max_daily_loss}"

        # Check drawdown
        if self.peak_capital > 0:
            drawdown = (self.peak_capital - current_capital) / self.peak_capital
            if drawdown > self.limits.max_drawdown_pct:
                return False, f"Drawdown {drawdown:.2%} exceeds limit {self.limits.max_drawdown_pct:.2%}"

        # Check exposure
        new_exposure = self.current_exposure + order_size
        if new_exposure > self.limits.max_total_exposure:
            return False, f"Exposure ${new_exposure:.2f} would exceed limit ${self.limits.max_total_exposure}"

        # Check trade frequency
        now = datetime.now()
        hour_ago = now - timedelta(hours=1)
        recent_trades = sum(1 for t in self.trade_times if t > hour_ago)
        
        if recent_trades >= self.limits.max_trades_per_hour:
            return False, f"Trade rate limit: {recent_trades} trades in last hour"

        return True, "OK"

    def record_trade(
        self,
        strategy_name: str,
        market_id: str,
        side: str,
        size: float,
        price: float,
        pnl: float = 0.0
    ) -> None:
        """Record a trade for risk tracking"""
        self.reset_daily()
        
        self.trades_today += 1
        self.trade_times.append(datetime.now())
        self.daily_pnl += pnl
        
        # Update exposure
        position_key = f"{strategy_name}:{market_id}"
        
        if side == "EXIT":
            self.current_exposure -= size
            if position_key in self.positions:
                del self.positions[position_key]
        else:
            self.current_exposure += size
            self.positions[position_key] = {
                "strategy": strategy_name,
                "market": market_id,
                "side": side,
                "size": size,
                "entry_price": price,
                "entry_time": datetime.now()
            }

        # Update peak capital
        current_capital = self.get_current_capital()
        if current_capital > self.peak_capital:
            self.peak_capital = current_capital

        logger.info(
            f"Trade recorded: {strategy_name} {side} ${size:.2f} @ {price:.4f}. "
            f"Daily P&L: ${self.daily_pnl:.2f}, Exposure: ${self.current_exposure:.2f}"
        )

    def get_current_capital(self) -> float:
        """Calculate current capital based on positions and P&L"""
        # Base capital + realized P&L
        base_capital = 1500.0  # 15 strategies × $100
        return base_capital + self.daily_pnl

    def get_risk_report(self) -> Dict:
        """Generate current risk status report"""
        current_capital = self.get_current_capital()
        
        drawdown = 0.0
        if self.peak_capital > 0:
            drawdown = (self.peak_capital - current_capital) / self.peak_capital

        return {
            "daily_pnl": round(self.daily_pnl, 2),
            "current_exposure": round(self.current_exposure, 2),
            "exposure_limit": self.limits.max_total_exposure,
            "exposure_pct": round(self.current_exposure / self.limits.max_total_exposure * 100, 1),
            "trades_today": self.trades_today,
            "current_drawdown_pct": round(drawdown * 100, 2),
            "max_drawdown_pct": self.limits.max_drawdown_pct * 100,
            "current_capital": round(current_capital, 2),
            "peak_capital": round(self.peak_capital, 2),
            "open_positions": len(self.positions),
            "limits": {
                "max_order_size": self.limits.max_order_size,
                "max_position_size": self.limits.max_position_size,
                "max_daily_loss": self.limits.max_daily_loss,
                "max_trades_per_hour": self.limits.max_trades_per_hour
            }
        }

    def check_strategy_limits(
        self,
        strategy_name: str,
        current_capital: float
    ) -> tuple[bool, str]:
        """Check if strategy can continue trading"""
        # Check if strategy has hit its capital limit
        if current_capital <= 0:
            return False, f"Strategy {strategy_name} bankrupt (capital: ${current_capital:.2f})"

        return True, "OK"
