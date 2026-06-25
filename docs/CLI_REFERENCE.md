# TheEyeBeta CLI Reference (Prod)

> Complete command reference — matches TheEyeBetaLocal `docs/CLI_REFERENCE.md`.
> On prod use `./theeye` (shim → `tb`) or `uv run tb` from TheEyeBetaProd root.

## Quick Setup

```bash
cd /home/the-eye-beta/TheEyeBeta2025/TheEyeBetaProd
./theeye now status
# equivalent: uv run tb now status
```

> **That's it!** The `./theeye` wrapper auto-configures the prod workspace venv.

**Prod-only extras** (not in Local `./theeye` docs): `tb status`, `tb prelive`, `tb workers`, `tb canonical`, `tb intraday`, `tb deploy`, `tb secrets`.

---

## Command Groups

| Group | Description |
|-------|-------------|
| `now` | Live data queries (prices, indicators, news, signals) |
| `engine` | Engine management and health |
| `db` | Database verification |
| `instrument` | Ticker/instrument management |
| `pipeline` | Daily pipeline operations |
| `plot` | Stock charts with technical indicators |
| `quant` | Quant research tools (projects 1–10: returns, VaR, Sharpe, frontier, pairs, etc.) |
| `trask` | Audit & monitoring: worker/sentinel status, control, alerts, digests |

---

## 1. NOW Commands — Live Data Queries

### `now status`
Shows overall engine health and statistics.

**Syntax:**
```bash
./theeye now status
```

**Sample Calls:**
```bash
# 1. Basic status check
./theeye now status

# 2. Status with JSON output (if supported)
./theeye now status --json
```

---

### `now price <TICKER>`
Returns the latest price for a specific ticker.

**Syntax:**
```bash
./theeye now price <TICKER>
```

**Sample Calls:**
```bash
# 3. Apple current price
./theeye now price AAPL

# 4. Microsoft current price
./theeye now price MSFT

# 5. Google current price
./theeye now price GOOGL

# 6. Amazon current price
./theeye now price AMZN

# 7. Tesla current price
./theeye now price TSLA

# 8. Meta current price
./theeye now price META

# 9. NVIDIA current price
./theeye now price NVDA

# 10. JPMorgan current price
./theeye now price JPM

# 11. Visa current price
./theeye now price V

# 12. Walmart current price
./theeye now price WMT

# 13. Johnson & Johnson
./theeye now price JNJ

# 14. Procter & Gamble
./theeye now price PG

# 15. Mastercard
./theeye now price MA

# 16. UnitedHealth
./theeye now price UNH

# 17. Home Depot
./theeye now price HD

# 18. Bank of America
./theeye now price BAC

# 19. Pfizer
./theeye now price PFE

# 20. Disney
./theeye now price DIS

# 21. Coca-Cola
./theeye now price KO

# 22. Netflix
./theeye now price NFLX

# 23. Adobe
./theeye now price ADBE

# 24. Salesforce
./theeye now price CRM

# 25. Intel
./theeye now price INTC

# 26. AMD
./theeye now price AMD

# 27. Cisco
./theeye now price CSCO

# 28. Oracle
./theeye now price ORCL

# 29. Berkshire Hathaway B
./theeye now price BRK-B

# 30. Exxon Mobil
./theeye now price XOM
```

---

### `now indicators <TICKER> [--long]`
Returns latest technical indicators from `latest_snapshot`.

- **Default (short)**: Price, SMA 50/200, EMA 50/200, RSI 14, MACD, and current signal.
- **`--long` / `-l`**: Full suite — adds momentum (RSI 9, Stochastic, Williams %R, CCI, ADX), Bollinger Bands, volume metrics, fundamentals (P/E, PEG, P/B, EPS, dividend yield, market cap), derived price-vs-MA metrics, and bullish/oversold/overbought flags.

