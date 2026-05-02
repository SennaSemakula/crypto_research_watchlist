# PLAN

Phased build plan for the crypto sibling. Each phase ends with a green
test run and a commit.

Date: 2026-05-02. Author: Claude Code (Senna delegated).

The repo already has a working skeleton: `autotrader/aggressive.py` (gate
logic), `autotrader/config.py` (Pydantic config), 5y daily backfill, baseline
backtest, 9 smoke tests passing. This plan layers on the missing pieces from
the stock side: SQLite persistence, signals modules, paper broker, pipeline,
notifier, conftest hardening.

## Phase A — scaffolding completion (DONE)

Already in repo:
- pyproject.toml, config.yml, README.md, .gitignore
- src/crypto_research_watchlist/{autotrader,signals,__init__.py}
- 5y backfill at data/historical/prices_daily.parquet
- baseline backtest reproduces a known-bad strategy as a calibration anchor
- 9 smoke tests

Still missing in Phase A (this session):
- `src/crypto_research_watchlist/db.py` (SQLAlchemy engine + session)
- `src/crypto_research_watchlist/models.py` (ORM models for signals,
  candidates, paper-broker positions/orders)
- `src/crypto_research_watchlist/config.py` (top-level AppConfig + EnvSettings)
- `src/crypto_research_watchlist/universe.py` (UniverseEntry + filter)
- `tests/conftest.py` (env scrub fixture; copy from stock side)
- `.env.example`, `config.example.yml`
- Acceptance: `pytest -q` green; new modules covered.

## Phase B — signals (this session)

Files:
- `src/crypto_research_watchlist/signals/__init__.py` (SignalResult, SignalContext, evaluate_all)
- `src/crypto_research_watchlist/signals/technical.py` (RSI / MACD / EMA cross / volume spike — same math as stock side)
- `src/crypto_research_watchlist/signals/funding_rate.py` (interface + neutral fallback when None)
- `src/crypto_research_watchlist/signals/open_interest.py` (interface + neutral fallback)
- `src/crypto_research_watchlist/signals/onchain.py` (interface + neutral fallback)
- `src/crypto_research_watchlist/signals/cross_asset.py` (BTC dominance / ETH-BTC ratio from price panel)

Tests:
- `tests/test_signals_technical.py` — synthetic OHLCV → expected RSI/MACD/cross labels
- `tests/test_signals_funding.py` — None input returns neutral; threshold trips return correct direction
- `tests/test_signals_orchestrator.py` — evaluate_all returns one entry per registered evaluator

Acceptance: each evaluator is a pure function over (SignalContext) → SignalResult,
no network calls. SignalResult.strength bounded in [-1, +1].

## Phase C — risk + candidates + paper broker (this session)

Files:
- `src/crypto_research_watchlist/risk.py` (RiskVerdict, classify())
- `src/crypto_research_watchlist/candidates.py` (Candidate dataclass; build_candidates(prices, signals, cfg) -> list[Candidate])
- `src/crypto_research_watchlist/autotrader/paper_broker.py` (PaperBroker implementing the same broker_base contract; fills against last close + slippage)
- `src/crypto_research_watchlist/autotrader/runner.py` (entry point: load config, fetch candidates, persist, optionally place paper orders)

Tests:
- `tests/test_risk.py`
- `tests/test_paper_broker.py` — buy/sell flow, idempotency by client_order_key, slippage
- `tests/test_candidates.py` — top-N selection respects risk gates

## Phase D — pipeline + notifier (this session if time)

Files:
- `src/crypto_research_watchlist/pipeline.py` (RunResult; run_once(cfg, env, engine))
- `src/crypto_research_watchlist/notifiers/__init__.py`
- `src/crypto_research_watchlist/notifiers/base.py` (NotificationOutcome)
- `src/crypto_research_watchlist/notifiers/telegram.py` (mirror of stock side; off by default)
- `src/crypto_research_watchlist/cli.py` (Typer app: run, init-db, candidates, paper-status)

