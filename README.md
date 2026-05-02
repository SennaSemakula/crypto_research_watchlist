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
config.example.yml                  example to copy from
.env.example                        environment overrides example
run                                 wrapper script: venv + pipeline dispatch
src/crypto_research_watchlist/
  config.py                         AppConfig + EnvSettings
  db.py                             SQLAlchemy engine / session
  models.py                         ORM: SignalRecord, CandidateRecord, PaperOrder...
  universe.py                       UniverseEntry + filter
  risk.py                           RiskVerdict + classify()
  candidates.py                     Candidate + build / rank
  pipeline.py                       run_once() end-to-end
  cli.py                            Typer CLI: run / candidates / paper-status
  autotrader/
    aggressive.py                   rotation gate (chase-trap)
    config.py                       CryptoConfig (Pydantic)
    paper_broker.py                 in-process paper broker (idempotent)
    runner.py                       converts candidates into paper orders
  data/
    ccxt_provider.py                CCXT spot + perp adapter
    funding_provider.py             funding-rate provider
    onchain_provider.py             on-chain stub
  signals/
    technical.py                    RSI / MACD / EMA cross / volume spike
    funding_rate.py                 perp funding signal
    open_interest.py                OI delta + price delta
    onchain.py                      active addresses + exchange netflow
    cross_asset.py                  ETH/BTC, relative strength vs BTC
  notifiers/
    telegram.py                     off by default
scripts/research/
  backfill_history.py               yfinance -> data/historical/prices_daily.parquet
  baseline_backtest.py              60d-momentum + chase-trap, 5y of daily bars
  lib_calibration.py                reusable calibration primitives
data/historical/                    parquet bars, committed to repo for agent use
research_log/                       daily calibration evidence (one md per day)
intraday_log/                       hourly classification evidence (one md per run)
research/assets/                    per-symbol deep-dive notes
reports/                            backtest outputs + watchlist md/json
docs/RESEARCH.md                    universe + sources + signals + risk research
docs/PLAN.md                        phased build plan
docs/SIGNALS.md                     per-evaluator reference
docs/CRYPTO_VS_STOCKS.md            what is and is not portable from the stock repo
```

## CLI

```
./run                       run pipeline once -> reports/watchlist_<date>.md
./run -- candidates         show last run's ranking
./run -- paper-status       show paper portfolio cash + positions
./run -- init-db            create / migrate the SQLite schema (idempotent)
```

## Running locally

The `./run` wrapper handles venv + dependency install + DB init on first
invocation. After cloning:

```bash
./run                                  # pipeline run; writes reports/watchlist_<date>.md
./run -- paper-status                  # show paper portfolio
./run -- candidates                    # last run's ranking from the DB

# Manual flow if you prefer:
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q                              # 51 tests
python scripts/research/backfill_history.py    # refresh yfinance daily bars
python scripts/research/baseline_backtest.py   # baseline strategy report
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