**Syntax:**
```bash
./theeye now indicators <TICKER>          # short view
./theeye now indicators <TICKER> --long   # full view
./theeye now indicators <TICKER> -l       # full view (short flag)
```

**Sample Calls:**
```bash
# 31. Apple indicators (short)
./theeye now indicators AAPL

# 32. Apple indicators (full)
./theeye now indicators AAPL --long

# 33. Tesla indicators (short)
./theeye now indicators TSLA

# 34. Tesla indicators (full)
./theeye now indicators TSLA -l

# 35. NVIDIA indicators
./theeye now indicators NVDA

# 36. NVIDIA full
./theeye now indicators NVDA --long

# 37. Microsoft indicators
./theeye now indicators MSFT

# 38. Amazon full
./theeye now indicators AMZN --long

# 39. Google indicators
./theeye now indicators GOOGL

# 40. Meta full
./theeye now indicators META -l
```

---

### `now news <TICKER> [--limit N]`
Returns recent news for a ticker.

**Syntax:**
```bash
./theeye now news <TICKER> [--limit N]
```

**Sample Calls:**
```bash
# 41. Apple news (default 10)
./theeye now news AAPL

# 42. Apple news (3 items)
./theeye now news AAPL --limit 3

# 43. Apple news (5 items)
./theeye now news AAPL --limit 5

# 44. Apple news (20 items)
./theeye now news AAPL --limit 20

# 45. Apple news (1 item - latest only)
./theeye now news AAPL --limit 1

# 46. Apple news (50 items)
./theeye now news AAPL --limit 50

# 47. Tesla news (10 items)
./theeye now news TSLA --limit 10

# 48. NVIDIA news (15 items)
./theeye now news NVDA --limit 15

# 49. Microsoft news (5 items)
./theeye now news MSFT --limit 5

# 50. Amazon news (7 items)
./theeye now news AMZN --limit 7

# 51. Using short flag -n
./theeye now news AAPL -n 5

# 52. Meta news
./theeye now news META -n 10

# 53. Google news
./theeye now news GOOGL -n 8

# 54. Netflix news
./theeye now news NFLX -n 12

# 55. AMD news
./theeye now news AMD -n 6
```

---

### `now signals <TICKER> [--limit N]`
Returns trading signals from algorithms.

**Syntax:**
```bash
./theeye now signals <TICKER> [--limit N]
```

**Sample Calls:**
```bash
# 56. Apple signals (default)
./theeye now signals AAPL

# 57. Apple signals (5 most recent)
./theeye now signals AAPL --limit 5

# 58. Apple signals (3 most recent)
./theeye now signals AAPL --limit 3

# 59. Apple signals (20 most recent)
./theeye now signals AAPL --limit 20

# 60. Apple signals (1 - latest only)
./theeye now signals AAPL --limit 1

# 61. Tesla signals
./theeye now signals TSLA --limit 10

# 62. NVIDIA signals
./theeye now signals NVDA --limit 5

# 63. Microsoft signals
./theeye now signals MSFT --limit 8

# 64. Amazon signals
./theeye now signals AMZN -n 5

# 65. Google signals
./theeye now signals GOOGL -n 7
```

---

## 2. ENGINE Commands — Health & Management

### `engine ping`
Quick health check for the engine.

**Syntax:**
```bash
./theeye engine ping
```

**Sample Calls:**
```bash
# 66. Basic ping
./theeye engine ping

# 67. Ping (alias for status)
./theeye engine status
```

---

## 3. DB Commands — Database Operations

### `db verify`
Verifies database tables, indexes, and constraints exist.

**Syntax:**
```bash
./theeye db verify
```

**Sample Calls:**
```bash
# 68. Verify database schema
./theeye db verify
```

---

## 4. INSTRUMENT Commands — Ticker Management

### `instrument list`
Lists all tracked instruments/tickers.

**Syntax:**
```bash
./theeye instrument list
```

