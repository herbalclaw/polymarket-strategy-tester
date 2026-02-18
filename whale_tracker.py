"""
Whale tracking module for Polymarket.
Monitors large positions and profitable wallets for copy-trading signals.
"""
import asyncio
import json
import logging
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class WhalePosition:
    """Represents a whale's position in a market"""
    wallet_address: str
    market_id: str
    token_id: str
    side: str  # "YES" or "NO"
    size: float
    avg_entry_price: float
    unrealized_pnl: float
    last_updated: datetime


@dataclass
class WhaleProfile:
    """Profile of a whale trader"""
    wallet_address: str
    total_volume_30d: float
    win_rate: float
    total_pnl_30d: float
    avg_trade_size: float
    markets_traded: int
    last_trade_time: Optional[datetime]
    risk_score: float  # 0-100, lower is better


class WhaleTracker:
    """
    Tracks whale wallets and their trading activity.
    
    Features:
    - Monitor top position holders
    - Track profitable wallets
    - Generate copy-trade signals
    - Risk scoring for whales
    """

    GAMMA_API_URL = "https://gamma-api.polymarket.com"
    
    def __init__(self):
        self.known_whales: Dict[str, WhaleProfile] = {}
        self.positions: Dict[str, List[WhalePosition]] = {}  # market_id -> positions
        self.profitable_wallets: set = set()
        self.callbacks: List[Callable] = []
        self.session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        return self.session

    async def fetch_market_holders(
        self,
        market_id: str,
        limit: int = 20
    ) -> List[Dict]:
        """
        Fetch top position holders for a market.
        
        Note: This requires access to position data which may not be
        publicly available for all markets.
        """
        try:
            session = await self._get_session()
            
            # Try to fetch from Gamma API
            url = f"{self.GAMMA_API_URL}/markets/{market_id}/positions"
            params = {"limit": limit, "order_by": "size", "order_direction": "desc"}
            
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("positions", [])
                else:
                    logger.warning(f"Failed to fetch holders: {response.status}")
                    return []
                    
        except Exception as e:
            logger.error(f"Error fetching market holders: {e}")
            return []

    async def analyze_whale(
        self,
        wallet_address: str,
        days: int = 30
    ) -> Optional[WhaleProfile]:
        """
        Analyze a wallet's trading history and create a profile.
        
        This aggregates data from multiple sources to determine:
        - Win rate
        - Total P&L
        - Average trade size
        - Risk score
        """
        try:
            session = await self._get_session()
            
            # Fetch trade history
            url = f"{self.GAMMA_API_URL}/address/{wallet_address}/trades"
            params = {"start_date": (datetime.now() - timedelta(days=days)).isoformat()}
            
            async with session.get(url, params=params) as response:
                if response.status != 200:
                    return None
                    
                data = await response.json()
                trades = data.get("trades", [])
                
                if not trades:
                    return None

                # Calculate metrics
                total_volume = sum(t.get("size", 0) * t.get("price", 0) for t in trades)
                winning_trades = sum(1 for t in trades if t.get("pnl", 0) > 0)
                total_pnl = sum(t.get("pnl", 0) for t in trades)
                avg_size = total_volume / len(trades) if trades else 0
                markets = len(set(t.get("market_id") for t in trades))
                
                # Calculate risk score (0-100)
                # Factors: drawdown, position concentration, trade frequency
                risk_score = 50  # Base score
                
                # Lower score for consistent winners
                win_rate = winning_trades / len(trades) if trades else 0
                if win_rate > 0.6:
                    risk_score -= 20
                elif win_rate < 0.4:
                    risk_score += 20
                
                # Adjust for large average size (higher risk)
                if avg_size > 10000:
                    risk_score += 10
                
                # Adjust for diversification
                if markets > 10:
                    risk_score -= 10
                
                risk_score = max(0, min(100, risk_score))
                
                profile = WhaleProfile(
                    wallet_address=wallet_address,
                    total_volume_30d=total_volume,
                    win_rate=win_rate,
                    total_pnl_30d=total_pnl,
                    avg_trade_size=avg_size,
                    markets_traded=markets,
                    last_trade_time=datetime.fromisoformat(trades[0]["timestamp"]) if trades else None,
                    risk_score=risk_score
                )
                
                self.known_whales[wallet_address] = profile
                
                # Mark as profitable if good win rate and positive P&L
                if win_rate > 0.55 and total_pnl > 0:
                    self.profitable_wallets.add(wallet_address)
                
                return profile
                
        except Exception as e:
            logger.error(f"Error analyzing whale {wallet_address}: {e}")
            return None

    async def scan_for_whales(
        self,
        market_id: str,
        min_position_size: float = 5000
    ) -> List[WhaleProfile]:
        """
        Scan a market for whale positions and analyze them.
        
        Args:
            market_id: Market to scan
            min_position_size: Minimum position size in USD to qualify as whale
            
        Returns:
            List of whale profiles
        """
        logger.info(f"Scanning market {market_id} for whales...")
        
        holders = await self.fetch_market_holders(market_id, limit=50)
        whales = []
        
        for holder in holders:
            position_size = holder.get("size", 0) * holder.get("avg_price", 0)
            
            if position_size >= min_position_size:
                wallet = holder.get("wallet_address")
                
                # Analyze whale if not already known
                if wallet not in self.known_whales:
                    profile = await self.analyze_whale(wallet)
                    if profile:
                        whales.append(profile)
                else:
                    whales.append(self.known_whales[wallet])
        
        logger.info(f"Found {len(whales)} whales in market {market_id}")
        return whales

    def get_copy_trade_signals(
        self,
        min_win_rate: float = 0.55,
        min_pnl: float = 1000,
        max_risk_score: float = 60
    ) -> List[Dict]:
        """
        Generate copy-trade signals from profitable whales.
        
        Returns list of signals with:
        - wallet_address
        - confidence_score (based on win rate and P&L)
        - recommended_position_size
        - risk_level
        """
        signals = []
        
        for wallet in self.profitable_whales:
            profile = self.known_whales.get(wallet)
            if not profile:
                continue
            
            # Filter by criteria
            if profile.win_rate < min_win_rate:
                continue
            if profile.total_pnl_30d < min_pnl:
                continue
            if profile.risk_score > max_risk_score:
                continue
            
            # Calculate confidence score (0-100)
            confidence = (
                profile.win_rate * 50 +  # Win rate contributes up to 50
                min(profile.total_pnl_30d / 10000, 30) +  # P&L contributes up to 30
                (100 - profile.risk_score) * 0.2  # Low risk adds up to 20
            )
            
            signal = {
                "wallet_address": wallet,
                "confidence_score": round(confidence, 2),
                "win_rate": round(profile.win_rate * 100, 2),
                "total_pnl_30d": round(profile.total_pnl_30d, 2),
                "avg_trade_size": round(profile.avg_trade_size, 2),
                "risk_score": profile.risk_score,
                "recommended_size": round(profile.avg_trade_size * 0.1, 2),  # 10% of whale size
                "last_trade": profile.last_trade_time.isoformat() if profile.last_trade_time else None
            }
            
            signals.append(signal)
        
        # Sort by confidence
        signals.sort(key=lambda x: x["confidence_score"], reverse=True)
        return signals

    def register_callback(self, callback: Callable) -> None:
        """Register callback for whale activity alerts"""
        self.callbacks.append(callback)

    async def notify_whale_activity(self, activity: Dict) -> None:
        """Notify all registered callbacks of whale activity"""
        for callback in self.callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(activity)
                else:
                    callback(activity)
            except Exception as e:
                logger.error(f"Error in whale callback: {e}")

    async def close(self) -> None:
        """Close the aiohttp session"""
        if self.session and not self.session.closed:
            await self.session.close()


