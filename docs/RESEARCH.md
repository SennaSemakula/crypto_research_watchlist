# RESEARCH

Pre-build research note for the crypto sibling of `stock_research_watchlist`.
Written before any new code in Phase 1 to lock the design assumptions.

Date: 2026-05-02. Author: Claude Code (Senna delegated full autonomy).

## 1. Universe selection

### Thesis

Mirror the stock side's "volatile but high-quality" thesis. The stock universe
targets megacap tech because the volatility is real but the underlying
businesses survive cycles. The crypto analogue is large-cap, deeply-liquid,
multi-cycle-tested coins with real on-chain activity. Memecoins (DOGE, SHIB,
PEPE) are explicitly out: their volatility is uncorrelated with anything
fundamental, so signals do not generalise.

### Hard rules (every member must pass)

| Rule                                      | Threshold                       |
| ----------------------------------------- | ------------------------------- |
| Market cap (today)                        | >= 1,000,000,000 USD            |
| 30d average daily volume                  | >= 100,000,000 USD              |
| Listed on Binance                         | Yes (proxy for global liquidity)|
| Listed on Coinbase                        | Yes (proxy for US/EU compliance)|
| Token / chain age                         | >= 24 months                    |
| Stablecoin                                | Excluded                        |
| Wrapped / staked derivatives              | Excluded (use the underlying)   |
| Memecoin tag                              | Excluded                        |
| Public, identified core team              | Required                        |
| Has spot ETF or institutional custody     | Preferred but not required      |

### Concrete v0 universe (10 names)

This matches what is already committed in `data/historical/symbols.json`:

```
BTC-USD   bitcoin                  L1 reserve
ETH-USD   ethereum                 L1 smart-contract
SOL-USD   solana                   L1 smart-contract
BNB-USD   binance-coin             exchange-coin / L1
XRP-USD   ripple                   payments
ADA-USD   cardano                  L1
AVAX-USD  avalanche                L1
DOT-USD   polkadot                 L1 / interop
LINK-USD  chainlink                oracle / infra
MATIC-USD polygon (legacy ticker)  L2 / scaling
```

Notes on inclusions and exclusions:

- **DOGE** is borderline (originated as a memecoin, is now an institutionally
  recognised top-10 by cap). v0 excludes it: the on-chain activity is thin
  relative to its price, and supply is uncapped. Revisit if it lists in a
  spot ETF.
- **TON, TRX, NEAR, ATOM, APT, ARB, OP, INJ** are legitimate candidates that
  fail the 24-month-age or $1B-cap floor at certain points in the 5y backfill
  window. Adding them later is a one-line edit; the universe loader does not
  hard-code 10.
- **MATIC vs POL** — Polygon migrated tickers in 2024. yfinance still serves
  `MATIC-USD` for the historical series; the v1 universe loader will alias
  POL -> MATIC for spot-data continuity. The token economics changed;
  flagged in the per-asset note.
- **No stablecoins** (USDT, USDC, DAI). They are settlement infrastructure,
  not trading instruments.

### Survivorship caveat

SOL, AVAX, MATIC came online during the 5y window. Backtests must use the
actual listing date as their entry into the eligible set, not paper over
the gap. Already handled correctly in the existing `baseline_backtest.py`
because momentum returns NaN before enough history is available.

## 2. Data sources

All v1 sources are free or generous-free-tier. Paid sources documented
where they would help; interfaces stubbed for later.

### Spot OHLCV (daily)

- **yfinance** (primary). Already wired in `scripts/research/backfill_history.py`.
  Reliable for daily bars on the v0 universe. Survivorship issues are obvious
  (NaN before listing). Rate limit: not strict, but be polite (1s between
  calls).
- **CCXT** (intraday + cross-exchange validation). Wraps ~150 exchanges with
  one API. v1 use: hourly OHLCV from Binance public, fallback to Coinbase if
  the symbol is missing on Binance. CCXT public spot endpoints have no rate
  limit problem at our cadence (hourly fetch of 10 symbols).

### Funding rates (perp futures)

- **CCXT** `fetch_funding_rate(symbol)` against Binance / Bybit. Free public
  endpoint, returns the most recent 8h funding rate. Historical funding
  series via `fetch_funding_rate_history` (Binance only). Stub interface
  is in place; wiring is a v1 task.
- Coinglass has a richer cross-exchange aggregate but the free tier is
  capped at very low call counts; deferred.

### Open interest

- **CCXT** `fetch_open_interest_history` works on Binance and OKX. Daily
  granularity is sufficient. Stubbed.

### Liquidations

- Binance public liquidation websocket for live; their REST endpoint only
  surfaces the last 24h. Treat liquidations as a confirmation signal, not
  a primary trigger; v1 stubs only.

### On-chain

- **Blockchair** REST (free). Active addresses, transaction count for BTC
  and ETH. Daily granularity, no key required, generous rate limit.
