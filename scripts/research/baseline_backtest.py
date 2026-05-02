"""Baseline backtest of a simplified AGGRESSIVE_ROTATION crypto strategy on 5y of daily bars.

Goal: establish a reference performance footprint BEFORE the autonomous
calibration agents start tweaking thresholds. Without this anchor, we cannot
tell whether their tweaks are helping.

Simplified rules (price-only):
  - Universe: 10 majors from data/historical/symbols.json
  - Each daily bar, rank by 60d momentum (close/close_60d_ago - 1)
  - Apply chase-trap filter: drop any symbol whose 5d return >= 30% (vs 15% for stocks)
  - Hold the top-1 symbol
  - Rotate when rank drops >= 3 spots OR chase-trap on the holding
  - Round-trip cost: 0.36% (10bps txn + 8bps slippage, both sides)

Outputs:
  reports/baseline_backtest_<YYYY-MM-DD>.md
  reports/baseline_backtest_trades.csv
  reports/baseline_backtest_equity.csv
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# Dev fallback: if there is no externally-managed environment, point at the
# repo's local .venv site-packages. Routines should `pip install -e .` first
# and this shim becomes a no-op.
_HERE = Path(__file__).resolve()
_VENV_SP = _HERE.parents[2] / ".venv" / "lib" / "python3.13" / "site-packages"
if _VENV_SP.exists() and str(_VENV_SP) not in sys.path:
    sys.path.insert(0, str(_VENV_SP))

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
HIST = ROOT / "data" / "historical"
REPORTS = ROOT / "reports"
REPORTS.mkdir(parents=True, exist_ok=True)

# Match config defaults.
CHASE_TRAP_5D_PCT = 0.30
MOMENTUM_LOOKBACK_DAYS = 60
ROTATION_RANK_DROP = 3
TXN_COST_BPS = 10
SLIPPAGE_BPS = 8
ROUND_TRIP_COST = (TXN_COST_BPS + SLIPPAGE_BPS) * 2 / 10_000.0  # 0.36%

INITIAL_CAPITAL = 10_000.0


@dataclass
class Trade:
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    symbol: str
    entry_px: float
    exit_px: float
    hold_days: int
    gross_return_pct: float
    net_return_pct: float
    exit_reason: str


def load_data() -> tuple[pd.DataFrame, list[str]]:
    prices = pd.read_parquet(HIST / "prices_daily.parquet")
    prices["date"] = pd.to_datetime(prices["date"])
    symbols = json.loads((HIST / "symbols.json").read_text())
    universe = symbols["universe"]
    prices = prices[prices.symbol.isin(universe)].copy()
    return prices, universe


def build_close_panel(prices: pd.DataFrame) -> pd.DataFrame:
    return (prices.pivot(index="date", columns="symbol", values="close")
                  .sort_index()
                  .ffill(limit=2))


def compute_signals(close: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    momentum = close.pct_change(MOMENTUM_LOOKBACK_DAYS)
    ret_5d = close.pct_change(5)
    rank = momentum.rank(axis=1, ascending=False, method="min")
    return momentum, ret_5d, rank


def run_backtest(close, momentum, ret_5d, rank) -> tuple[pd.DataFrame, list[Trade]]:
    one_leg_cost = ROUND_TRIP_COST / 2.0

    equity = INITIAL_CAPITAL
    position_size: float = 0.0
    holding: str | None = None
    entry_px: float | None = None
    entry_date: pd.Timestamp | None = None
    entry_rank_at_entry: float | None = None

    equity_rows = []
    trades: list[Trade] = []

    valid_dates = close.index[MOMENTUM_LOOKBACK_DAYS:]

    for d in valid_dates:
        if holding is not None:
            cur_px = close.at[d, holding]
            if not pd.isna(cur_px):
                equity = position_size * (cur_px / entry_px)

        today_mom = momentum.loc[d]
        today_5d = ret_5d.loc[d]
        today_rank = rank.loc[d]

        mom_idx = today_mom.dropna().index
        ret5_aligned = today_5d.reindex(mom_idx)
        eligible = mom_idx[ret5_aligned.notna() & (ret5_aligned.abs() < CHASE_TRAP_5D_PCT)]
        eligible_mom = today_mom.loc[eligible].sort_values(ascending=False)
        if len(eligible_mom) == 0:
            equity_rows.append((d, equity, holding, "no eligible"))
            continue
        top_pick = eligible_mom.index[0]

        if holding is None:
            position_size = equity * (1 - one_leg_cost)
            holding = top_pick
            entry_px = float(close.at[d, top_pick])
            entry_date = d
            entry_rank_at_entry = float(today_rank.at[top_pick])
            equity = position_size
            equity_rows.append((d, equity, holding, "OPEN"))
            continue

        cur_5d = today_5d.get(holding, np.nan)
        cur_rank_now = today_rank.get(holding, np.nan)
        chase_trip = (not pd.isna(cur_5d)) and (abs(cur_5d) >= CHASE_TRAP_5D_PCT)
        rank_drift = (not pd.isna(cur_rank_now)) and (cur_rank_now - entry_rank_at_entry >= ROTATION_RANK_DROP)
        rotate_target_better = top_pick != holding and rank_drift

        if chase_trip or rotate_target_better:
            exit_px = float(close.at[d, holding])
            gross = exit_px / entry_px - 1.0
            cash_after_exit = position_size * (1 + gross) * (1 - one_leg_cost)
            net_round_trip = (1 + gross) * (1 - one_leg_cost) ** 2 - 1
            reason = "chase-trap" if chase_trip else "rotation"
            trades.append(Trade(
                entry_date=entry_date, exit_date=d, symbol=holding,
                entry_px=entry_px, exit_px=exit_px,
                hold_days=(d - entry_date).days,
                gross_return_pct=gross * 100,
                net_return_pct=net_round_trip * 100,
                exit_reason=reason,
            ))
            equity = cash_after_exit

            position_size = equity * (1 - one_leg_cost)
            holding = top_pick
            entry_px = float(close.at[d, top_pick])
            entry_date = d
            entry_rank_at_entry = float(today_rank.at[top_pick])
            equity = position_size
            equity_rows.append((d, equity, holding, f"ROTATE ({reason})"))
        else:
            equity_rows.append((d, equity, holding, "HOLD"))

    if holding is not None:
        last_d = valid_dates[-1]
        exit_px = float(close.at[last_d, holding])
        gross = exit_px / entry_px - 1.0
        cash_after_exit = position_size * (1 + gross) * (1 - one_leg_cost)
        net_round_trip = (1 + gross) * (1 - one_leg_cost) ** 2 - 1
        trades.append(Trade(
            entry_date=entry_date, exit_date=last_d, symbol=holding,
            entry_px=entry_px, exit_px=exit_px,
            hold_days=(last_d - entry_date).days,
            gross_return_pct=gross * 100,
            net_return_pct=net_round_trip * 100,
            exit_reason="end-of-data",
        ))
        equity = cash_after_exit
        if equity_rows:
            last_row = equity_rows[-1]
            equity_rows[-1] = (last_row[0], equity, None, "FINAL EXIT")

    eq_df = pd.DataFrame(equity_rows, columns=["date", "equity", "holding", "action"])
    eq_df["date"] = pd.to_datetime(eq_df["date"])
    eq_df = eq_df.set_index("date")
    return eq_df, trades


def compute_benchmarks(prices_all: pd.DataFrame, equity_index: pd.DatetimeIndex) -> dict[str, pd.Series]:
    """Buy-and-hold benchmarks aligned to the strategy's date range."""
    out = {}
    for sym in ("BTC-USD", "ETH-USD", "SPY"):
        s = (prices_all[prices_all.symbol == sym]
             .set_index("date")["close"]
             .reindex(equity_index, method="ffill"))
        if s.dropna().empty:
            continue
        s = s / s.iloc[0] * INITIAL_CAPITAL
        out[sym] = s
    return out


