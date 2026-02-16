import pandas as pd
from datetime import datetime
from typing import Dict, List
import os


class ExcelReporter:
    """Generate Excel reports for strategy testing."""
    
    def __init__(self, filename: str = None):
        if filename is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"strategy_results_{timestamp}.xlsx"
        
        self.filename = filename
        self.trades_data: Dict[str, List[Dict]] = {}
        self.performance_data: Dict[str, Dict] = {}
        
    def add_trade(self, strategy: str, trade: Dict):
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
        """Write summary sheet."""
        summary_data = []
        
        for strategy, metrics in self.performance_data.items():
            summary_data.append({
                'Strategy': strategy,
                'Total Trades': metrics.get('total_trades', 0),
                'Winning Trades': metrics.get('winning_trades', 0),
                'Losing Trades': metrics.get('losing_trades', 0),
                'Win Rate': f"{metrics.get('win_rate', 0):.1%}",
                'Total P&L %': f"{metrics.get('total_pnl', 0):+.3f}%",
                'Avg P&L per Trade': f"{metrics.get('avg_pnl', 0):+.3f}%",
            })
        
        df = pd.DataFrame(summary_data)
        df.to_excel(writer, sheet_name='Summary', index=False)
        
        # Auto-adjust column widths
        worksheet = writer.sheets['Summary']
        for column in worksheet.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 50)
            worksheet.column_dimensions[column_letter].width = adjusted_width
    
    def _write_strategy_sheet(self, writer, strategy: str, trades: List[Dict]):
        """Write individual strategy sheet."""
        if not trades:
            df = pd.DataFrame(columns=['No trades yet'])
        else:
            df = pd.DataFrame(trades)
        
        # Sheet name limited to 31 chars
        sheet_name = strategy[:31]
        df.to_excel(writer, sheet_name=sheet_name, index=False)
        
        # Formatting
        worksheet = writer.sheets[sheet_name]
        
        # Color code P&L
        for idx, row in enumerate(worksheet.iter_rows(min_row=2, max_row=worksheet.max_row), start=2):
            pnl_cell = row[7]  # P&L % column
            if pnl_cell.value:
                try:
                    val = float(str(pnl_cell.value).replace('%', ''))
                    if val > 0:
                        pnl_cell.fill = openpyxl.styles.PatternFill(start_color='C6EFCE', end_color='C6EFCE', fill_type='solid')
                    elif val < 0:
                        pnl_cell.fill = openpyxl.styles.PatternFill(start_color='FFC7CE', end_color='FFC7CE', fill_type='solid')
                except:
                    pass
    
    def _write_all_trades_sheet(self, writer):
        """Write all trades combined."""
        all_trades = []
        for strategy, trades in self.trades_data.items():
            all_trades.extend(trades)
        
        if all_trades:
            # Sort by time
            all_trades.sort(key=lambda x: x['Date'] + ' ' + x['Time'])
            df = pd.DataFrame(all_trades)
        else:
            df = pd.DataFrame(columns=['No trades yet'])
        
        df.to_excel(writer, sheet_name='All Trades', index=False)
    
    def _write_comparison_sheet(self, writer):
        """Write strategy comparison."""
        comparison_data = []
        
        for strategy, metrics in self.performance_data.items():
            comparison_data.append({
                'Strategy': strategy,
                'Sharpe Ratio': metrics.get('sharpe', 0),
                'Max Drawdown %': metrics.get('max_drawdown', 0),
                'Profit Factor': metrics.get('profit_factor', 0),
                'Avg Win %': metrics.get('avg_win', 0),
                'Avg Loss %': metrics.get('avg_loss', 0),
                'Win/Loss Ratio': metrics.get('win_loss_ratio', 0),
            })
        
        df = pd.DataFrame(comparison_data)
        df.to_excel(writer, sheet_name='Comparison', index=False)
