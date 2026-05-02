# Decision engine

How the crypto research watchlist turns ranked candidates into auditable
decisions. Two engines run side by side, each producing one decision per
symbol per run, persisted to the SQLite database for back-evaluation.

Date: 2026-05-02. Mirrors the stock sibling's architecture; crypto-tuned
defaults documented in-line. Paper-only and shadow-only in v1.

## 2026-05 score-scale migration

Candidate `score` migrated from raw `[-1, +1]` aggregated signal strength
to a `[0, 100]` weighted feature aggregation:
- momentum (0.35), volatility_regime (0.20), rel_strength_vs_btc (0.20),
  funding_signal (0.10), drawdown_penalty (0.15) — see `src/scoring.py`.
- Action thresholds in `cfg.crypto.scoring.thresholds`: STRONG >= 72,
  WATCH >= 55, AVOID < 40 (otherwise WATCH).
- Per-feature breakdown is persisted on `Candidate.extras["features"]`.
- Legacy callers using `aggregate_strength=` and stub candidates with
  `[-1, +1]` scores still work via auto-rescaling shims in passive,
  aggressive, telegram, and risk.

## Where decisions come from

```
pipeline.run_once
  -> ranked Candidate objects (signals + risk verdict)
       -> autotrader.passive.run_once_passive
            -> PassiveReport (one decision per candidate)
       -> autotrader.aggressive.run_once_aggressive
            -> AggressiveReport
       -> autotrader.learning_summary.build_weekly_summary
            -> WeeklyLearningSummary (digest of past week)
```

Each report flows two places: into the SQLAlchemy decision tables for
audit and back-evaluation, and into a Telegram notifier for operator
awareness.

## Passive accumulation engine

### Goal

Slowly accumulate quality crypto names by buying small fixed-USD tranches
when they go on sale. Crypto is fatter-tailed than equities, so the dip
threshold is wider than the stock side's -5%.

### Inputs

