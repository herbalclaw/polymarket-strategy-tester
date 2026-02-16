# Discovered Trading Strategies for Polymarket

## Active Research Log

### 1. Order Book Imbalance (OBI) Strategy
**Source:** HFT Backtest Documentation
**Type:** High-frequency market microstructure

**Concept:**
- Calculate imbalance between bid and ask volumes in order book
- Formula: (BidQty - AskQty) / (BidQty + AskQty)
- Standardize over rolling window for z-score
- Positive imbalance = bullish signal, negative = bearish

**Implementation Notes:**
- Need Level 2 order book data (bids/asks with quantities)
- Look at top N levels (e.g., 1% depth from mid price)
- Standardize over window (e.g., 100 ticks) for mean reversion
- Can combine with VAMP (Volume Adjusted Mid Price)

**Potential for Polymarket:**
- Polymarket CLOB API provides order book depth
- 5-minute BTC markets have enough liquidity
- Can detect short-term directional bias

---

### 2. Cross-Platform Arbitrage
**Source:** Biteye/Futunn Analysis
**Type:** Risk-free arbitrage

**Concept:**
- Same event traded on multiple platforms (Polymarket, Kalshi, etc.)
- Buy low on one platform, sell high on another
- Requires simultaneous positions

**Challenges:**
- Different oracle mechanisms may lead to different settlements
- Capital requirements (need accounts on multiple platforms)
- Transfer delays between platforms

**Potential for Polymarket:**
- Limited to events available on multiple platforms
- Political events often on both Polymarket and Kalshi
- Crypto price predictions could be arbitraged with derivatives

---

### 3. Negative Risk Arbitrage (Multi-Outcome)
**Source:** Biteye Analysis
**Type:** Mathematical arbitrage

**Concept:**
- In multi-outcome markets (elections with multiple candidates)
- Sum of all probabilities should = 1
- If sum < 1, buy all NO positions for guaranteed profit
- If sum > 1, buy all YES positions (less common)

**Formula:**
- For N outcomes, if Σ(NO_prices) < 1, buy all NO
- Profit = 1 - Σ(NO_prices)

**Potential for Polymarket:**
- Election markets with 3+ candidates
- Sports tournaments with multiple teams
- Need to check if market allows buying all outcomes

---

### 4. Spread Market Making
**Source:** Biteye Analysis
**Type:** Market making

**Concept:**
- Place limit orders on both sides of the book
- Capture bid-ask spread
- Requires inventory management

**Key Parameters:**
- Half-spread (distance from mid price)
- Skew (adjust based on position)
- Position limits

**Potential for Polymarket:**
- New/low liquidity markets have wider spreads
- Need to manage inventory risk
- 5-minute markets may have less competition

---

### 5. Statistical Arbitrage (Mean Reversion)
**Source:** dYdX, QuantInsti
**Type:** Quantitative/statistical

**Concept:**
- Identify pairs of correlated assets
- When spread diverges from mean, bet on reversion
- Long underperformer, short outperformer

**For Polymarket:**
- BTC/ETH price correlation
- Similar events with different timeframes
- Cross-asset relationships

**Challenges:**
- Can't short on Polymarket directly (buy NO instead)
- Need to find cointegrated pairs

---

### 6. Information-Based Front-Running
**Source:** Biteye Analysis
**Type:** Information edge

**Concept:**
- Exploit time lag between news and price updates
- Requires faster data source than market
- Examples: live sports feeds, election results

**Implementation:**
- Monitor primary data sources (Twitter, news APIs)
- NLP for sentiment analysis
- Rapid execution when signal detected

**Potential for Polymarket:**
- High competition from bots
- Need sub-second latency
- Risk of adverse selection

---

### 7. Volatility + Probability Arbitrage
**Source:** Biteye (distinct-baguette case)
**Type:** Automated statistical

**Concept:**
- Wait for volatility/panic repricing
- When YES + NO < 1, buy both sides
- Small profits per trade, high frequency
- 26,756 trades, $448K profit, $17 avg per trade

**Key Insight:**
- Market inefficiencies during volatile periods
- Combine with position sizing
- Exit before settlement to avoid resolution risk

---

### 8. Time-Value Distortion (Multi-Year Markets)
**Source:** Reddit r/CryptoCurrency
**Type:** Structural edge

**Concept:**
- Long-dated markets have time value not priced in
- Early sellers discount for capital lockup
- Buy YES early when over-discounted

**Example:**
- 2026 election markets in 2024
- Early NO sellers create YES opportunity

---

## Strategy Priority for Implementation

1. **Order Book Imbalance** - Can implement with current data feed
2. **Negative Risk Arbitrage** - Simple math, check market availability
3. **Volatility + Probability** - Good for automated trading
4. **Spread Market Making** - Requires inventory management
5. **Statistical Arbitrage** - Need more data analysis
6. **Cross-Platform** - Requires multiple exchange accounts

## Next Steps

- [ ] Implement OBI strategy with order book data
- [ ] Create multi-outcome arbitrage scanner
- [ ] Analyze historical data for mean reversion opportunities
- [ ] Build volatility detection for probability arbitrage
