#!/usr/bin/env python3
"""
GitHub Auto-Push Module
Automatically pushes Excel updates to GitHub on every trade close.
"""

import subprocess
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger('github_pusher')


class GitHubAutoPusher:
    """Automatically pushes trading updates to GitHub."""
    
    def __init__(self, repo_path: str = ".", excel_filename: str = "live_trading_results.xlsx"):
        self.repo_path = Path(repo_path)
        self.excel_filename = excel_filename
        self.last_push_trade_count = 0
        self.push_count = 0
        
    def _run_git_command(self, args: list, check: bool = True) -> tuple:
        """Run a git command and return (success, output)."""
        try:
            result = subprocess.run(
                ['git'] + args,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=30
            )
            if check and result.returncode != 0:
                logger.error(f"Git command failed: {result.stderr}")
                return False, result.stderr
            return True, result.stdout
        except subprocess.TimeoutExpired:
            logger.error("Git command timed out")
            return False, "Timeout"
        except Exception as e:
            logger.error(f"Git command error: {e}")
            return False, str(e)
    
    def should_push(self, current_trade_count: int) -> bool:
        """Check if we should push (new trades since last push)."""
        return current_trade_count > self.last_push_trade_count
    
    def push_update(self, trade_summary: Optional[str] = None) -> bool:
        """Push Excel update to GitHub."""
        try:
            self.push_count += 1
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # Configure git if needed
            self._ensure_git_config()
            
            # Add the Excel file
            excel_path = self.repo_path / self.excel_filename
            if not excel_path.exists():
                logger.warning(f"Excel file not found: {excel_path}")
                return False
            
            # Stage the file
            success, _ = self._run_git_command(['add', self.excel_filename], check=False)
            if not success:
                logger.error("Failed to stage Excel file")
                return False
            
            # Check if there are changes
            success, diff_output = self._run_git_command(['diff', '--cached', '--quiet'], check=False)
            if success:
                # No changes to commit
                logger.debug("No changes to push")
                return True
            
            # Create commit message
            if trade_summary:
                message = f"Trade #{self.push_count} closed at {timestamp} - {trade_summary}"
            else:
                message = f"Update trading results - {timestamp}"
            
            # Commit
            success, _ = self._run_git_command(['commit', '-m', message], check=False)
            if not success:
                logger.error("Failed to commit")
                return False
            
            # Push
            success, output = self._run_git_command(['push', 'origin', 'master'], check=False)
            if not success:
                logger.error(f"Failed to push: {output}")
                return False
            
            logger.info(f"✅ Pushed to GitHub: {message}")
            return True
            
        except Exception as e:
            logger.error(f"Push error: {e}")
            return False
    
    def _ensure_git_config(self):
        """Ensure git user is configured."""
        # Check if user.email is set
        success, email = self._run_git_command(['config', 'user.email'], check=False)
        if not success or not email.strip():
            self._run_git_command(['config', 'user.email', 'trading-bot@polymarket.local'], check=False)
        
        # Check if user.name is set
        success, name = self._run_git_command(['config', 'user.name'], check=False)
        if not success or not name.strip():
            self._run_git_command(['config', 'user.name', 'Polymarket Trading Bot'], check=False)
    
    def push_on_trade_close(self, trade_count: int, trade_data: dict) -> bool:
        """Push update when a trade closes."""
        if not self.should_push(trade_count):
            return True  # Nothing to push
        
        # Create summary
        pnl = trade_data.get('pnl_pct', 0)
        strategy = trade_data.get('strategy', 'unknown')
        side = trade_data.get('side', 'UNKNOWN')
        
        summary = f"{strategy} {side} {pnl:+.3f}%"
        
        success = self.push_update(summary)
        
        if success:
            self.last_push_trade_count = trade_count
        
        return success
    
    def force_push(self, message: str = "Manual update") -> bool:
        """Force a push regardless of trade count."""
        return self.push_update(message)


# Singleton instance for easy import
_default_pusher = None

def get_pusher(repo_path: str = ".") -> GitHubAutoPusher:
    """Get or create the default pusher instance."""
    global _default_pusher
    if _default_pusher is None:
        _default_pusher = GitHubAutoPusher(repo_path=repo_path)
    return _default_pusher


def push_trade_update(trade_count: int, trade_data: dict, repo_path: str = ".") -> bool:
    """Convenience function to push a trade update."""
    pusher = get_pusher(repo_path)
    return pusher.push_on_trade_close(trade_count, trade_data)
