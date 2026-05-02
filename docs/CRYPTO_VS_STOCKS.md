# Crypto vs. Stocks: what ported, what did not

This doc tracks the deltas between `stock_research_watchlist` and this repo.
Read it before changing a threshold without checking the parallel knob in
the stock repo.

## What is the same

- Project layout: `src/<pkg>/autotrader/`, `scripts/research/`, `data/historical/`,
  `research_log/`, `intraday_log/`, `research/assets/`, `reports/`, `docs/`.
- Calibration cadence: daily 03:00 UTC + hourly intra-day + 4-hourly per-asset rotation.
- Decision schema: `Decision(action, reason)` with action in {STRONG, WATCH, AVOID}.
- Rotation gate model: chase-trap + 60d momentum rank + rank-drop rotation.
- Output discipline: markdown only, no live trades, no Telegram, no paid APIs.
- The lib_calibration primitives: threshold sweep, regime buckets, sector summary.

## What is different

| Concept                  | Stocks                             | Crypto                                              |
| ------------------------ | ---------------------------------- | --------------------------------------------------- |
| Market hours             | 09:30-16:00 ET, weekdays           | 24/7                                                |
| Universe size            | 23                                 | 10                                                  |
| Chase-trap (5d)          | 15%                                | 30%                                                 |
| Chase-trap (1d)          | n/a                                | 18% (added; single-session rips are a crypto thing) |
| Sharpe annualisation     | sqrt(252)                          | sqrt(365)                                           |
| Round-trip cost          | 0.16% (8bps + 8bps)                | 0.36% (10bps + 8bps each side, CEX retail tier)     |
| Sector model             | SPDR Select Sector ETFs (XLK, etc) | Crypto-native categories (L1, payments, oracle, L2) |
| Earnings logic           | Pre-earnings blackout + RSI gate   | None — crypto has no earnings                       |
| Macro regime markers     | VIX, 10Y yield, DXY, oil, gold     | VIX (cross-asset only)                              |
| Cross-asset benchmark    | n/a (asset class is the universe)  | SPY (sanity check that crypto is not just beta)     |
| Native benchmarks        | SPY, QQQ, IWM                      | BTC-USD, ETH-USD                                    |
| Data source              | yfinance + SEC Edgar               | yfinance + ccxt public endpoints                    |
| Funding-rate awareness   | n/a                                | Placeholder — Wednesday calibration owns wiring it  |
| Position concentration   | 65/35 two-name split allowed       | Single name (universe is correlated enough)         |
| Single-name max weight   | 8%                                 | 30% (smaller universe, higher conviction)           |

## What did not translate at all

- **Earnings forecasting** (`earnings_prediction/` in the stock repo). Crypto has
  no quarterly earnings. The closest analogue is on-chain unlocks / token
  emissions, which is a different discipline.
- **Insider transactions / short-interest signals**. No SEC equivalent for
  layer-1 issuers. Whale-wallet activity is the rough analogue but is far
  noisier; not in scope for v0.1.
- **Analyst price targets**. Crypto has no buy-side coverage in any consistent
  format; CoinDesk-style "fair value" pieces are too sparse to gate on.
- **10-Q anomaly detection**. No filings.

## What is new (no stock equivalent)

- **Funding-rate awareness** (placeholder; Wednesday calibration). Perp futures
  funding rate is a crypto-specific positioning gauge with no equity analogue.
- **Correlation-with-BTC regime** (Friday calibration). When alts decouple from
  BTC, rotation alpha is highest. When they all follow BTC, rotation is just
  noise on a single beta exposure.
- **24/7 cadence**. The intra-day routine fires every hour, every day, including
  weekends — there is no "market closed" branch.

## Why the chase-trap moved from 15% to 30%

The 15% threshold for stocks was chosen because a 15% 5-day move in a $50B+
equity almost always means M&A, earnings shock, or a regulatory event — the
kind of thing where chasing the move usually loses. In crypto, a 15% 5-day
move on BTC happens routinely in normal regimes; it does not signal a chase
trap, it signals "Tuesday".

The starting threshold of 30% is a guess based on 5y of daily ranges. The
Monday calibration sweeps 20/25/30/35/40 each week and the agent should
adjust if the data argues a different value dominates.

## Why "no live trades" is non-negotiable

The stock repo enforces this and so does this one. Routines write markdown,
nothing else. Any change that would call an exchange API, sign a transaction,
or hold a private key is outside this system's scope.