class WhaleCopyStrategy:
    """
    Trading strategy that copies whale trades.
    
    Configurable parameters:
    - min_whale_confidence: Minimum confidence score to copy
    - position_size_pct: Percentage of whale's position to copy
    - max_positions: Maximum concurrent positions
    - stop_loss_pct: Stop loss percentage
    """

    def __init__(
        self,
        whale_tracker: WhaleTracker,
        min_confidence: float = 70.0,
        position_size_pct: float = 0.1,
        max_positions: int = 5,
        stop_loss_pct: float = 0.15
    ):
        self.tracker = whale_tracker
        self.min_confidence = min_confidence
        self.position_size_pct = position_size_pct
        self.max_positions = max_positions
        self.stop_loss_pct = stop_loss_pct
        self.active_positions: Dict[str, Dict] = {}

    async def generate_signals(self) -> List[Dict]:
        """Generate trading signals based on whale activity"""
        signals = self.tracker.get_copy_trade_signals(
            min_win_rate=0.55,
            min_pnl=1000,
            max_risk_score=60
        )
        
        valid_signals = [
            s for s in signals
            if s["confidence_score"] >= self.min_confidence
            and s["wallet_address"] not in self.active_positions
        ]
        
        # Limit to max_positions
        return valid_signals[:self.max_positions]

    def calculate_position_size(self, whale_avg_size: float) -> float:
        """Calculate position size based on whale's average"""
        return min(
            whale_avg_size * self.position_size_pct,
            100  # Max $100 per trade
        )
