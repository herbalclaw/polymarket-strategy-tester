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
        self.closed_trades: List[Dict] = []  # Track closed trades for GitHub push
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
    
    def record_trade(self, strategy_name: str, signal, entry_price: float, 
                     exit_price: float, pnl_pct: float, entry_reason: str,
                     exit_reason: str, duration_minutes: float):
        """Record a completed trade and immediately update Excel."""
        with self.lock:
            # Handle both Signal objects and dicts
            signal_type = getattr(signal, 'signal', None) or signal.get('type', 'UNKNOWN')
            confidence = getattr(signal, 'confidence', 0) or signal.get('confidence', 0)
            
            trade_record = {
                'Trade #': len(self.closed_trades) + 1,
                'Date': datetime.now().strftime('%Y-%m-%d'),
                'Time': datetime.now().strftime('%H:%M:%S'),
                'Strategy': strategy_name,
                'Side': signal_type.upper() if isinstance(signal_type, str) else str(signal_type).upper(),
                'Entry Price': round(entry_price, 6),
                'Exit Price': round(exit_price, 6),
                'P&L %': round(pnl_pct, 4),
                'P&L $': round(pnl_pct * 10, 2),  # $10 position size
                'Confidence': round(confidence, 4),
                'Entry Reason': entry_reason[:100] if entry_reason else '',
                'Exit Reason': exit_reason[:100] if exit_reason else '',
                'Duration (min)': round(duration_minutes, 2),
            }
            
            self.closed_trades.append(trade_record)
            
            # Update strategy-specific data
            if strategy_name not in self.trades_data:
                self.trades_data[strategy_name] = []
            self.trades_data[strategy_name].append(trade_record)
            
            # Update performance metrics
            self._update_performance_metrics(strategy_name)
            
            # Immediately write to Excel
            self._write_excel()
            
            return trade_record
    
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
                # Summary sheet
                self._write_summary_sheet(writer)
                
                # Individual strategy sheets
                for strategy, trades in self.trades_data.items():
                    self._write_strategy_sheet(writer, strategy, trades)
                
                # All trades sheet
                self._write_all_trades_sheet(writer)
                
                # Comparison sheet
                self._write_comparison_sheet(writer)
                
        except Exception as e:
            print(f"Error writing Excel: {e}")
    
    def add_trade(self, strategy: str, trade: Dict):
        """Legacy method - use record_trade for new trades."""
        # Convert to new format
        self.record_trade(
            strategy_name=strategy,
            signal=trade,
            entry_price=trade.get('entry_price', 0),
            exit_price=trade.get('exit_price', 0),
            pnl_pct=trade.get('pnl', 0),
            entry_reason=trade.get('reason', ''),
            exit_reason=trade.get('exit_reason', ''),
            duration_minutes=trade.get('duration_min', 0)
        )
    
    def update_performance(self, strategy: str, metrics: Dict):
        """Update performance metrics."""
        self.performance_data[strategy] = metrics
        self._write_excel()
    
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
        """Add a trade to the report."""
        if strategy not in self.trades_data:
            self.trades_data[strategy] = []
        
        # Enrich trade data
        trade_record = {
            'Trade #': len(self.trades_data[strategy]) + 1,
            'Date': datetime.fromtimestamp(trade.get('timestamp', 0)).strftime('%Y-%m-%d'),
            'Time': datetime.fromtimestamp(trade.get('timestamp', 0)).strftime('%H:%M:%S'),
            'Strategy': strategy,
            'Side': trade.get('side', '').upper(),
            'Entry Price': trade.get('entry_price', 0),
            'Exit Price': trade.get('exit_price', 0),
            'P&L %': trade.get('pnl', 0),
            'P&L $': trade.get('pnl', 0) * 5,  # Assuming $5 bet
            'Confidence': trade.get('confidence', 0),
            'Entry Reason': trade.get('reason', ''),
            'Exit Reason': trade.get('exit_reason', ''),
            'Duration (min)': trade.get('duration_min', 0),
        }
        
        self.trades_data[strategy].append(trade_record)
    
    def update_performance(self, strategy: str, metrics: Dict):
        """Update performance metrics."""
        self.performance_data[strategy] = metrics
    
    def generate(self):
        """Generate Excel file with multiple sheets."""
        with pd.ExcelWriter(self.filename, engine='openpyxl') as writer:
            
            # Sheet 1: Summary
            self._write_summary_sheet(writer)
            
            # Sheet 2-6: Individual strategy trades
            for strategy, trades in self.trades_data.items():
                self._write_strategy_sheet(writer, strategy, trades)
            
            # Sheet 7: All Trades Combined
            self._write_all_trades_sheet(writer)
            
            # Sheet 8: Performance Comparison
            self._write_comparison_sheet(writer)
        
        print(f"✅ Excel report generated: {self.filename}")
        return self.filename
    
    def _write_summary_sheet(self, writer):
        """Write summary sheet with current performance."""
        summary_data = []
        
        # Add overall stats
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
        
        # Per-strategy stats
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
        
        # Format
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
        
        # Sheet name limited to 31 chars
        sheet_name = strategy[:31]
        df.to_excel(writer, sheet_name=sheet_name, index=False)
        
        # Formatting
        worksheet = writer.sheets[sheet_name]
        
        # Color code P&L column (index 7)
        green_fill = PatternFill(start_color='C6EFCE', end_color='C6EFCE', fill_type='solid')
        red_fill = PatternFill(start_color='FFC7CE', end_color='FFC7CE', fill_type='solid')
        
        for row_idx, row in enumerate(worksheet.iter_rows(min_row=2, max_row=worksheet.max_row), start=2):
            if len(row) > 7:
                pnl_cell = row[7]  # P&L % column
                if pnl_cell.value is not None:
                    try:
                        val = float(pnl_cell.value)
                        if val > 0:
                            pnl_cell.fill = green_fill
                        elif val < 0:
                            pnl_cell.fill = red_fill
                    except (ValueError, TypeError):
                        pass
        
        # Auto-adjust column widths
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
            # Sort by date/time
            sorted_trades = sorted(
                self.closed_trades, 
                key=lambda x: x['Date'] + ' ' + x['Time']
            )
            df = pd.DataFrame(sorted_trades)
        else:
            df = pd.DataFrame({'Status': ['No trades yet']})
        
        df.to_excel(writer, sheet_name='All Trades', index=False)
        
        # Format
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
        
        # Auto-adjust
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
        
        # Auto-adjust
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