**Sample Calls:**
```bash
# 70. List all instruments
./theeye instrument list

# 71. List with head (first 20)
./theeye instrument list | head -20

# 72. List with count
./theeye instrument list | wc -l

# 73. Search for specific ticker
./theeye instrument list | grep AAPL

# 74. Search for tech tickers
./theeye instrument list | grep -E "AAPL|MSFT|GOOGL|META"

# 75. Search for bank tickers
./theeye instrument list | grep -E "JPM|BAC|GS|MS|C"
```

### `instrument add <TICKER>`
Adds a new instrument to track.

**Syntax:**
```bash
./theeye instrument add <TICKER> [--name NAME] [--exchange EXCHANGE]
```

**Sample Calls:**
```bash
# 76. Add ticker (basic)
./theeye instrument add PLTR

# 77. Add ticker with name
./theeye instrument add PLTR --name "Palantir Technologies"

# 78. Add ticker with exchange
./theeye instrument add PLTR --exchange NASDAQ

# 79. Add ticker with all options
./theeye instrument add COIN --name "Coinbase Global" --exchange NASDAQ

# 80. Add another ticker
./theeye instrument add RIVN --name "Rivian Automotive" --exchange NASDAQ
```

---

## 5. PIPELINE Commands — Daily Operations

### `pipeline daily`
Runs the daily data pipeline.

**Syntax:**
```bash
./theeye pipeline daily [OPTIONS]
```

**Sample Calls:**
```bash
# 81. Run full daily pipeline
./theeye pipeline daily

# 82. Run ingest only
./theeye pipeline daily --mode ingest-only

# 83. Run compute only
./theeye pipeline daily --mode compute-only

# 84. Skip non-trading days
./theeye pipeline daily --skip-non-trading

# 85. Fail fast on errors
./theeye pipeline daily --fail-fast

# 86. Custom lookback period
./theeye pipeline daily --lookback 1y

# 87. Custom batch size
./theeye pipeline daily --batch-size 20

# 88. JSON output
./theeye pipeline daily --json-output

# 89. Dry run (preview)
./theeye pipeline daily --dry-run

# 90. Force update (bypass market hours check)
./theeye pipeline daily --force-update

# 91. Custom post-close delay
./theeye pipeline daily --post-close-delay 2.0

# 92. Combined options
./theeye pipeline daily --mode full --skip-non-trading --batch-size 15

# 93. Full options for production
./theeye pipeline daily --mode full --fail-fast --skip-non-trading

# 94. Testing mode
./theeye pipeline daily --dry-run --json-output
```

---

## 6. PLOT Commands — Technical Charts

### `plot price <TICKER>`
Simple price chart.

```bash
# 95. Basic price chart
./theeye plot price AAPL

# 96. 1-year range
./theeye plot price MSFT --range 1y

# 97. Save to file
./theeye plot price GOOGL --save googl_price.png
```

### `plot all <TICKER>`
Price with all SMA/EMA overlays (10, 50, 200) and golden/death cross markers.

```bash
# 98. Full overlay chart
./theeye plot all AAPL

# 99. 1-year with save
./theeye plot all NVDA --range 1y --save nvda_all.png
```

### `plot sma <TICKER>` / `plot ema <TICKER>`
Price with only SMA or EMA overlays.

```bash
# 100. SMA overlays
./theeye plot sma AAPL

# 101. EMA overlays
./theeye plot ema TSLA --range 1y
```

### `plot volume <TICKER>`
Price with colour-coded volume bars (green = up day, red = down day).

```bash
# 102. Volume chart
./theeye plot volume AAPL

# 103. Volume 1-year saved
./theeye plot volume MSFT --range 1y --save msft_vol.png
```

### `plot rsi <TICKER>`
Price with RSI(14) subplot. Highlights oversold (<30) and overbought (>70) zones.

```bash
# 104. RSI chart
./theeye plot rsi AAPL

# 105. RSI 1-year
./theeye plot rsi NVDA --range 1y
```

