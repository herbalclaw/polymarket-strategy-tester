# Polymarket Strategy Tester

Modular strategy testing framework for Polymarket prediction markets.

## Features

- **Modular Strategy System**: Add strategies as plugins
- **Paper Trading**: Test without real money
- **Backtesting**: Test against historical data
- **Multi-Exchange Data**: Aggregate prices from 7+ exchanges
- **Sentiment Analysis**: News and social media signals

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run paper trading with all strategies
python run_paper_trading.py

# Backtest a specific strategy
python run_backtest.py --strategy momentum --data data/btc_5min.csv

# Test single strategy
python test_strategy.py --strategy arbitrage
```

## Strategy Structure

Create a new strategy in `strategies/`:

```python
from core.base_strategy import BaseStrategy

class MyStrategy(BaseStrategy):
    name = "my_strategy"
    
    def generate_signal(self, data):
        # Your logic here
        return {
            "signal": "up",  # or "down"
            "confidence": 0.75,
            "reason": "My reason"
        }
```

## Available Strategies

| Strategy | Description | Status |
|----------|-------------|--------|
| Momentum | Follow aggregated price direction | ✅ Active |
| Arbitrage | Exploit price discrepancies | ✅ Active |
| VWAP | Mean reversion to VWAP | ✅ Active |
| LeadLag | Follow leading exchange | ✅ Active |
| Sentiment | News/social media based | ✅ Active |

## Project Structure

```
polymarket-strategy-tester/
├── core/               # Core framework
├── strategies/         # Strategy implementations
├── backtest/          # Backtesting engine
├── data/              # Data sources
├── tests/             # Unit tests
└── examples/          # Usage examples
```
