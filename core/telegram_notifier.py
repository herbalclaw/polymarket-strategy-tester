#!/usr/bin/env python3
"""
Telegram Notifier for Polymarket Trading
Matches format from trade_terminal Windows bot
"""

import os
import sys
from typing import Dict, Optional
from datetime import datetime

# Ensure UTF-8 encoding for emojis
import locale
locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')

class TelegramNotifier:
    """Send formatted trade notifications to Telegram"""
    
    # Emoji mappings matching trade_terminal format
    EMOJIS = {
        'bot': '🤖',
        'terminal': '📊',
        'long': '🟢',
        'short': '🔴',
        'close': '❌',
        'open': '✅',
        'profit': '🟢',
        'loss': '🔴',
        'time': '🕐',
        'chart': '📈',
        'chart_down': '📉',
        'money': '💰',
        'warning': '⚠️',
        'rocket': '🚀',
        'lock': '🔒',
        'unlock': '🔓',
    }
    
    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        self.bot_token = bot_token or os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = chat_id or os.getenv('TELEGRAM_CHAT_ID')
        
    def _escape_markdown(self, text: str) -> str:
        """Escape special characters for Telegram MarkdownV2"""
        special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        for char in special_chars:
            text = text.replace(char, f'\\{char}')
        return text
    
    def format_trade_message(
        self,
        strategy: str,
        market: str,
        side: str,  # 'LONG' or 'SHORT'
        action: str,  # 'OPEN' or 'CLOSE'
        entry_price: float,
        exit_price: Optional[float] = None,
        size: float = 0.0,
        pnl_pct: Optional[float] = None,
        pnl_amount: Optional[float] = None,
        duration_bars: int = 0,
        duration_time: str = "",
        fees: float = 0.0,
        capital: float = 0.0,
        timestamp: Optional[str] = None
    ) -> str:
        """
        Format trade message matching trade_terminal style:
        🤖 TRADE TERMINAL ❌ LONG closed — EMA RETURN
        Market: HYPE-USD-PERP
        Layers: 1 | Avg Entry: $26.8444
        Exit Price: $26.4950
        Size: 2.26 HYPE
        Held: 28 bars (7h 0m)
        Fees: $0.0138
        Capital: $59.5986
        🕐 21:15 UTC
        PnL: $-0.8035 (-1.32%) 🔴 LOSS
        """
        
        E = self.EMOJIS
        
        # Determine emojis based on action and P&L
        action_emoji = E['close'] if action == 'CLOSE' else E['open']
        side_emoji = E['long'] if side == 'LONG' else E['short']
        
        # Build header
        lines = [
            f"{E['bot']} TRADE TERMINAL {action_emoji} {side} {action.lower()} — {strategy}",
            f"",
            f"Market: {market}",
        ]
        
        # Entry/exit info
        if action == 'OPEN':
            lines.append(f"Entry: ${entry_price:.4f}")
        else:
            lines.append(f"Avg Entry: ${entry_price:.4f}")
            if exit_price:
                lines.append(f"Exit Price: ${exit_price:.4f}")
        
        # Size and duration
        if size > 0:
            lines.append(f"Size: {size:.2f}")
        
        if duration_bars > 0 or duration_time:
            lines.append(f"Held: {duration_bars} bars ({duration_time})")
        
        # Fees and capital
        if fees > 0:
            lines.append(f"Fees: ${fees:.4f}")
        if capital > 0:
            lines.append(f"Capital: ${capital:.4f}")
        
        # Timestamp
        if timestamp:
            lines.append(f"{E['time']} {timestamp}")
        
        # P&L line
        if pnl_amount is not None and pnl_pct is not None:
            pnl_emoji = E['profit'] if pnl_amount >= 0 else E['loss']
            result_text = "PROFIT" if pnl_amount >= 0 else "LOSS"
            lines.append(f"")
            lines.append(f"PnL: ${pnl_amount:+.4f} ({pnl_pct:+.2f}%) {pnl_emoji} {result_text}")
        
        return '\n'.join(lines)
    
    def format_hourly_report(
        self,
        portfolio_pnl: float,
        win_rate: float,
        total_trades: int,
        top_strategies: list,
        progress_pct: int = 55
    ) -> str:
        """Format hourly progress report"""
        
        E = self.EMOJIS
        
        # Progress bar
        filled = int(progress_pct / 5)
        empty = 20 - filled
        progress_bar = '█' * filled + '░' * empty
        
        lines = [
            f"{E['bot']} Hourly Progress Report",
            f"",
            f"Progress: [{progress_bar}] {progress_pct}%",
            f"",
            f"Portfolio P&L: ${portfolio_pnl:+.2f}",
            f"Win Rate: {win_rate:.1f}%",
            f"Total Trades: {total_trades}",
            f"",
            f"{E['chart']} Top Strategies:",
        ]
        
        for i, strat in enumerate(top_strategies[:5], 1):
            pnl = strat.get('pnl', 0)
            emoji = E['profit'] if pnl >= 0 else E['loss']
            lines.append(f"{i}. {strat.get('name', 'Unknown')}: ${pnl:+.2f} {emoji}")
        
        return '\n'.join(lines)
    
    def send_message(self, message: str) -> bool:
        """Send message to Telegram (placeholder - actual sending done by OpenClaw)"""
        # The actual sending is handled by OpenClaw's message tool
        # This class just formats the message properly
        print(message)
        return True


# Standalone function for easy import
def format_trade_notification(**kwargs) -> str:
    """Format a trade notification message"""
    notifier = TelegramNotifier()
    return notifier.format_trade_message(**kwargs)


def format_hourly_notification(**kwargs) -> str:
    """Format an hourly report notification"""
    notifier = TelegramNotifier()
    return notifier.format_hourly_report(**kwargs)


if __name__ == '__main__':
    # Test the formatter
    notifier = TelegramNotifier()
    
    # Test trade close message
    msg = notifier.format_trade_message(
        strategy="EMA RETURN",
        market="HYPE-USD-PERP",
        side="LONG",
        action="CLOSE",
        entry_price=26.8444,
        exit_price=26.4950,
        size=2.26,
        pnl_pct=-1.32,
        pnl_amount=-0.8035,
        duration_bars=28,
        duration_time="7h 0m",
        fees=0.0138,
        capital=59.5986,
        timestamp="21:15 UTC"
    )
    print("=" * 50)
    print("TRADE MESSAGE:")
    print("=" * 50)
    print(msg)
    print()
    
    # Test hourly report
    top_strats = [
        {'name': 'AsymmetricMomentum', 'pnl': 5.82},
        {'name': 'MarketMaking', 'pnl': 1.97},
        {'name': 'RangeBoundMR', 'pnl': 0.37},
    ]
    msg2 = notifier.format_hourly_report(
        portfolio_pnl=-5.74,
        win_rate=28.96,
        total_trades=366,
        top_strategies=top_strats,
        progress_pct=55
    )
    print("=" * 50)
    print("HOURLY REPORT:")
    print("=" * 50)
    print(msg2)