### `plot macd <TICKER>`
Price with MACD / signal line / histogram subplot.

```bash
# 106. MACD chart
./theeye plot macd AAPL

# 107. MACD saved
./theeye plot macd MSFT --range 1y --save msft_macd.png
```

### `plot splits <TICKER>`
Price with corporate action markers (splits = dashed yellow, dividends = dotted cyan).

```bash
# 108. Splits/dividends over 5 years
./theeye plot splits AAPL --range 5y

# 109. Splits saved
./theeye plot splits NVDA --range 5y --save nvda_splits.png
```

### `plot full <TICKER>`
Comprehensive multi-panel chart: price + SMA/EMA + volume + RSI + MACD + corporate actions.

```bash
# 110. Full technical view
./theeye plot full AAPL

# 111. Full view 1-year saved
./theeye plot full MSFT --range 1y --save msft_full.png
```

### `plot custom <TICKER> [OPTIONS]`
Pick any combination of overlays and subplots.

```bash
# 112. Custom: price + EMA-50 + RSI
./theeye plot custom AAPL --price --ema-50 --rsi

# 113. Custom: price + SMA-50 + SMA-200 + volume + MACD
./theeye plot custom MSFT --price --sma-50 --sma-200 --volume --macd

# 114. Custom: everything
./theeye plot custom GOOGL --price --ema-10 --ema-50 --sma-200 --volume --rsi --macd --splits --crosses
```

---

## 7. QUANT Commands — Beginner Quant Projects (1–10)

The `quant` group exposes the 10 beginner quant projects as **ready-made tools**:

1. Daily returns & volatility analyzer  
2. Rolling correlation & covariance explorer  
3. Sharpe ratio optimizer  
4. EMA crossover backtest (wrapper around existing backtest)  
5. Monte Carlo option pricing  
6. Value at Risk (VaR) & Expected Shortfall (CVaR)  
7. Risk parity portfolio  
8. CAPM beta & factor exposure  
9. Mean–variance efficient frontier  
10. Pairs trading with cointegration  

All commands use the same pricing data and indicators that power the engine.

### `quant returns <TICKERS> --start YYYY-MM-DD --end YYYY-MM-DD`
Project 1 – Daily Returns and Volatility Analyzer.

- Loads `price_daily` for the given tickers, computes:
  - Daily returns
  - Cumulative returns
  - Rolling 20‑day annualized volatility
- Prints a summary table (total return and vol per ticker).

**Syntax:**
```bash
./theeye quant returns AAPL,MSFT --start 2025-01-01 --end 2025-12-31
```

**Sample Calls:**
```bash
# 115. 1-year returns & vol for AAPL, MSFT, NVDA
./theeye quant returns AAPL,MSFT,NVDA --start 2025-01-01 --end 2025-12-31

# 116. 6-month returns & vol for a FAANG mini-basket
./theeye quant returns AAPL,AMZN,META,NFLX --start 2025-07-01 --end 2025-12-31
```

---

### `quant corr <TICKERS> [--window N]`
Project 2 – Rolling Correlation and Covariance Explorer.

- Uses `RollingCorrelationAnalyzer` on daily returns.
- Shows the **latest correlation matrix** for the chosen rolling window.

**Syntax:**
```bash
./theeye quant corr AAPL,MSFT,NVDA --window 60
```

**Sample Calls:**
```bash
# 117. 60-day rolling correlation for big tech
./theeye quant corr AAPL,MSFT,GOOGL,AMZN,META --window 60

# 118. 30-day rolling correlation for banks
./theeye quant corr JPM,BAC,GS,MS --window 30
```

---

### `quant sharpe-opt <TICKERS> [--rf R] [--allow-short]`
Project 3 – Sharpe Ratio Optimizer.

- Loads daily returns and runs a **mean–variance Sharpe optimizer**.
- Prints optimal weights, expected return, volatility, and Sharpe ratio.

