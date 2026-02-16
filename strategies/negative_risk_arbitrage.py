"""
Negative Risk Arbitrage Strategy

Exploits mathematical inefficiencies in multi-outcome markets.
When sum of all NO prices < 1, buying all NOs guarantees profit.

Reference: Biteye Analysis of Polymarket Arbitrage
"""

from typing import Optional, List, Dict
from core.base_strategy import BaseStrategy, Signal, MarketData


class NegativeRiskArbitrageStrategy(BaseStrategy):
    """
    Multi-outcome arbitrage strategy.
    
    In markets with N mutually exclusive outcomes:
    - Sum of all probabilities should equal 1
    - If Σ(NO_prices) < 1, buy all NO for risk-free profit
    - Profit = 1 - Σ(NO_prices)
    """
    
    name = "negative_risk_arbitrage"
    description = "Multi-outcome arbitrage via NO position aggregation"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        # Minimum profit threshold (%)
        self.min_profit_pct = self.config.get('min_profit_pct', 0.01)  # 1%
        # Maximum number of outcomes to track
        self.max_outcomes = self.config.get('max_outcomes', 10)
        
    def analyze_multi_outcome_market(self, outcomes: List[Dict]) -> Optional[Dict]:
        """
        Analyze a multi-outcome market for arbitrage opportunity.
        
        Args:
            outcomes: List of {'name': str, 'no_price': float}
            
        Returns:
            Arbitrage opportunity details or None
        """
        if len(outcomes) < 2 or len(outcomes) > self.max_outcomes:
            return None
        
        # Sum all NO prices
        total_no_price = sum(o['no_price'] for o in outcomes)
        
        # Check if arbitrage exists
        if total_no_price >= 1.0 - self.min_profit_pct:
            return None
        
        # Calculate profit
        profit = 1.0 - total_no_price
        profit_pct = profit / total_no_price * 100 if total_no_price > 0 else 0
        
        return {
            'total_no_price': total_no_price,
            'profit': profit,
            'profit_pct': profit_pct,
            'outcomes': outcomes,
            'type': 'buy_all_no'
        }
    
    def generate_signal(self, market_data: MarketData) -> Optional[Signal]:
        """
        Generate signal if multi-outcome arbitrage is detected.
        
        Note: This requires market_data to have 'multi_outcome' field
        with list of outcomes and their NO prices.
        """
        # Check if we have multi-outcome data
        multi_outcome = getattr(market_data, 'multi_outcome', None)
        
        if not multi_outcome:
            return None
        
        # Analyze for arbitrage
        arb = self.analyze_multi_outcome_market(multi_outcome)
        
        if not arb:
            return None
        
        # Generate high-confidence signal
        # This is essentially risk-free (minus gas/fees)
        confidence = 0.95
        
        return Signal(
            strategy=self.name,
            signal="arbitrage",
            confidence=confidence,
            reason=f"Multi-outcome arb: {arb['profit_pct']:.2f}% profit buying all NO",
            metadata={
                'profit': arb['profit'],
                'profit_pct': arb['profit_pct'],
                'total_no_price': arb['total_no_price'],
                'outcomes': len(arb['outcomes']),
                'arb_type': arb['type']
            }
        )