Tests:
- `tests/test_pipeline.py` — run_once on sample data produces a non-empty RunResult
- `tests/test_notifiers.py` — disabled by default; HTML escaping correct

## Phase B/C/D status update (2026-05-02)

Operational architecture brought to parity with the stock sibling.

**Decision engine — DONE**
- `autotrader/passive.py`: passive accumulation engine. PassiveAction enum,
  PassiveDecision, PassiveReport, evaluate(), run_once_passive(). Crypto-tuned
  gates: dip threshold from 30d high (default -8%), weekly cap per symbol /
  total, drawdown gate, stablecoin de-peg block. Shadow-only in v1.
- `autotrader/aggressive.py`: rotation engine extended. Existing classify /
  rotate_decision primitives preserved; added AggressiveAction, AggressiveDecision,
  AggressiveReport, evaluate_aggressive(), run_once_aggressive(). Chase-trap
  gate (5d > 30%, 1d > 18%), rank-drop and score-gap rotation, post-trap cooldown.
- `autotrader/order_supervisor.py`: paper-broker reconciliation. Detects
  decisions without positions and positions without decision audit trail.
- `autotrader/learning_summary.py`: weekly digest. Decision counts, hit-rate
  back-eval against parquet, score-distribution shift, top realised moves.

**Notifiers — DONE**
- `notifiers/passive_notifier.py`: quiet-by-default Telegram render.
- `notifiers/aggressive_notifier.py`: long-form Telegram render with ATR
  buy / target / stop zones reused from the existing telegram.py renderer.

**Persistence — DONE**
- `models.py` adds passive_decisions, aggressive_decisions, learning_summaries.

**CLI — DONE**
- `passive`, `aggressive`, `supervise`, `learning-summary` subcommands all
  with optional `--send-telegram`.

**GH Actions — DONE**
- `.github/workflows/passive-daily.yml` (14:00 UTC daily)
- `.github/workflows/aggressive-overnight.yml` (22:00 UTC weekdays)
- `.github/workflows/learning-summary.yml` (Sunday 18:00 UTC)

**Calibration — DONE**
- `scripts/research/calibration_sweep.py`: grid sweeps chase-trap, rotation
  gap, dip threshold over the parquet history. Writes JSON to
  `data/historical/calibration_<date>.json`.

**Tests — DONE**
- 47 new tests added (98 total): test_passive, test_aggressive,
  test_supervisor, test_learning_summary, test_notifier_passive,
  test_notifier_aggressive, test_calibration_sweep.

## Phase E — backfill + walk-forward calibration (next session)

Already partly done: 5y daily OHLCV is present. Still TODO:
- Hourly OHLCV via CCXT for the last 90 days (intraday)
- Funding rate history backfill via CCXT (Binance) for the last 12 months
- Walk-forward sweep harness in `scripts/research/walk_forward.py`

Acceptance: report writes to `reports/walk_forward_<date>.md` with
out-of-sample metrics by parameter.

## Phase F — live readiness (FUTURE; not this session)

- `src/crypto_research_watchlist/autotrader/brokers/coinbase_advanced.py`
  implementing the same broker contract.
- Kill switch (file at repo root, like the stock side's `.agent_panic`).
- Reconcile: every cold-start fetches positions from the broker and replays
  the journal.
- DO NOT ship live trading until Senna signs off.

## What this session targets

Phases A through D, end-to-end. Stops short of E and F.

## Style / discipline

Carried verbatim from stock side:
- Pure functions where possible; ORM at the edges only.
- All evaluators take a context object; never reach into globals.
- Tests offline. Mock CCXT. Mock all HTTP.
- Telegram notifier ships disabled by default; enable via .env.
- Conftest scrubs every sensitive env var before each test (the stock side
  was bitten by `TELEGRAM_BOT_TOKEN` leak from a real .env).
- No em dashes anywhere. No ampersands in user-facing copy. No AI co-authorship
  in commits.