- **Etherscan / Solscan / BscScan** public APIs. Per-chain.
- **Glassnode / CryptoQuant** would give richer features (UTXO age bands,
  exchange netflow, MVRV). Paid. Not in v1.

### News / sentiment

- **CryptoPanic** free API tier for headline aggregation. 100 calls/min,
  sufficient.
- **CoinDesk RSS**, **CoinTelegraph RSS** — both free, no key.
- **Reddit** /r/cryptocurrency public JSON endpoints — be cautious about
  signal quality; sentiment from retail-heavy subs is mostly noise.

### Macro context

- **FRED** (free; the stock side already uses it) for DXY, real yields, and
  cross-asset signals. The crypto side will reuse the same provider when
  it lands.
- **^VIX** (yfinance) — already in the macro panel.

### Reliability ranking (v1)

```
yfinance:    reliable, rate-limit-tolerant, daily granularity sufficient
ccxt-spot:   reliable for top-10, intraday available
ccxt-funding: reliable on Binance, intermittent on Bybit
blockchair:  reliable for BTC/ETH, no SOL/ADA/etc
cryptopanic: reliable but signal-to-noise is low
```

## 3. Signals

Each signal: thesis + formula + regime where it works. Calibration of
specific thresholds is left to the daily/weekly calibration agents using
walk-forward sweeps over the backfilled parquet.

### 3.1 Technical (price-only, daily candles)

Same math as the stock side. Adapter file: `signals/technical.py`.

| Signal      | Formula                                        | Bullish trigger          | Bearish trigger        |
| ----------- | ---------------------------------------------- | ------------------------ | ---------------------- |
| RSI(14)     | Wilder's smoothing of gain/loss                | < 30                     | > 70                   |
| EMA cross   | EMA(20) vs EMA(50)                             | golden                   | death                  |
| MACD        | EMA(12) - EMA(26), signal EMA(9)               | line > signal && > 0     | line < signal && < 0   |
| Volume spike| today / 30d-avg                                | >= 2x with positive day  | >= 2x with red day     |
| ATR(14)     | true range, Wilder smooth; for sizing only     | n/a                      | n/a                    |

Crypto-specific tweak: the volume-spike threshold matters less than for
equities because crypto volume is less seasonal (no overnight gap). Keep
the 2x / 3x thresholds and let calibration argue.

### 3.2 Funding-rate divergence

**Thesis.** Perp funding rate is the price longs pay shorts (or vice versa)
to keep the perp anchored to spot. Sustained extreme positive funding
(say > +0.05% per 8h for 24h) means longs are over-leveraged: forward
24h returns historically mean-revert. Sustained extreme negative funding
is bullish (capitulation, shorts paying longs).

**Formula.** Let f_8h be the most-recent 8h funding rate.
- Bullish trigger: median funding over last 24h <= -0.03%
- Bearish trigger: median funding over last 24h >= +0.05%
- Strong: above thresholds AND price has been flat or against the funding

**Regime.** Works best in chop / range-bound regimes. In a strong directional
trend, extreme funding can persist for days without mean-reverting.

### 3.3 Open-interest delta

**Thesis.** Open interest measures how much capital is positioned in perps.
Combined with price action, OI tells a story:
- Rising OI + rising price: trend conviction (bullish)
- Rising OI + flat price: squeeze brewing (direction unclear — wait)
- Falling OI + falling price: capitulation (often a bottom signal)
- Falling OI + rising price: short-cover rally (often unsustainable)

**Formula.** delta_oi_7d = (oi_today - oi_7d_ago) / oi_7d_ago.
Signal: bucket the (delta_oi, delta_price) plane.

### 3.4 Liquidation cascades

**Thesis.** A liquidation cascade is forced selling/buying that exhausts
positioning in one direction. Large prints are an exhaustion signal.

**Formula.** Long liquidations USD over 60 minutes > 0.5% of OI = cascade.
Forward 4h returns post-cascade are positively skewed.

**v1 status:** stubbed. The CCXT REST endpoints don't expose historical
liquidation data well; need websocket capture, which is out of scope for v1.

### 3.5 On-chain activity

**Thesis.** Active addresses and exchange netflow are slow-moving but
predictive of multi-week regime shifts. Coins leaving exchanges imply
holders are moving to cold storage = bullish accumulation. Reverse is
distribution.

**Formula (BTC, ETH only in v1):**
- active_addresses_30d_zscore > 1 = unusually high activity (bullish)
- exchange_netflow_7d (USD) < -100M = strong outflow (bullish)

### 3.6 Cross-asset

**Thesis.** Crypto is not yet a fully decoupled asset class. BTC dominance
and the ETH/BTC ratio tell us where rotation alpha is.

**Formulas.**
- btc_dominance = btc_mcap / total_crypto_mcap
- eth_btc_ratio = ETH_close / BTC_close
- Signals: btc_dominance rising && alts falling = "BTC season" (favour BTC).
  btc_dominance falling = "alt season" (rotate to ETH/SOL/etc).