def metrics(equity: pd.Series) -> dict[str, float]:
    eq = equity.dropna()
    if len(eq) < 2:
        return {"cagr_pct": float("nan"), "sharpe": float("nan"),
                "max_dd_pct": float("nan"), "total_return_pct": float("nan")}
    days = (eq.index[-1] - eq.index[0]).days or 1
    years = days / 365.25
    total_return = eq.iloc[-1] / eq.iloc[0] - 1
    cagr = (1 + total_return) ** (1 / years) - 1
    daily_ret = eq.pct_change().dropna()
    # Crypto trades 24/7, so 365 trading days/year (vs 252 for equities).
    sharpe = (daily_ret.mean() / daily_ret.std() * np.sqrt(365)) if daily_ret.std() > 0 else float("nan")
    rolling_max = eq.cummax()
    dd = (eq / rolling_max - 1).min()
    return {
        "cagr_pct": cagr * 100,
        "sharpe": sharpe,
        "max_dd_pct": dd * 100,
        "total_return_pct": total_return * 100,
    }


def per_year_returns(equity: pd.Series) -> pd.DataFrame:
    eq = equity.dropna()
    if eq.empty:
        return pd.DataFrame()
    yearly = eq.resample("YE").last().pct_change() * 100
    yearly.iloc[0] = (eq.resample("YE").last().iloc[0] / INITIAL_CAPITAL - 1) * 100
    yearly = yearly.to_frame("return_pct")
    yearly.index = yearly.index.year
    return yearly


