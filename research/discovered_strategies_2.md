# Additional Discovered Strategies - Continuous Research

## Date: 2025-02-16

---

## 1. Sharp Money Tracking (Reverse Line Movement)
**Source:** Action Network, Sports Betting Education
**Type:** Information edge / Market sentiment

**Concept:**
- Track "sharp" (professional) money vs "public" (retail) money
- Reverse Line Movement (RLM): When line moves AWAY from popular side
- Example: 70% of public bets on YES, but price moves toward NO
- Indicates smart money is on the contrarian side

**Key Indicators:**
- Bet Signals: Sudden line shifts at multiple books
- Bets vs Dollars discrepancy: Low % of bets but high % of dollars = sharp action
- Line freeze: Heavy public support but line doesn't move (books protecting other side)
- Contrarian plays: <40% of bets with line moving toward them

**Implementation for Polymarket:**
- Monitor order book flow (large orders vs small orders)
- Track wallet profitability (via Hashdive or similar)
- Look for price movement against volume-weighted sentiment
- Follow wallets with proven track records (whale copying)

---

## 2. Market Making with Liquidity Rewards
**Source:** Polymarket Docs, defiance_cr interview
**Type:** Passive income / Market microstructure

**Concept:**
- Place limit orders on both sides of the book
- Capture spread + earn liquidity rewards
- Rewards formula favors two-sided liquidity (3x more than one-sided)
- Closer to mid price = higher rewards

**Key Parameters:**
- Half-spread distance from mid
- Position skew (adjust based on inventory)
- Volatility assessment (wider spreads in volatile markets)
- Market selection (low volatility + high rewards = best)

**Real Example:**
- @defiance_cr made $700-800/day at peak
- Started with $10K, scaled up
- Key: Find markets with mispriced risk/reward
- Bot analyzes 3h, 24h, 7d, 30d volatility

**Implementation Notes:**
- Need automated order management
- Position merging to reduce gas fees
- Real-time order book monitoring via WebSocket
- Google Sheets integration for parameter tuning

---

## 3. Volatility-Based Market Selection
**Source:** defiance_cr interview, Poly-Maker bot
**Type:** Risk management / Market selection

**Concept:**
- Rank markets by risk-adjusted return potential
- Calculate volatility across multiple timeframes
- Avoid high-volatility markets (news-driven, unpredictable)
- Target low-volatility markets with steady reward rates

**Formula:**
```
Risk-Adjusted Score = Liquidity Rewards / Volatility
```

**Volatility Calculation:**
- Standard deviation of price over window
- Look at 3h, 24h, 7d, 30d timeframes
- Markets with stable ranges (e.g., 22-25% over weeks) = low vol

**Example Markets:**
- GOOD: Canada PM market (Poilievre 22-25% stable)
- BAD: US trade deal market (headline-driven, massive swings)

---

## 4. Multi-Timeframe Momentum
**Source:** Poly-Maker bot analysis
**Type:** Trend following

**Concept:**
- Analyze price across multiple timeframes simultaneously
- 3h (micro), 24h (short), 7d (medium), 30d (long)
- Align signals across timeframes for higher confidence
- Avoid markets with conflicting timeframe signals

**Implementation:**
- Calculate momentum score for each timeframe
- Weighted average: 40% 3h + 30% 24h + 20% 7d + 10% 30d
- Signal when weighted score > threshold

---

## 5. Information Front-Running (News-Based)
**Source:** Dropstab research, Biteye analysis
**Type:** Information edge / Speed

**Concept:**
- Exploit time lag between news and price updates
- Monitor primary sources (Twitter, news APIs, official feeds)
- NLP for sentiment analysis on breaking news
- Execute within seconds of signal detection

**Key Sources:**
- Twitter/X for real-time updates
- Official government feeds (BLS, Fed)
- Sports live feeds (faster than TV broadcast)
- Crypto exchange APIs for price oracle events

**Challenges:**
- High competition from bots
- Risk of false signals / rumors
- Need sub-second latency
- Adverse selection risk

