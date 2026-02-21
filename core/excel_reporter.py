"""
Excel Reporter with Proper Capital Tracking and Strategy Management
"""

import pandas as pd
import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment
from datetime import datetime
from typing import Dict, List, Optional
import os
import threading


class ExcelReporter:
    """Generate Excel reports with capital tracking and strategy failure detection."""
    
    def __init__(self, filename: str = "live_trading_results.xlsx", 
                 initial_capital: float = 100.0,
                 trade_size: float = 5.0):
        self.filename = filename
        self.initial_capital = initial_capital
        self.trade_size = trade_size
        self.current_capital = initial_capital
        
        # Track all strategies and their capital
        self.strategy_capital: Dict[str, float] = {}
        self.strategy_active: Dict[str, bool] = {}
        self.strategy_trades: Dict[str, List[Dict]] = {}
        
        self.closed_trades: List[Dict] = []
        self.open_trades: List[Dict] = []
        self.lock = threading.Lock()
        
        # Ensure file exists
        if not os.path.exists(self.filename):
            self._create_empty_file()
        else:
            # Load existing trades from Excel
            self._load_existing_trades()
    
    def register_strategies(self, strategy_names: List[str]):
        """Register all strategies with initial capital."""
        with self.lock:
            for name in strategy_names:
                if name not in self.strategy_capital:
                    self.strategy_capital[name] = self.initial_capital
                    self.strategy_active[name] = True
                    self.strategy_trades[name] = []
    
    def _create_empty_file(self):
        """Create initial Excel file with proper structure."""
        with pd.ExcelWriter(self.filename, engine='openpyxl') as writer:
            # Summary sheet
            summary_data = {
                'Metric': ['Initial Capital', 'Current Capital', 'Total P&L $', 'Total P&L %', 
                          'Total Trades', 'Winning Trades', 'Losing Trades', 'Win Rate %'],
                'Value': [self.initial_capital, self.initial_capital, 0, 0, 0, 0, 0, 0]
            }
            pd.DataFrame(summary_data).to_excel(writer, sheet_name='Summary', index=False)
            
            # Strategy Status sheet
            status_data = {
                'Strategy': [],
                'Status': [],
                'Capital': [],
                'Trades': [],
                'P&L $': [],
                'P&L %': []
            }
            pd.DataFrame(status_data).to_excel(writer, sheet_name='Strategy Status', index=False)
            
            # All Trades sheet
            trades_data = {
                'Trade #': [],
                'Date': [],
                'Time': [],
                'Strategy': [],
                'Side': [],
                'Entry Price': [],
                'Exit Price': [],
                'Status': [],
                'P&L %': [],
                'P&L $': [],
                'Capital After': [],
                'Confidence': [],
                'Entry Reason': [],
                'Exit Reason': [],
                'Duration (min)': []
            }
            pd.DataFrame(trades_data).to_excel(writer, sheet_name='All Trades', index=False)
    
    def _load_existing_trades(self):
        """Load existing trades from Excel file on startup."""
        try:
            import zipfile
            import xml.etree.ElementTree as ET
            
            with zipfile.ZipFile(self.filename, 'r') as z:
                with z.open('xl/worksheets/sheet3.xml') as f:
                    sheet_root = ET.fromstring(f.read())
                    NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
                    
                    for i, row in enumerate(sheet_root.iter(f'{NS}row')):
                        if i == 0:  # Skip header
                            continue
                        
                        cells = list(row.iter(f'{NS}c'))
                        if len(cells) < 10:
                            continue
                        
                        def get_value(cell):
                            v = cell.find(f'{NS}v')
                            if v is not None and v.text:
                                return v.text
                            is_elem = cell.find(f'{NS}is/{NS}t')
                            if is_elem is not None and is_elem.text:
                                return is_elem.text
                            return ''
                        
                        trade_id = get_value(cells[0])
                        if not trade_id or not trade_id.isdigit():
                            continue
                        
                        status = get_value(cells[7]) if len(cells) > 7 else 'OPEN'
                        
                        trade_record = {
                            'Trade #': int(trade_id),
                            'Date': get_value(cells[1]),
                            'Time': get_value(cells[2]),
                            'Strategy': get_value(cells[3]),
                            'Side': get_value(cells[4]),
                            'Entry Price': float(get_value(cells[5]) or 0),
                            'Exit Price': float(get_value(cells[6]) or 0),
                            'Status': status,
                            'P&L %': float(get_value(cells[8]) or 0),
                            'P&L $': float(get_value(cells[9]) or 0),
                        }
                        
                        if status == 'CLOSED':
                            self.closed_trades.append(trade_record)
                        else:
                            self.open_trades.append(trade_record)
                        
                        # Also populate strategy_trades for consistency
                        strategy_name = trade_record['Strategy']
                        if strategy_name:
                            if strategy_name not in self.strategy_trades:
                                self.strategy_trades[strategy_name] = []
                            self.strategy_trades[strategy_name].append(trade_record)
                            
                            # Also populate strategy_capital and strategy_active
                            if strategy_name not in self.strategy_capital:
                                self.strategy_capital[strategy_name] = self.initial_capital
                                self.strategy_active[strategy_name] = True
                            
            # Calculate final capital for each strategy from closed trades
            for strategy_name, trades in self.strategy_trades.items():
                total_pnl = sum(t.get('P&L $', 0) for t in trades if t.get('Status') == 'CLOSED')
                self.strategy_capital[strategy_name] = self.initial_capital + total_pnl
                # Mark as bankrupt if capital <= 0
                if self.strategy_capital[strategy_name] <= 0:
                    self.strategy_active[strategy_name] = False
                            
            print(f"Loaded {len(self.closed_trades)} closed trades and {len(self.open_trades)} open trades from Excel")
            print(f"Populated strategy_trades for {len(self.strategy_trades)} strategies")
            print(f"Populated strategy_capital for {len(self.strategy_capital)} strategies")
        except Exception as e:
            print(f"Warning: Could not load existing trades: {e}")
    
    def record_trade_open(self, strategy_name: str, signal, entry_price: float,
                          entry_reason: str) -> Optional[Dict]:
        """Record a trade open."""
        with self.lock:
            # Check if strategy is active (not bankrupt)
            if not self.strategy_active.get(strategy_name, True):
                return None  # Don't trade if bankrupt
            
            signal_type = getattr(signal, 'signal', None) or signal.get('type', 'UNKNOWN')
            confidence = getattr(signal, 'confidence', 0) or signal.get('confidence', 0)
            
            trade_num = len(self.closed_trades) + len(self.open_trades) + 1
            
            open_record = {
                'Trade #': trade_num,
                'Date': datetime.now().strftime('%Y-%m-%d'),
                'Time': datetime.now().strftime('%H:%M:%S'),
                'Strategy': strategy_name,
                'Side': signal_type.upper() if isinstance(signal_type, str) else str(signal_type).upper(),
                'Entry Price': round(entry_price, 6),
                'Exit Price': None,
                'Status': 'OPEN',
                'P&L %': 0.0,
                'P&L $': 0.0,
                'Capital After': self.strategy_capital.get(strategy_name, self.initial_capital),
                'Entry Slippage (bps)': 0,
                'Exit Slippage (bps)': 0,
                'Confidence': round(confidence, 4),
                'Entry Reason': entry_reason[:100] if entry_reason else '',
                'Exit Reason': '',
                'Duration (min)': 0.0,
            }
            
            self.open_trades.append(open_record)
            
            if strategy_name not in self.strategy_trades:
                self.strategy_trades[strategy_name] = []
            self.strategy_trades[strategy_name].append(open_record)
            
            self._write_excel()
            
            return open_record
    
    def record_trade_close(self, trade_id: int, exit_price: float, pnl_pct: float,
                          exit_reason: str, duration_minutes: float,
                          pnl_amount: Optional[float] = None) -> Optional[Dict]:
        """Record a trade close and update capital."""
        with self.lock:
            # Find the open trade
            open_trade = None
            open_idx = None
            for idx, trade in enumerate(self.open_trades):
                if trade['Trade #'] == trade_id:
                    open_trade = trade
                    open_idx = idx
                    break
            
            if open_trade is None:
                return None
            
            strategy_name = open_trade['Strategy']
            entry_price = open_trade['Entry Price']
            
            # Calculate P&L in dollars
            # If pnl_amount provided, use it (for binary markets)
            # Otherwise calculate from percentage
            if pnl_amount is not None:
                pnl_dollars = pnl_amount  # Bot now returns dollar PnL directly
            else:
                pnl_dollars = (pnl_pct / 100) * self.trade_size
            
            # Update strategy capital
            old_capital = self.strategy_capital.get(strategy_name, self.initial_capital)
            new_capital = old_capital + pnl_dollars
            self.strategy_capital[strategy_name] = new_capital
            
            # Check for bankruptcy (capital <= 0)
            if new_capital <= 0:
                self.strategy_active[strategy_name] = False
            
            # Create closed trade record
            closed_record = {
                **open_trade,
                'Exit Price': round(exit_price, 6),
                'Status': 'CLOSED',
                'P&L %': round(pnl_pct, 4),
                'P&L $': round(pnl_dollars, 2),
                'Capital After': round(new_capital, 2),
                'Exit Reason': exit_reason[:100] if exit_reason else '',
                'Duration (min)': round(duration_minutes, 2),
            }
            
            # Remove from open trades
            self.open_trades.pop(open_idx)
            
            # Add to closed trades
            self.closed_trades.append(closed_record)
            
            # Update in strategy trades
            if strategy_name in self.strategy_trades:
                for idx, trade in enumerate(self.strategy_trades[strategy_name]):
                    if trade['Trade #'] == trade_id:
                        self.strategy_trades[strategy_name][idx] = closed_record
                        break
            
            self._write_excel()
            
            return closed_record
    
    def _write_excel(self):
        """Write all data to Excel file."""
        try:
            with pd.ExcelWriter(self.filename, engine='openpyxl') as writer:
                # Write Summary sheet
                self._write_summary_sheet(writer)
                
                # Write Strategy Status sheet
                self._write_strategy_status_sheet(writer)
                
                # Write All Trades sheet
                self._write_trades_sheet(writer)
                
                # Write per-strategy sheets
                self._write_strategy_sheets(writer)
                
        except Exception as e:
            print(f"Error writing Excel: {e}")
    
    def _write_summary_sheet(self, writer):
        """Write summary statistics."""
        # Calculate totals
        total_trades = len(self.closed_trades)
        winning_trades = sum(1 for t in self.closed_trades if t['P&L $'] > 0)
        losing_trades = sum(1 for t in self.closed_trades if t['P&L $'] < 0)
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        total_pnl_dollars = sum(t['P&L $'] for t in self.closed_trades)
        total_pnl_pct = (total_pnl_dollars / (total_trades * self.trade_size) * 100) if total_trades > 0 else 0
        
        current_total_capital = sum(self.strategy_capital.values())
        
        summary_data = {
            'Metric': ['Initial Capital', 'Current Capital', 'Total P&L $', 'Total P&L %', 
                      'Total Trades', 'Winning Trades', 'Losing Trades', 'Win Rate %',
                      'Trade Size', 'Active Strategies', 'Bankrupt Strategies'],
            'Value': [
                self.initial_capital * len(self.strategy_capital),
                round(current_total_capital, 2),
                round(total_pnl_dollars, 2),
                round(total_pnl_pct, 2),
                total_trades,
                winning_trades,
                losing_trades,
                round(win_rate, 2),
                self.trade_size,
                sum(1 for active in self.strategy_active.values() if active),
                sum(1 for active in self.strategy_active.values() if not active)
            ]
        }
        
        df = pd.DataFrame(summary_data)
        df.to_excel(writer, sheet_name='Summary', index=False)
        
        # Format
        worksheet = writer.sheets['Summary']
        worksheet.column_dimensions['A'].width = 20
        worksheet.column_dimensions['B'].width = 15
    
    def _write_strategy_status_sheet(self, writer):
        """Write strategy status with capital and bankruptcy info."""
        status_data = {
            'Strategy': [],
            'Status': [],
            'Capital': [],
            'Trades': [],
            'P&L $': [],
            'P&L %': [],
            'Win Rate %': []
        }
        
        for strategy_name in sorted(self.strategy_capital.keys()):
            trades = self.strategy_trades.get(strategy_name, [])
            closed = [t for t in trades if t['Status'] == 'CLOSED']
            
            total_pnl = sum(t['P&L $'] for t in closed)
            initial = self.initial_capital
            pnl_pct = ((self.strategy_capital[strategy_name] - initial) / initial * 100) if initial > 0 else 0
            
            wins = sum(1 for t in closed if t['P&L $'] > 0)
            win_rate = (wins / len(closed) * 100) if closed else 0
            
            status = 'ACTIVE' if self.strategy_active.get(strategy_name, True) else 'BANKRUPT'
            
            status_data['Strategy'].append(strategy_name)
            status_data['Status'].append(status)
            status_data['Capital'].append(round(self.strategy_capital[strategy_name], 2))
            status_data['Trades'].append(len(closed))
            status_data['P&L $'].append(round(total_pnl, 2))
            status_data['P&L %'].append(round(pnl_pct, 2))
            status_data['Win Rate %'].append(round(win_rate, 2))
        
        df = pd.DataFrame(status_data)
        df.to_excel(writer, sheet_name='Strategy Status', index=False)
    
    def _write_trades_sheet(self, writer):
        """Write all trades."""
        all_trades = self.closed_trades + self.open_trades
        all_trades.sort(key=lambda x: x['Trade #'])
        
        if all_trades:
            df = pd.DataFrame(all_trades)
            df.to_excel(writer, sheet_name='All Trades', index=False)
        else:
            pd.DataFrame().to_excel(writer, sheet_name='All Trades', index=False)
    
    def _write_strategy_sheets(self, writer):
        """Write individual strategy sheets."""
        for strategy_name, trades in self.strategy_trades.items():
            sheet_name = strategy_name[:31]  # Excel sheet name limit
            
            if trades:
                df = pd.DataFrame(trades)
                df.to_excel(writer, sheet_name=sheet_name, index=False)
    
    def is_strategy_active(self, strategy_name: str) -> bool:
        """Check if a strategy is still active (not bankrupt)."""
        return self.strategy_active.get(strategy_name, True)
    
    def get_strategy_capital(self, strategy_name: str) -> float:
        """Get current capital for a strategy."""
        return self.strategy_capital.get(strategy_name, self.initial_capital)