def main() -> None:
    prices, universe = load_data()
    print(f"Loaded {len(prices):,} rows for {prices.symbol.nunique()} universe symbols")

    prices_all = pd.read_parquet(HIST / "prices_daily.parquet")
    prices_all["date"] = pd.to_datetime(prices_all["date"])

    close = build_close_panel(prices)
    momentum, ret_5d, rank = compute_signals(close)
    print(f"Date range: {close.index[0].date()} to {close.index[-1].date()}")
    print(f"Momentum panel: {momentum.shape}, NaN cells: {momentum.isna().sum().sum():,}")

    equity_df, trades = run_backtest(close, momentum, ret_5d, rank)
    print(f"\nStrategy trades: {len(trades)}")
    print(f"Equity end: ${equity_df.equity.iloc[-1]:,.0f} (initial ${INITIAL_CAPITAL:,.0f})")

    bench = compute_benchmarks(prices_all, equity_df.index)
    strat_metrics = metrics(equity_df.equity)
    bench_metrics = {sym: metrics(s) for sym, s in bench.items()}

    strat_yearly = per_year_returns(equity_df.equity)
    bench_yearly = {sym: per_year_returns(s) for sym, s in bench.items()}

    trades_df = pd.DataFrame([t.__dict__ for t in trades])
    if len(trades_df):
        trades_df["entry_date"] = pd.to_datetime(trades_df["entry_date"])
        trades_df["exit_date"] = pd.to_datetime(trades_df["exit_date"])
    win_rate = (trades_df.net_return_pct > 0).mean() * 100 if len(trades_df) else float("nan")
    avg_hold = trades_df.hold_days.mean() if len(trades_df) else float("nan")
    avg_win = trades_df[trades_df.net_return_pct > 0].net_return_pct.mean() if len(trades_df) and (trades_df.net_return_pct > 0).any() else float("nan")
    avg_loss = trades_df[trades_df.net_return_pct <= 0].net_return_pct.mean() if len(trades_df) and (trades_df.net_return_pct <= 0).any() else float("nan")

    symbol_share = trades_df.symbol.value_counts(normalize=True) * 100 if len(trades_df) else pd.Series(dtype=float)

    today = datetime.now(timezone.utc).date().isoformat()
    eq_path = REPORTS / "baseline_backtest_equity.csv"
    tr_path = REPORTS / "baseline_backtest_trades.csv"
    md_path = REPORTS / f"baseline_backtest_{today}.md"

    equity_df.reset_index().to_csv(eq_path, index=False)
    trades_df.to_csv(tr_path, index=False)

    lines: list[str] = []
    lines.append("# Crypto Baseline Backtest — simplified AGGRESSIVE_ROTATION")
    lines.append("")
    lines.append(f"_Generated {datetime.now(timezone.utc).isoformat()}_")
    lines.append("")
    lines.append("Price-only approximation. Captures 60d momentum top-1 selection,")
    lines.append("30% chase-trap filter (5d), rotation on rank-drop or chase-trap exit,")
    lines.append("CEX-retail-tier round-trip cost.")
    lines.append("")
    lines.append("## Setup")
    lines.append("")
    lines.append(f"- Universe: {len(universe)} symbols (`{', '.join(universe)}`)")
    lines.append(f"- Date range: {equity_df.index[0].date()} to {equity_df.index[-1].date()}")
    lines.append(f"- Initial capital: ${INITIAL_CAPITAL:,.0f}")
    lines.append(f"- Chase-trap threshold: {CHASE_TRAP_5D_PCT*100:.0f}% (5d move)")
    lines.append(f"- Momentum lookback: {MOMENTUM_LOOKBACK_DAYS}d")
    lines.append(f"- Rotation trigger: rank drops {ROTATION_RANK_DROP} or more spots, or chase-trap")
    lines.append(f"- Round-trip cost: {ROUND_TRIP_COST*100:.2f}%")
    lines.append("")
    lines.append("## Headline Metrics")
    lines.append("")
    lines.append("| | Strategy | BTC | ETH | SPY |")
    lines.append("|---|---|---|---|---|")

    def fmt(d: dict, k: str) -> str:
        v = d.get(k, float("nan"))
        return f"{v:.2f}" if not pd.isna(v) else "n/a"
    keys = ("total_return_pct", "cagr_pct", "sharpe", "max_dd_pct")
    labels = ("Total return %", "CAGR %", "Sharpe", "Max drawdown %")
    for k, lbl in zip(keys, labels):
        row = f"| {lbl} | {fmt(strat_metrics, k)} "
        for sym in ("BTC-USD", "ETH-USD", "SPY"):
            row += f"| {fmt(bench_metrics.get(sym, {}), k)} "
        row += "|"
        lines.append(row)
    lines.append("")
    lines.append("## Trade Stats")
    lines.append("")
    lines.append(f"- Total trades: {len(trades_df)}")
    lines.append(f"- Win rate: {win_rate:.1f}%")
    lines.append(f"- Avg hold: {avg_hold:.1f} days")
    lines.append(f"- Avg winning trade: {avg_win:.2f}%")
    lines.append(f"- Avg losing trade: {avg_loss:.2f}%")
    lines.append("")
    if len(trades_df):
        reasons = trades_df.exit_reason.value_counts()
        lines.append("Exit reason breakdown:")
        for r, c in reasons.items():
            lines.append(f"- {r}: {c}")
        lines.append("")
    lines.append("## Per-Year Returns (%)")
    lines.append("")
    lines.append("| Year | Strategy | BTC | ETH | SPY |")
    lines.append("|---|---|---|---|---|")
    for y in strat_yearly.index:
        row = f"| {y} | {strat_yearly.loc[y, 'return_pct']:.2f} "
        for sym in ("BTC-USD", "ETH-USD", "SPY"):
            df = bench_yearly.get(sym, pd.DataFrame())
            if y in df.index:
                row += f"| {df.loc[y, 'return_pct']:.2f} "
            else:
                row += "| n/a "
        row += "|"
        lines.append(row)
    lines.append("")
    lines.append("## Symbol Exposure (% of trades)")
    lines.append("")
    for sym, pct in symbol_share.head(10).items():
        lines.append(f"- {sym}: {pct:.1f}%")
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- Crypto trades 24/7, so the Sharpe denominator uses sqrt(365), not sqrt(252).")
    lines.append("- The chase-trap threshold of 30% (5d) is the calibration baseline; the daily")
    lines.append("  calibration agent should sweep [20, 25, 30, 35, 40] and report which dominates.")
    lines.append("- Survivorship bias: MATIC, AVAX, SOL came online during this 5y window so")
    lines.append("  they are absent from the eligible set in the early period.")
    lines.append("- No funding-rate awareness yet; that is on the calibration agent's TODO list.")
    lines.append("")
    lines.append("## Files")
    lines.append("")
    lines.append(f"- `reports/baseline_backtest_{today}.md` (this file)")
    lines.append("- `reports/baseline_backtest_trades.csv`")
    lines.append("- `reports/baseline_backtest_equity.csv`")

    md_path.write_text("\n".join(lines))
    print(f"\nWrote {md_path}")
    print(f"Wrote {tr_path}")
    print(f"Wrote {eq_path}")


if __name__ == "__main__":
    main()