**Syntax:**
```bash
./theeye quant sharpe-opt AAPL,MSFT,NVDA --rf 0.02
```

**Sample Calls:**
```bash
# 119. Long-only maximum Sharpe portfolio for AAPL/MSFT/NVDA
./theeye quant sharpe-opt AAPL,MSFT,NVDA --rf 0.02

# 120. Allow shorting in a 4-asset universe
./theeye quant sharpe-opt AAPL,MSFT,GOOGL,AMZN --rf 0.01 --allow-short
```

---

### `quant ema-backtest <TICKER> [--start] [--end]`
Project 4 – EMA Crossover Backtest.

- High-level wrapper around the existing EMA crossover backtest engine.
- Simulates long/flat EMA(12,26) crossover strategy and prints summary stats.

**Syntax:**
```bash
./theeye quant ema-backtest AAPL --start 2024-01-01 --end 2024-12-31
```

**Sample Calls:**
```bash
# 121. 1-year EMA crossover backtest for AAPL
./theeye quant ema-backtest AAPL --start 2025-01-01 --end 2025-12-31

# 122. 3-year EMA crossover backtest for TSLA
./theeye quant ema-backtest TSLA --start 2023-01-01 --end 2025-12-31
```

---

### `quant mc-option S0 K T SIGMA [--r R] [--paths N] [--steps N] [--type call|put]`
Project 5 – Monte Carlo Option Pricing.

- Prices a **European call or put** under GBM using Monte Carlo.
- Uses `price_european_option_mc` with configurable paths and steps.

**Syntax:**
```bash
./theeye quant mc-option 100 110 0.5 0.25 --r 0.03 --paths 20000 --steps 252 --type call
```

**Sample Calls:**
```bash
# 123. 6M call, 25% vol, 3% r, 10k paths
./theeye quant mc-option 100 110 0.5 0.25 --r 0.03 --paths 10000

# 124. 1Y put, 40% vol, more simulations
./theeye quant mc-option 80 75 1.0 0.40 --r 0.02 --paths 50000 --type put
```

---

### `quant var <TICKERS> [--confidence C] [--window N]`
Project 6 – Value at Risk (VaR) and Expected Shortfall (CVaR).

- Equal-weights the provided tickers into a simple portfolio.
- Computes **historical VaR and CVaR** over the chosen window using `VaREstimator`.

**Syntax:**
```bash
./theeye quant var AAPL,MSFT --confidence 0.99 --window 252
```

**Sample Calls:**
```bash
# 125. 95% 1-year VaR/CVaR for AAPL+MSFT
./theeye quant var AAPL,MSFT --confidence 0.95 --window 252

# 126. 99% 2-year VaR/CVaR for a 4-stock mini-portfolio
./theeye quant var AAPL,MSFT,GOOGL,AMZN --confidence 0.99 --window 504
```

---

### `quant risk-parity <TICKERS>`
Project 7 – Risk Parity Portfolio.

- Builds a risk-parity allocation using `RiskParityOptimizer`.
- Prints weights and normalized risk contributions by asset.

**Syntax:**
```bash
./theeye quant risk-parity AAPL,MSFT,NVDA,GOOGL
```

**Sample Calls:**
```bash
# 127. Risk parity on a 4-name tech basket
./theeye quant risk-parity AAPL,MSFT,GOOGL,AMZN

# 128. Risk parity on a mixed equity universe
./theeye quant risk-parity AAPL,JNJ,XOM,JPM,HD
```

---

### `quant capm <TICKER> <MARKET> [--rf R]`
Project 8 – CAPM Beta and Factor Exposure Analyzer.

- Runs a CAPM regression of asset excess returns vs market excess returns.
- Returns beta, alpha, R², and summary statistics.

**Syntax:**
```bash
./theeye quant capm AAPL ^GSPC --rf 0.02
```

