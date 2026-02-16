# Continuous Strategy Discovery & Adaptation System

This system continuously monitors top Polymarket traders, deciphers their strategies, and automatically adds them to paper trading.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    MASTER ORCHESTRATOR                          │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   Paper      │  │   Strategy   │  │   Auto-      │          │
│  │   Trading    │  │   Discovery  │  │   Integrator │          │
│  │   (5s cycle) │  │   (30min)    │  │   (5min)     │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│         │                 │                  │                  │
│         ▼                 ▼                  ▼                  │
│  ┌──────────────────────────────────────────────────────┐      │
│  │              STRATEGY ENGINE                         │      │
│  │  [Base Strategies] + [Discovered Strategies]         │      │
│  └──────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

## Components

### 1. Strategy Discovery Engine (`discovery/strategy_discovery.py`)

**Purpose**: Analyzes top trader wallets to decipher their strategies

**Target Wallets**:
- `0x9d84...` - $2.6M profit, 63% win rate
- `0xd218...` - $958K profit, 67% win rate

**Pattern Analysis**:
- Time patterns (algorithmic vs discretionary)
- Market specialization
- Position sizing consistency
- Trade frequency

**Strategy Hypothesis**:
- Latency Arbitrage (high frequency + algorithmic)
- High Conviction Specialist (selective + consistent sizing)
- Multi-Strategy Algorithmic (diversified + systematic)

**Output**:
- Auto-generated Python strategy files in `strategies/discovered/`
- SQLite database with pattern history
- Markdown reports

### 2. Auto-Integrator (`discovery/auto_integrator.py`)

**Purpose**: Automatically adds discovered strategies to live paper trading

**Process**:
1. Polls discovery database every 5 minutes
2. Loads new strategy classes dynamically
3. Instantiates and adds to StrategyEngine
4. Begins paper trading immediately

### 3. Master Orchestrator (`master_orchestrator.py`)

**Purpose**: Runs all components together

**Schedule**:
| Component | Interval | Action |
|-----------|----------|--------|
| Paper Trading | 5 seconds | Execute signals, record trades |
| Discovery | 30 minutes | Analyze wallets, generate strategies |
| Integration | 5 minutes | Add new strategies to trading |
| Excel Report | 50 cycles | Generate performance report |

## Usage

### Start Everything
```bash
cd polymarket-strategy-tester
source venv/bin/activate
python master_orchestrator.py
```

### Run Discovery Only
```bash
python discovery/strategy_discovery.py
```

### Run Auto-Integrator Only
```bash
python discovery/auto_integrator.py
```

## Database Schema

### `deciphered_strategies`
- `strategy_name` - Unique identifier
- `wallet_source` - Origin wallet
- `strategy_code` - Python code
- `description` - JSON hypothesis
- `active` - Currently trading
- `created_at` / `updated_at` - Timestamps

### `strategy_patterns`
- `wallet` - Analyzed wallet
- `pattern_type` - Category
- `pattern_data` - JSON analysis
- `confidence` - Hypothesis confidence

### `strategy_updates`
- Tracks changes to strategies over time
- Records why updates occurred

## Strategy Templates

The system generates strategies based on detected patterns:

### Latency Arbitrage
- Fast execution on price discrepancies
- Small positions, high volume
- Millisecond-level timing

### High Conviction
- Multiple confirming factors required
- Selective entry (2+ factors)
- Consistent position sizing

### Multi-Strategy
- Combines momentum, mean reversion, breakout
- Dynamic weighting based on performance
- Risk parity allocation

## Monitoring

### Logs
- `master_orchestrator.log` - Main orchestrator
- `strategy_discovery.log` - Discovery engine
- `auto_integrator.log` - Integration events

### Reports
- `discovery_data/strategy_report.md` - Discovered strategies
- `strategy_report_cycle_*.xlsx` - Performance reports

### Database
- `discovery_data/strategies.db` - SQLite with all data

## Workflow

1. **Discovery** (every 30 min)
   - Fetch wallet activity from Polymarket
   - Analyze patterns
   - Generate strategy code
   - Save to database

2. **Integration** (every 5 min)
   - Check for new strategies
   - Load Python class
   - Add to StrategyEngine
   - Start paper trading

3. **Trading** (every 5 sec)
   - Fetch price data
   - Get signals from ALL strategies
   - Execute highest confidence
   - Record to Excel

4. **Adaptation** (continuous)
   - Monitor strategy performance
   - Update patterns as more data available
   - Refine strategy code
   - Log all changes

## Adding New Target Wallets

Edit `TARGET_WALLETS` in `discovery/strategy_discovery.py`:

```python
TARGET_WALLETS = [
    "0x9d84...",
    "0xd218...",
    "0xNEW_WALLET...",  # Add here
]
```

## Safety Features

- All strategies start in paper trading only
- Confidence threshold (60%+) required for trades
- Strategy performance tracked separately
- Easy to disable strategies by setting `active = 0`
