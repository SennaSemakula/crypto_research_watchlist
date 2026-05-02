# START HERE — handoff for the next Claude Code session

This file tells the next agent (and you, Senna) what was built, what works,
and what the user must do first.

## Repo

- Local: `/Users/senna/crypto_research_watchlist`
- Remote: https://github.com/SennaSemakula/crypto_research_watchlist (public)
- Branch: `main`. First commit pushed.

## What works today

- **Skeleton + config**: `pyproject.toml`, `config.yml`, `.gitignore`,
  `README.md`, `docs/CRYPTO_VS_STOCKS.md`.
- **Gate logic**: `src/crypto_research_watchlist/autotrader/aggressive.py`
  ports the chase-trap + rotation gate from the stock repo, tuned for crypto:
    - chase_trap_5d_pct = 30% (vs 15% for stocks)
    - chase_trap_1d_pct = 18% (added; single-session rip protection)
    - momentum_lookback_days = 60
    - No earnings logic (crypto has none).
    - `funding_signal()` is a placeholder for ccxt wiring (TODO).
- **5y daily backfill**: `data/historical/prices_daily.parquet` covers all
  10 universe symbols + SPY (cross-asset) + ^VIX (macro). 20,415 rows,
  0.64 MB on disk, committed to repo so routines do not need network.
- **Baseline backtest**: `reports/baseline_backtest_2026-05-02.md` records:
    - Strategy: -56.15% total / -15.65% CAGR / 0.20 Sharpe / -89.75% max DD
    - BTC buy-and-hold:  +125.63% / +18.29% / 0.58 Sharpe / -76.63% max DD
    - ETH buy-and-hold:  +15.98%  / +3.11%  / 0.40 Sharpe / -79.35% max DD
    - SPY buy-and-hold:  +80.28%  / +12.94% / 0.79 Sharpe / -24.50% max DD
  The naive top-1 momentum rotation underperforms BTC by ~34 CAGR points.
  This is the calibration anchor; the daily routines should beat it.
- **Tests**: 9 smoke tests, all passing (`tests/test_smoke.py`).
- **Calibration primitives**: `scripts/research/lib_calibration.py` provides
  threshold sweeps, vol regime buckets, BTC correlation, sector summaries,
  and a `funding_rate_buckets` placeholder.

## What needs you, first thing on return

### 1. Install the Claude GitHub App on the new repo (CRITICAL)

Without this, every routine that tries to push will fail with
`auto_disabled_repo_access`, just like happened with the stock repo.

Open: https://github.com/apps/claude/installations/new
Select: only the `SennaSemakula/crypto_research_watchlist` repo.
Verify: a green tick on https://github.com/SennaSemakula/crypto_research_watchlist/settings/installations

### 2. Install the four routines

The routines could not be installed from the bootstrap session because
neither `RemoteTrigger` nor `mcp__scheduled-tasks__create_scheduled_task`
were granted to that session. The specs are committed at:

- `routines/kickoff.routine.yml` — fires once, ~2min after install.
- `routines/daily_calibration.routine.yml` — `0 3 * * *` UTC daily.
- `routines/intraday_scan.routine.yml` — `0 * * * *` (hourly, 24/7).
- `routines/asset_rotation.routine.yml` — `0 */4 * * *` (every 4h).

For each, generate a fresh lowercase v4 UUID for `events[].data.uuid`
and create via `RemoteTrigger`:

```python
RemoteTrigger.create(
    environment_id="env_01PkjZM61nLK8yvWynh7pdWG",
    model="claude-sonnet-4-6",
    sources=[{"git_repository": {"url": "https://github.com/SennaSemakula/crypto_research_watchlist"}}],
    allowed_tools=["Bash","Read","Write","Edit","Glob","Grep"],
    cron_expression=<from yml>,           # omit for kickoff
    fire_at=<for kickoff>,
    events=[{"data": {"uuid": "<fresh-v4>"}}],
    prompt=<from yml>,
)
```

### 3. (Optional) Re-run the backfill

The committed parquet is from 2026-05-02 12:06 UTC. If you want fresher
data before the first routine fires:

```bash
cd ~/crypto_research_watchlist
source .venv/bin/activate
python scripts/research/backfill_history.py
git add data/historical/ && git commit -m "refresh: backfill" && git push
```

## What did not get done in the bootstrap session

- **Routines were not actually installed** (the tools were denied). The
  specs are in `routines/` ready to paste. ETA after you install: ~5 min.
- **Funding-rate wiring** is a documented TODO. The Wednesday calibration
  routine is responsible for landing it.
- **Hourly aggressive runner**: not started. The intra-day scan only
  classifies; it does not "trade". By design.

## Hard rules baked in (every routine prompt)

- NO Telegram, NO live trades, NO paid APIs.
- yfinance + ccxt public endpoints only.
- Direct push to `main`. No PRs.
- If `src/` touched, pytest must pass first.
- A `.agent_panic` file at repo root halts every routine.

## Local dev recipe

```bash
cd ~/crypto_research_watchlist
source .venv/bin/activate
pip install -e .
pytest -q                              # should be 9/9
python scripts/research/backfill_history.py    # idempotent
python scripts/research/baseline_backtest.py   # writes new dated md
```

## Calibration honesty

The baseline strategy LOSES money over 5 years (-56%). This is correct
and expected: a naive single-name top-1 momentum rotation through 10
correlated cryptos eats round-trip costs and gets whipsawed by the chase
trap on the way up. The daily calibration routine's job is to find a
configuration that beats BTC buy-and-hold (+125%) on a risk-adjusted
basis. If after 4 weeks of calibration the strategy still trails BTC's
Sharpe, the right answer is to retire the rotation logic and use this
system purely for STRONG/WATCH/AVOID decision support, not allocation.