---

## 6. Mathematical Arbitrage (YES + NO != $1)
**Source:** Dropstab, Biteye
**Type:** Risk-free arbitrage

**Concept:**
- Binary options must settle at $1 (YES=$1, NO=$0 or vice versa)
- If YES + NO < $1: Buy both, redeem for $1
- If YES + NO > $1: Mint pair for $1, sell both
- Bots catch most, but mispricings appear during news spikes

**Implementation:**
- Monitor all markets for YES + NO price sum
- Calculate profit after fees/gas
- Execute when profit > threshold
- Multi-outcome version: Sum of all probabilities should = 1

---

## 7. Wallet Tracking (Whale Following)
**Source:** Hashdive, Dropstab
**Type:** Copy trading / Information edge

**Concept:**
- Track wallets with high win rates
- Flag "potential insiders" with unusual performance
- Follow their entries (copy trading)
- Tools: Hashdive, Dune dashboards, manual tracking

**Key Metrics:**
- Win rate > 60%
- Profit consistency
- Position sizing patterns
- Timing (early entries before price moves)

**Implementation:**
- Monitor target wallet addresses
- Alert on new positions
- Copy trade at configurable % of their size
- Risk management: Stop if they stop out

---

## 8. Fade the Public (Contrarian)
**Source:** Action Network, Sports betting theory
**Type:** Behavioral edge

**Concept:**
- Public bets on bias, not value
- Overvalue: Recent performance, home teams, favorites, overs
- Look for >70% public on one side
- Fade (bet against) the public
- Best when combined with sharp money confirmation

**Polymarket Application:**
- Monitor volume vs price movement
- High volume buying but price stagnant = smart money selling
- Look for divergences between sentiment and price

---

## 9. Time-Decay Exploitation (Theta)
**Source:** Reddit, Medium
**Type:** Structural edge

**Concept:**
- Long-dated markets have time value not priced in
- Early sellers discount for capital lockup
- Buy YES early when over-discounted
- Sell before settlement to avoid resolution risk

**Example:**
- 2026 election markets in 2024
- Early NO sellers create YES opportunity
- Exit before final resolution

---

## 10. Cross-Market Correlation
**Source:** Statistical arbitrage research
**Type:** Quantitative

**Concept:**
- Related markets should move together
- Example: Trump election odds vs GOP control odds
- When correlation breaks, bet on reversion
- Calculate correlation coefficient over window

**Implementation:**
- Identify correlated market pairs
- Monitor correlation coefficient
- When |correlation| < threshold, wait
- When divergence > threshold, bet on reversion

---

## Priority Implementation Queue

### Immediate (This Week)
1. ✅ Order Book Imbalance - DONE
2. ✅ Negative Risk Arbitrage - DONE
3. Sharp Money Detection (wallet tracking + volume analysis)
4. Volatility-Based Market Scorer

### Short Term (Next 2 Weeks)
5. Multi-Timeframe Momentum
6. Mathematical Arbitrage Scanner
7. Cross-Market Correlation Monitor

### Medium Term (Next Month)
8. Market Making Bot (with liquidity rewards)
9. News-Based Front-Running (NLP)
10. Full Backtesting Framework

---

## Resources Found

### GitHub Repos
- warproxxx/poly-maker: Market making bot (open source)
- discountry/polymarket-trading-bot: Beginner-friendly bot
- ent0n29/polybot: Reverse-engineering toolkit
- Novus-Tech-LLC/Polymarket-Arbitrage-Bot: Production-ready

### Tools
- Hashdive: Wallet tracking and insider detection
- Dune Analytics: On-chain data dashboards
- Polymarket CLOB API: Real-time order book

### Key Insights
- Only 7.6% of wallets are profitable
- Top traders make $200-800/day with market making
- Alpha half-life is < 2 minutes for news events
- Liquidity rewards favor two-sided quoting
- Best opportunities in low-volatility, high-reward markets