### 3.7 Macro

**Thesis.** Crypto is risk-on. DXY rising = USD strength = risk-off = headwind.
Real yields rising = competition for capital = headwind.

**Formulas.** Reuse the stock side's FRED provider when ported. v1 ships with
^VIX in the macro panel; DXY/yields land later.

## 4. Risk model

Crypto-specific risks beyond the stock side:

### Position sizing

- Max single-name weight: 30% (smaller universe than stocks, higher conviction
  per name; the stock side's 8% is too tight for a 10-coin universe).
- Max sector weight (L1 / payments / oracle / L2): 60%. L1 dominates the
  universe, so this is mostly informational.
- Max concurrent positions: 2 in v1. The strategy thesis is concentration
  in the highest-conviction name, not basket exposure.

### Leverage

- Zero. v1 is spot-only. Perpetuals are observed (for funding signals) but
  not traded.

### Stablecoin risk

- Approved settlement currencies: USDC > USDT (USDC has cleaner reserves
  reporting, but USDT has deeper liquidity on most CEXs).
- Daily de-peg check: alert and freeze new entries if any approved stable
  trades outside [0.997, 1.003] for > 1h.
- Cap stablecoin sitting in cash to 100% of portfolio for v1 (we are paper-
  trading; in a live phase, reduce to 50% per stable).

### Hard exclusions (already in universe rules)

- Market cap < 500M USD
- Token age < 12 months
- Anonymous team
- Governance tokens of unaudited protocols (no audited protocols in v0
  universe, so no-op)

### Drawdown gate

- Pause new entries after rolling 30d portfolio drawdown >= -15%.
- Resume only after a 7-day cooldown AND a fresh STRONG signal.

### Time-of-day awareness

- Funding rates reset every 8h on most perps (00:00, 08:00, 16:00 UTC).
- Avoid placing market orders in the 5 minutes around funding resets
  (heightened slippage). v1 paper broker timestamps fills; this becomes a
  live-trading concern only.
- 24/7 markets mean weekend signals are real signals, not artefacts.

### What can go catastrophically wrong (and how we limit it)

- Exchange insolvency (FTX-style). Mitigation: paper-only in v1; multi-exchange
  in live phase; never hold > 30% of portfolio at any one venue.
- Stablecoin collapse (Terra-style). Mitigation: hard-exclude algorithmic
  stables (already done — only USDC/USDT permitted).
- Smart-contract exploit on the underlying chain. Out-of-scope for v0
  universe (BTC, ETH dominate; the rest are L1s with their own consensus,
  not contract-deployment risk).
- Regulatory / exchange-listing event (delisting). Mitigation: the universe
  filter requires both Binance + Coinbase listing; one delisting drops the
  asset, two stops it from being eligible.

## 5. Execution

### Exchange choice (when v1 paper graduates to live in a future phase)

Decision: **Coinbase Advanced Trade API** for live execution.

Reasons:
1. UK/EU regulatory clarity — Senna is UK-based; Coinbase serves the UK
   under the FCA's crypto rules.
2. Documented REST + websocket APIs, good Python ecosystem.
3. Spot-only by default — no accidental leverage.
4. Lower base spreads than Binance UK.
5. The full v0 universe trades there with USD or USDC pairs.

Kraken was the runner-up; equally UK-friendly, slightly worse API ergonomics.
Binance was rejected for UK retail access friction post-2023.

### v1 execution: paper broker only

- Simulated fills against the most recent close.
- Slippage model: 8 bps per side (matches the backtest assumption).
- Transaction cost: 10 bps per side (CEX retail tier).
- Fills are recorded to SQLite via SQLAlchemy.
- No exchange API keys, no private keys, no signed transactions.

### Idempotency

- Every order has a `client_order_key` (SHA1 of `(date, symbol, side, qty)`).
- Paper broker rejects duplicates within a 24h window — same pattern as the
  stock side's broker_base.py.

## 6. Open questions Senna should resolve before live

- DOGE inclusion (currently excluded as memecoin; revisit when ETF lands).
- POL / MATIC ticker migration (which series do we use post-2024?).
- Whether to add TON / NEAR once they clear the 24-month-age hurdle.
- Live-execution venue confirmation (Coinbase Advanced Trade default).
- On-chain provider: stay free (Blockchair) or upgrade to Glassnode at
  the live phase?

## 7. References

- Stock-side architecture: `/Users/senna/stock_research_watchlist/docs/ARCHITECTURE.md`
- Stock-side methodology: `/Users/senna/stock_research_watchlist/docs/METHODOLOGY.md`
- Crypto vs stocks delta: `docs/CRYPTO_VS_STOCKS.md`
- Baseline backtest evidence: `reports/baseline_backtest_2026-05-02.md`
