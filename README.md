# Crypto Research Watchlist

Local, decision-support research watchlist for the top-cap cryptocurrencies.
Sister system to [stock_research_watchlist](https://github.com/SennaSemakula/stock_research_watchlist),
adapted for the 24/7 crypto market.

## Scope

- 10 majors only: BTC, ETH, SOL, BNB, XRP, ADA, AVAX, DOT, LINK, MATIC.
- No stablecoins, no meme coins, no sub-$1B caps.
- Decisions logged. Markdown only. No live trades. No Telegram. No paid APIs.

## What it is

- Aggressive-rotation watchlist: pick the single best name by 60d momentum subject to
  a chase-trap filter (default 30% over 5 days for crypto vs 15% for equities).
- Hourly intra-day signal classification (STRONG / WATCH / AVOID) logged to `intraday_log/`.
- Per-asset deep-dive notes in `research/assets/<SYMBOL>.md`.
- Daily calibration evidence in `research_log/`.

## What it is NOT

- Not a broker. Not connected to any exchange or wallet.
- Not financial advice. The output is a markdown watchlist for a human to read.
- Not a high-frequency system. Daily bars + hourly signal classification only.

## Layout

```
config.yml                          universe, gates, sizing
src/crypto_research_watchlist/
  autotrader/aggressive.py          rotation gate logic
  autotrader/config.py              Pydantic config model
  signals/                          (placeholder for per-signal modules)
scripts/research/
  backfill_history.py               yfinance -> data/historical/prices_daily.parquet
  baseline_backtest.py              60d-momentum + chase-trap, 5y of daily bars
  lib_calibration.py                reusable calibration primitives
data/historical/                    parquet bars, committed to repo for agent use
research_log/                       daily calibration evidence (one md per day)
intraday_log/                       hourly classification evidence (one md per run)
research/assets/                    per-symbol deep-dive notes
reports/                            backtest outputs
docs/CRYPTO_VS_STOCKS.md            what is and is not portable from the stock repo
```

## Running locally

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
python scripts/research/backfill_history.py
python scripts/research/baseline_backtest.py
pytest -q
```

## Hard rules (every routine, every contributor)

- No live trades. No Telegram. No paid APIs.
- Direct push to `main`; no PR ceremony for routine output.
- If `src/` was touched and tests fail, do not push.
- A `.agent_panic` file at the repo root halts every routine.

## Calibration cadence

- 03:00 UTC daily — calibration agent runs threshold sweeps + writes a research_log entry.
- Hourly, 24/7 — intra-day signal scan classifies each universe member STRONG / WATCH / AVOID.
- Every 4 hours — per-asset rotation refreshes 2 asset notes per run.

See `docs/CRYPTO_VS_STOCKS.md` for which stock-repo concepts ported and which did not.