**Sample Calls:**
```bash
# 129. CAPM beta of AAPL vs S&P 500
./theeye quant capm AAPL ^GSPC --rf 0.02

# 130. CAPM beta of TSLA vs NASDAQ-100 proxy
./theeye quant capm TSLA QQQ --rf 0.01
```

---

### `quant frontier <TICKERS> [--rf R]`
Project 9 – Mean–Variance Efficient Frontier Visualizer (text summary).

- Uses `compute_efficient_frontier` to build the frontier.
- Prints the **tangency (max Sharpe) portfolio** as a quick summary.

**Syntax:**
```bash
./theeye quant frontier AAPL,MSFT,GOOGL,AMZN,META --rf 0.02
```

**Sample Calls:**
```bash
# 131. Efficient frontier for 5 mega-caps
./theeye quant frontier AAPL,MSFT,GOOGL,AMZN,META --rf 0.02

# 132. Lower risk-free rate scenario
./theeye quant frontier AAPL,MSFT,NVDA --rf 0.01
```

---

### `quant pairs <TICKERS> [--max-pairs N]`
Project 10 – Pairs Trading with Cointegration.

- Runs a cointegration scan using `CointegrationTester` and `find_cointegrated_pairs`.
- Shows the top candidate pairs with p-values and hedge ratios.

**Syntax:**
```bash
./theeye quant pairs AAPL,MSFT,GOOGL,AMZN,META --max-pairs 5
```

**Sample Calls:**
```bash
# 133. Scan big tech for cointegrated pairs
./theeye quant pairs AAPL,MSFT,GOOGL,AMZN,META --max-pairs 5

# 134. Scan a financials universe
./theeye quant pairs JPM,BAC,GS,MS,C --max-pairs 3
```

---

## 8. TRASK Commands — Audit & Monitoring

Trask is the central audit and monitoring orchestrator. It manages **Sentinels** (per-worker audit agents) that monitor health, emit structured events, and expose control surfaces.

### `trask status`
Shows overall Trask system status.

**Syntax:**
```bash
./theeye trask status
```

**Sample Calls:**
```bash
# 135. Full system status
./theeye trask status
```

---

### `trask dashboard`
Interactive monitoring dashboard with live updates.

**Syntax:**
```bash
./theeye trask dashboard [--once] [--refresh N]
```

**Sample Calls:**
```bash
# 136. Interactive live dashboard (refreshes every 2s)
./theeye trask dashboard

# 137. Single snapshot (no live updates)
./theeye trask dashboard --once

# 138. Custom refresh rate (5 seconds)
./theeye trask dashboard --refresh 5
```

---

### `trask worker <action> [worker_id]`
Control and monitor workers.

**Syntax:**
```bash
./theeye trask worker status [worker_id]
./theeye trask worker start <worker_id> [--confirm]
./theeye trask worker stop <worker_id> [--confirm]
./theeye trask worker restart <worker_id> [--confirm]
```

**Sample Calls:**
```bash
# 139. View all workers
./theeye trask worker status

# 140. View specific worker
./theeye trask worker status price

# 141. Stop a worker (requires confirmation)
./theeye trask worker stop price

# 142. Stop with auto-confirm
./theeye trask worker stop price --confirm

# 143. Start a worker
./theeye trask worker start news --confirm

# 144. Restart a worker
./theeye trask worker restart indicator --confirm
```

---

### `trask sentinel <action> [sentinel_id]`
Control and monitor sentinels (per-worker audit agents).

**Syntax:**
```bash
./theeye trask sentinel status [sentinel_id]
./theeye trask sentinel start <sentinel_id> [--confirm]
./theeye trask sentinel stop <sentinel_id> [--confirm]
```

**Sample Calls:**
```bash
# 145. View all sentinels
./theeye trask sentinel status

# 146. View specific sentinel
./theeye trask sentinel status price_sentinel

# 147. Stop a sentinel
./theeye trask sentinel stop price_sentinel --confirm
```

---

### `trask digest`
Manage and trigger digest emails.

