import pandas as pd
import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment
from datetime import datetime
from typing import Dict, List, Optional
import os
import threading


class ExcelReporter:
    """Generate Excel reports for strategy testing - updated live on every trade."""
    
    def __init__(self, filename: str = "live_trading_results.xlsx"):
        self.filename = filename
        self.trades_data: Dict[str, List[Dict]] = {}
        self.performance_data: Dict[str, Dict] = {}
        self.closed_trades: List[Dict] = []
        self.open_trades: List[Dict] = []  # Track open trades
        self.lock = threading.Lock()
        
        # Ensure file exists
        if not os.path.exists(self.filename):
            self._create_empty_file()
    
    def _create_empty_file(self):
        """Create initial Excel file."""
        with pd.ExcelWriter(self.filename, engine='openpyxl') as writer:
            pd.DataFrame({'Status': ['Trading started - waiting for trades...']}).to_excel(
                writer, sheet_name='Summary', index=False
            )
    
    def record_trade_open(self, strategy_name: str, signal, entry_price: float,
                          entry_reason: str) -> Dict:
        """Record a trade open and immediately update Excel."""
        with self.lock:
            signal_type = getattr(signal, 'signal', None) or signal.get('type', 'UNKNOWN')
            confidence = getattr(signal, 'confidence', 0) or signal.get('confidence', 0)
            
            open_record = {
                'Trade #': len(self.closed_trades) + len(self.open_trades) + 1,
                'Date': datetime.now().strftime('%Y-%m-%d'),
                'Time': datetime.now().strftime('%H:%M:%S'),
                'Strategy': strategy_name,
                'Side': signal_type.upper() if isinstance(signal_type, str) else str(signal_type).upper(),
                'Entry Price': round(entry_price, 6),
                'Exit Price': None,
                'Status': 'OPEN',
                'P&L %': 0.0,
                'P&L $': 0.0,
                'Confidence': round(confidence, 4),
                'Entry Reason': entry_reason[:100] if entry_reason else '',
                'Exit Reason': '',
                'Duration (min)': 0.0,
            }
            
            self.open_trades.append(open_record)
            
            if strategy_name not in self.trades_data:
                self.trades_data[strategy_name] = []
            self.trades_data[strategy_name].append(open_record)
            
            self._write_excel()
            
            return open_record
    
    def record_trade_close(self, trade_id: int, exit_price: float, pnl_pct: float,
                          exit_reason: str, duration_minutes: float) -> Dict:
        """Record a trade close and immediately update Excel."""
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
            
            # Create closed trade record
            closed_record = {
                **open_trade,
                'Exit Price': round(exit_price, 6),
                'Status': 'CLOSED',
                'P&L %': round(pnl_pct, 4),
                'P&L $': round(pnl_pct * 10, 2),
                'Exit Reason': exit_reason[:100] if exit_reason else '',
                'Duration (min)': round(duration_minutes, 2),
            }
            
            # Remove from open trades
            self.open_trades.pop(open_idx)
            
            # Add to closed trades
            self.closed_trades.append(closed_record)
            
            # Update in strategy data
            strategy_name = closed_record['Strategy']
            if strategy_name in self.trades_data:
                # Replace the open trade with closed trade
                for idx, trade in enumerate(self.trades_data[strategy_name]):
                    if trade['Trade #'] == trade_id:
                        self.trades_data[strategy_name][idx] = closed_record
                        break
            
            self._update_performance_metrics(strategy_name)
            self._write_excel()
            
            return closed_record

    def record_trade(self, strategy_name: str, signal, entry_price: float, 
                     exit_price: float, pnl_pct: float, entry_reason: str,
                     exit_reason: str, duration_minutes: float):
        """Legacy method - records a completed trade in one step."""
        # Record as open then immediately close
        signal_copy = type('obj', (object,), {'signal': getattr(signal, 'signal', 'UNKNOWN'), 
                                              'confidence': getattr(signal, 'confidence', 0)})()
        open_record = self.record_trade_open(strategy_name, signal_copy, entry_price, entry_reason)
        return self.record_trade_close(open_record['Trade #'], exit_price, pnl_pct, exit_reason, duration_minutes)
    
    def _update_performance_metrics(self, strategy: str):
        """Calculate performance metrics for a strategy."""
        trades = self.trades_data.get(strategy, [])
        
        if not trades:
            return
        
        pnls = [t['P&L %'] for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        
        total_pnl = sum(pnls)
        win_count = len(wins)
        loss_count = len(losses)
        total = len(pnls)
        
        self.performance_data[strategy] = {
            'total_trades': total,
            'winning_trades': win_count,
            'losing_trades': loss_count,
            'win_rate': win_count / total if total > 0 else 0,
            'total_pnl': total_pnl,
            'avg_pnl': total_pnl / total if total > 0 else 0,
            'avg_win': sum(wins) / len(wins) if wins else 0,
            'avg_loss': sum(losses) / len(losses) if losses else 0,
            'max_drawdown': min(pnls) if pnls else 0,
            'profit_factor': abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float('inf'),
            'win_loss_ratio': abs((sum(wins) / len(wins)) / (sum(losses) / len(losses))) if wins and losses else 0,
        }
    
    def _write_excel(self):
        """Write current state to Excel file."""
        try:
            with pd.ExcelWriter(self.filename, engine='openpyxl') as writer:
                self._write_summary_sheet(writer)
                
                for strategy, trades in self.trades_data.items():
                    self._write_strategy_sheet(writer, strategy, trades)
                
                self._write_all_trades_sheet(writer)
                self._write_comparison_sheet(writer)
                
        except Exception as e:
            print(f"Error writing Excel: {e}")
    
    def generate(self):
        """Force regenerate Excel file."""
        self._write_excel()
        return self.filename
    
    def get_last_trade(self) -> Optional[Dict]:
        """Get the most recent closed trade."""
        return self.closed_trades[-1] if self.closed_trades else None
    
    def get_closed_trades_count(self) -> int:
        """Get total number of closed trades."""
        return len(self.closed_trades)
    
    def _write_summary_sheet(self, writer):
        """Write summary sheet with current performance."""
        summary_data = []
        
        total_trades = len(self.closed_trades)
        if total_trades > 0:
            all_pnls = [t['P&L %'] for t in self.closed_trades]
            total_pnl = sum(all_pnls)
            wins = [p for p in all_pnls if p > 0]
            
            summary_data.append({
                'Metric': 'OVERALL',
                'Strategy': 'ALL COMBINED',
                'Total Trades': total_trades,
                'Win Rate': f"{len(wins)/total_trades:.1%}" if total_trades > 0 else "0%",
                'Total P&L %': f"{total_pnl:+.4f}%",
                'Avg Trade': f"{total_pnl/total_trades:+.4f}%" if total_trades > 0 else "0%",
            })
        
        for strategy, metrics in self.performance_data.items():
            summary_data.append({
                'Metric': 'STRATEGY',
                'Strategy': strategy,
                'Total Trades': metrics.get('total_trades', 0),
                'Win Rate': f"{metrics.get('win_rate', 0):.1%}",
                'Total P&L %': f"{metrics.get('total_pnl', 0):+.4f}%",
                'Avg Trade': f"{metrics.get('avg_pnl', 0):+.4f}%",
            })
        
        df = pd.DataFrame(summary_data)
        df.to_excel(writer, sheet_name='Summary', index=False)
        
        worksheet = writer.sheets['Summary']
        for column in worksheet.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if cell.value and len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            worksheet.column_dimensions[column_letter].width = min(max_length + 2, 50)
    
    def _write_strategy_sheet(self, writer, strategy: str, trades: List[Dict]):
        """Write individual strategy sheet with formatting."""
        if not trades:
            df = pd.DataFrame({'Status': ['No trades for this strategy yet']})
        else:
            df = pd.DataFrame(trades)
        
        sheet_name = strategy[:31]
        df.to_excel(writer, sheet_name=sheet_name, index=False)
        
        worksheet = writer.sheets[sheet_name]
        
        green_fill = PatternFill(start_color='C6EFCE', end_color='C6EFCE', fill_type='solid')
        red_fill = PatternFill(start_color='FFC7CE', end_color='FFC7CE', fill_type='solid')
        
        for row_idx, row in enumerate(worksheet.iter_rows(min_row=2, max_row=worksheet.max_row), start=2):
            if len(row) > 7:
                pnl_cell = row[7]
                if pnl_cell.value is not None:
                    try:
                        val = float(pnl_cell.value)
                        if val > 0:
                            pnl_cell.fill = green_fill
                        elif val < 0:
                            pnl_cell.fill = red_fill
                    except (ValueError, TypeError):
                        pass
        
        for column in worksheet.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if cell.value and len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            worksheet.column_dimensions[column_letter].width = min(max_length + 2, 50)
    
    def _write_all_trades_sheet(self, writer):
        """Write all trades combined, sorted by time."""
        if self.closed_trades:
            sorted_trades = sorted(self.closed_trades, key=lambda x: x['Date'] + ' ' + x['Time'])
            df = pd.DataFrame(sorted_trades)
        else:
            df = pd.DataFrame({'Status': ['No trades yet']})
        
        df.to_excel(writer, sheet_name='All Trades', index=False)
        
        worksheet = writer.sheets['All Trades']
        green_fill = PatternFill(start_color='C6EFCE', end_color='C6EFCE', fill_type='solid')
        red_fill = PatternFill(start_color='FFC7CE', end_color='FFC7CE', fill_type='solid')
        
        for row in worksheet.iter_rows(min_row=2, max_row=worksheet.max_row):
            if len(row) > 7:
                pnl_cell = row[7]
                if pnl_cell.value is not None:
                    try:
                        val = float(pnl_cell.value)
                        if val > 0:
                            pnl_cell.fill = green_fill
                        elif val < 0:
                            pnl_cell.fill = red_fill
                    except:
                        pass
        
        for column in worksheet.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if cell.value and len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            worksheet.column_dimensions[column_letter].width = min(max_length + 2, 50)
    
    def _write_comparison_sheet(self, writer):
        """Write strategy comparison metrics."""
        comparison_data = []
        
        for strategy, metrics in self.performance_data.items():
            comparison_data.append({
                'Strategy': strategy,
                'Total Trades': metrics.get('total_trades', 0),
                'Win Rate': f"{metrics.get('win_rate', 0):.1%}",
                'Profit Factor': f"{metrics.get('profit_factor', 0):.2f}",
                'Avg Win %': f"{metrics.get('avg_win', 0):+.4f}%",
                'Avg Loss %': f"{metrics.get('avg_loss', 0):+.4f}%",
                'Win/Loss Ratio': f"{metrics.get('win_loss_ratio', 0):.2f}",
                'Max Drawdown': f"{metrics.get('max_drawdown', 0):+.4f}%",
            })
        
        if not comparison_data:
            df = pd.DataFrame({'Status': ['No data yet']})
        else:
            df = pd.DataFrame(comparison_data)
        
        df.to_excel(writer, sheet_name='Comparison', index=False)
        
        worksheet = writer.sheets['Comparison']
        for column in worksheet.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if cell.value and len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            worksheet.column_dimensions[column_letter].width = min(max_length + 2, 50)