`PassiveContext` carries:
- paper-broker cash (`cash_usd`) and positions (`positions_by_symbol_usd`)
- week-to-date buy totals (per-symbol and aggregate)
- 30d portfolio drawdown proxy (BTC's drawdown from 30d high)
- stablecoin de-peg flag (sniffed from `signals/cross_asset.py` details)
- per-symbol price extras: `last`, `high30`, `atr14`, `p1d`/`p7d`/`p30d`

### Gates (in order)

1. **Portfolio gates first.** If stablecoin de-peg flag set, or 30d
   drawdown <= -15%: every decision is `BLOCK_BUY_RISK_EVENT`.
2. **Universe.** Symbol must be in `cfg.universe.symbols`.
3. **Score floor.** `score >= cfg.passive.min_accumulation_score` (default
   50 on the 0-100 scale post 2026-05 migration) AND `action != "AVOID"`.
4. **Dip qualifier.** `last / high30 - 1 <= -dip_threshold_pct` (default
   -8%). Without dip data, fall through to `WAIT_FOR_BETTER_PRICE` rather
   than auto-buying on missing inputs.
5. **Weekly caps.** Per-symbol cap (default $300/wk) and total cap
   (default $1500/wk). Cash on hand is the third clamp.
6. **Sizing.** First tranche $100, add tranche $100 (when symbol is
   already in `positions_by_symbol_usd`). Sized to
   `min(target, per_sym_remaining, total_remaining, cash_remaining)`.
7. **Shadow rebrand.** If `cfg.passive.shadow_mode=True` (default),
   relabel `AUTO_BUY_FIRST_TRANCHE` and `AUTO_ADD_TRANCHE` to
   `AUTO_BUY_SHADOW`, preserving the original action in the reasons list
   for downstream analytics.

### Actions emitted

- `AUTO_BUY_FIRST_TRANCHE`: live first buy (live mode only).
- `AUTO_ADD_TRANCHE`: live add to existing position.
- `AUTO_BUY_SHADOW`: would-be buy in shadow mode (no order placed).
- `WAIT_FOR_BETTER_PRICE`: dip not deep enough, or weekly cap exhausted.
- `BLOCK_BUY_RISK_EVENT`: portfolio gate tripped (de-peg, drawdown).
- `HOLD`: nothing to do (rare in v1).
- `SELL_REVIEW_ONLY`: held position warrants human review (reserved for
  future expansion; no auto-sell).
- `DO_NOT_BUY`: outside universe, AVOID, or score below floor.

### Calibration knobs (config.yml -> passive)

| knob                              | default | notes                                  |
|-----------------------------------|---------|----------------------------------------|
| `shadow_mode`                     | true    | default true. NEVER live in v1.        |
| `first_tranche_usd`               | 100     | first buy of a name                    |
| `add_tranche_usd`                 | 100     | additional buy of an existing name     |
| `weekly_cap_per_symbol_usd`       | 300     | sweep 200-500 in calibration           |
| `weekly_cap_total_usd`            | 1500    | scales with portfolio                  |
| `dip_threshold_from_30d_high_pct` | 0.08    | sweep 0.05-0.12                        |
| `drawdown_gate_pct`               | 0.15    | sweep 0.10-0.25                        |
| `min_accumulation_score`          | 50.0    | 0-100 scale; aligned with WATCH thr     |
| `high_conviction_score_threshold` | 60.0    | 0-100 scale; permits add-tranche bonus |

## Aggressive rotation engine

### Goal

Concentrated, high-conviction rotation: hold the single best opportunity,
swap quickly when something better appears, refuse to chase parabolic moves.

### Inputs

`AggressiveContext` carries:
- ranked candidates (with extras["px"] return panel)
- the currently held symbol (operator-supplied; v1 has no portfolio
  tracker for the rotation engine)
- holding's rank at entry (for rank-drop comparisons)
- last chase-trap timestamps per symbol (for cooldown)

### Gates (in order, per candidate)

1. **Cooldown.** If this symbol was chase-trap'd within `cooldown_days`
   (default 3), emit `COOLDOWN_HOLD`.
2. **Chase-trap.** `is_chase_trap` checks `|r5d| >= 30%` OR `|r1d| >= 18%`.
   Triggered -> `DO_NOT_CHASE`.
3. **AVOID passthrough.** If pipeline labelled the candidate AVOID, emit
   `AVOID`.
4. **Rotation.** When a holding exists and this candidate is a different
   symbol, rotate when ANY of:
   - holding itself in chase-trap (forced exit)
   - score gap (challenger - holder, on 0-100 scale) >= `rotation_score_gap`
     (default 15)
   - holder's rank slipped >= `rotation_rank_drop` (default 3) since entry
   The rotation is only logged for the top-ranked candidate to avoid emitting
   duplicate rotates.
5. **Buy.** When no holding and this is the top STRONG candidate, emit `BUY`.
6. **Otherwise** `HOLD`.

### Actions emitted

- `BUY`: top STRONG candidate when not holding anything.
- `ROTATE`: exit current and enter target.
- `HOLD`: no rotation trigger, no chase, no buy criteria met.
- `DO_NOT_CHASE`: chase-trap fired.
- `COOLDOWN_HOLD`: within post-chase cooldown.
- `AVOID`: pipeline labelled it AVOID.
- `NO_CANDIDATES`: empty input.

### Calibration knobs (config.yml -> aggressive)

| knob                       | default | sweep range            |
|----------------------------|---------|------------------------|
| `chase_trap_5d_pct`        | 0.30    | 0.20-0.40              |
| `chase_trap_1d_pct`        | 0.18    | 0.10-0.25              |
| `momentum_lookback_days`   | 60      | 20-120                 |
| `rotation_rank_drop`       | 3       | 2-5                    |
| `rotation_score_gap`       | 15.0    | 10-20                  |
| `cooldown_days`            | 3       | 1-7                    |

## Supervisor

`autotrader/order_supervisor.reconcile()` reads paper portfolio state and
recent decisions, then flags two kinds of drift:

1. Non-shadow buy decisions logged in the last 48h with no matching paper
   position. (In v1 this should not fire because shadow_mode=true is the
   default; the check is here so live mode flipping flips on cleanly.)
2. Open paper positions with no decision audit trail in the lookback window.

Output: `SupervisorReport` with `mismatches`, `warnings`. The Telegram
formatter emits the message only when warnings are present.

## Learning summary

`autotrader/learning_summary.build_weekly_summary()` aggregates the past N
weeks (default 1):

- `passive_action_counts`, `aggressive_action_counts`: counters per action.
- `hit_rate_pct`: of WATCH+ candidates 7-14 days ago, what percent moved
  positively over the next 7 days. Computed against the parquet historical
  OHLCV so it works fully offline.
- Score distribution shift: this week vs prior week mean.
- Top realised moves: prior-week candidates ranked by realised 7d return.

The summary persists to the `learning_summaries` table and writes a
markdown report to `reports/learning_summary_<date>.md`. The Sunday
GitHub Action also Telegrams the digest.

## Calibration

`scripts/research/calibration_sweep.py` runs a 3-axis grid search:

- chase-trap 5d threshold: 20-40% in 5pt steps
- rotation score gap: 10-20 in 5pt steps (tag-only in this sim)
- dip threshold from 30d high: 5-12% in 1pt steps

For each grid point it runs a top-1 momentum simulation across the
parquet history with the chase-trap and dip filters applied, and reports
forward-7d hit-rate, mean, median. The best row (max win-rate, then max
mean) is recommended. Output: `data/historical/calibration_<date>.json`.

The expected operator workflow: every Monday morning, eyeball the latest
calibration JSON, decide whether to nudge a threshold, edit `config.yml`,
commit. Manual loop, deliberate.

## Why this shape

Two engines, three notifiers, one supervisor: same as the stock side.
Crypto-specific differences:

- No earnings logic (crypto has no earnings).
- No market-hours gate (24/7 markets).
- No FX layer (USD throughout).
- Wider chase-trap and dip thresholds (fatter tails).
- Stablecoin de-peg as a hard portfolio block (no equity equivalent).
- Sharpe denominator uses sqrt(365), not sqrt(252) (24/7 trading days).

All decisions are paper-only / shadow-only in v1. The shadow-mode default
exists so the operator can audit a live cadence (logs, Telegrams, learning
summary) before committing to live execution.