**Syntax:**
```bash
./theeye trask digest [--now]
```

**Sample Calls:**
```bash
# 148. View digest status and recent emails
./theeye trask digest

# 149. Trigger immediate digest email
./theeye trask digest --now
```

---

### `trask events`
View audit events.

**Syntax:**
```bash
./theeye trask events [--limit N] [--severity S] [--type T]
```

**Sample Calls:**
```bash
# 150. Recent events (default 20)
./theeye trask events

# 151. More events
./theeye trask events --limit 50

# 152. Filter by severity
./theeye trask events --severity error

# 153. Filter by event type
./theeye trask events --type state_change

# 154. Combined filters
./theeye trask events --severity warning --limit 30
```

---

## 9. Advanced Usage — Chained Commands

```bash
# 155. Get price and indicators together
./theeye now price AAPL && ./theeye now indicators AAPL

# 156. Full ticker analysis
./theeye now price AAPL && ./theeye now indicators AAPL && ./theeye now news AAPL --limit 3

# 157. Multi-ticker price check
for t in AAPL MSFT GOOGL; do ./theeye now price $t; done

# 158. Status then specific ticker
./theeye now status && ./theeye now price AAPL

# 159. Verify DB then check engine
./theeye db verify && ./theeye engine ping

# 160. Full system check (engine + Trask)
./theeye engine ping && ./theeye trask status && ./theeye now status
```

---

## Quick Reference Card

| Command | Description |
|---------|-------------|
| `./theeye now status` | Engine health overview |
| `./theeye now price AAPL` | Get current price |
| `./theeye now indicators AAPL` | Key indicators (short) |
| `./theeye now indicators AAPL --long` | Full indicator suite |
| `./theeye now news AAPL -n 5` | Get 5 latest news |
| `./theeye now signals AAPL -n 5` | Get 5 latest signals |
| `./theeye engine ping` | Quick health check |
| `./theeye db verify` | Verify schema |
| `./theeye instrument list` | List all tickers |
| `./theeye instrument add XYZ` | Add new ticker |
| `./theeye pipeline daily` | Run daily update |
| `./theeye plot full AAPL` | Full technical chart |
| `./theeye plot rsi AAPL` | Price + RSI chart |
| `./theeye plot macd AAPL` | Price + MACD chart |
| `./theeye plot volume AAPL` | Price + volume chart |
| `./theeye plot splits AAPL` | Price + corporate actions |
| `./theeye trask status` | Trask audit system status |
| `./theeye trask dashboard` | Interactive monitoring |
| `./theeye trask worker status` | View all workers |
| `./theeye trask sentinel status` | View all sentinels |
| `./theeye trask events` | View audit events |
| `./theeye trask digest --now` | Trigger digest email |

---

## Help Commands

```bash
# Get help for any command
./theeye --help
./theeye now --help
./theeye now price --help
./theeye now news --help
./theeye pipeline daily --help
./theeye instrument --help
```

---

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | Auto-configured |
| `PYTHONPATH` | Python module paths | Auto-configured |
| `FINNHUB_API_KEY` | Finnhub API key for real-time data | Optional |
| `ENGINE_TICKERS` | Tickers to track (`all` or comma-separated) | `all` |
| `ENGINE_PRICE_INTERVAL` | Price fetch interval in seconds | `60` |
| `SMTP_HOST` | SMTP server hostname | `smtp.gmail.com` |
| `SMTP_PORT` | SMTP server port | `587` |
| `SMTP_USER` | SMTP username | Required for email |
| `SMTP_PASSWORD` | SMTP password | Required for email |
| `SMTP_FROM` | From email address | Same as SMTP_USER |
| `TRASK_ALERT_EMAILS` | Comma-separated alert recipients | Required for email |
| `TRASK_EMAIL_TITLE_PREFIX` | Email subject prefix | `TheEyeBeta Trask` |

---

*Updated: June 18, 2026 — Prod parity with Local `./theeye` CLI*
