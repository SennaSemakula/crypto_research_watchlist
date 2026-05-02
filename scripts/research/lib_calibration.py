"""Reusable calibration primitives for the crypto daily improvement agent.

These functions take the backfilled `data/historical/prices_daily.parquet`
and return calibration evidence: threshold sweeps, distribution comparisons,
regression coefficients, regime bucket stats.

Design parallel to the stock repo's lib_calibration.py with three changes:
  - No earnings-drift function (crypto has no earnings).
  - Adds `funding_rate_buckets()` — placeholder, marked TODO.
  - Sharpe denominator uses sqrt(365), not sqrt(252).

All thresholds and constants here mirror `src/crypto_research_watchlist/
autotrader/config.py` defaults at the time of writing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Dev fallback: prefer repo-local .venv when invoked outside it.
_HERE = Path(__file__).resolve()
_VENV_SP = _HERE.parents[2] / ".venv" / "lib" / "python3.13" / "site-packages"
if _VENV_SP.exists() and str(_VENV_SP) not in sys.path:
    sys.path.insert(0, str(_VENV_SP))

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
HIST = ROOT / "data" / "historical"

# Mirror of current production knobs (config.py defaults as of 2026-05-02).
CURRENT_CHASE_TRAP_5D_PCT = 30.0
CURRENT_CHASE_TRAP_1D_PCT = 18.0
CURRENT_MOMENTUM_LOOKBACK_DAYS = 60
CURRENT_ROTATION_RANK_DROP = 3
CURRENT_ROTATION_SCORE_GAP = 15.0
CURRENT_DRIFT_FLOOR_PT = 8.0

# Symbol -> crypto-sector mapping (rough; the calibration agent can refine).
SYMBOL_SECTOR = {
    "BTC-USD": "L1", "ETH-USD": "L1", "SOL-USD": "L1", "BNB-USD": "L1",
    "AVAX-USD": "L1", "ADA-USD": "L1", "DOT-USD": "L1",
    "XRP-USD": "payments",
    "LINK-USD": "oracle",
    "MATIC-USD": "layer2",
}

# 24/7 markets.
TRADING_DAYS_PER_YEAR = 365


# ---------- Data loaders ----------------------------------------------------

def load_prices() -> pd.DataFrame:
    df = pd.read_parquet(HIST / "prices_daily.parquet")
    df["date"] = pd.to_datetime(df["date"])
    return df


def load_universe() -> list[str]:
    return json.loads((HIST / "symbols.json").read_text())["universe"]


def close_panel(prices: pd.DataFrame, symbols: list[str] | None = None) -> pd.DataFrame:
    df = prices
    if symbols is not None:
        df = df[df.symbol.isin(symbols)]
    return df.pivot(index="date", columns="symbol", values="close").sort_index().ffill(limit=2)


# ---------- Threshold sweeps ------------------------------------------------

def sweep_chase_trap_5d(close: pd.DataFrame, lookback: int = 60,
                       thresholds: list[float] = (0.15, 0.20, 0.25, 0.30, 0.35, 0.40)) -> pd.DataFrame:
    """For each threshold, simulate top-1 momentum rotation and report key metrics.

    This is the bread-and-butter of the calibration agent: it runs once a day,
    sweeps the gate, and recommends whether to nudge the threshold up or down.
    """
    momentum = close.pct_change(lookback)
    ret_5d = close.pct_change(5)
    ret_fwd = close.pct_change(7).shift(-7)

    rows = []
    for thr in thresholds:
        eligible_mask = ret_5d.abs() < thr
        ranked = momentum.where(eligible_mask).rank(axis=1, ascending=False, method="min")
        top1 = ranked == 1
        # Forward 7d return of the top-1 pick on each day.
        fwd_when_picked = ret_fwd.where(top1)
        flat = fwd_when_picked.stack()
        rows.append({
            "threshold_pct": thr * 100,
            "n_picks": int(top1.sum().sum()),
            "median_fwd_7d_pct": float(flat.median() * 100) if len(flat) else float("nan"),
            "mean_fwd_7d_pct": float(flat.mean() * 100) if len(flat) else float("nan"),
            "win_rate_pct": float((flat > 0).mean() * 100) if len(flat) else float("nan"),
        })
    return pd.DataFrame(rows)


def sweep_momentum_lookback(close: pd.DataFrame,
                            lookbacks: list[int] = (20, 40, 60, 90, 120)) -> pd.DataFrame:
    """How does the choice of momentum window affect top-1 forward returns?"""
    ret_fwd = close.pct_change(7).shift(-7)
    rows = []
    for lb in lookbacks:
        mom = close.pct_change(lb)
        ranked = mom.rank(axis=1, ascending=False, method="min")
        top1 = ranked == 1
        flat = ret_fwd.where(top1).stack()
        rows.append({
            "lookback_days": lb,
            "n_picks": int(top1.sum().sum()),
            "median_fwd_7d_pct": float(flat.median() * 100) if len(flat) else float("nan"),
            "win_rate_pct": float((flat > 0).mean() * 100) if len(flat) else float("nan"),
        })
    return pd.DataFrame(rows)


# ---------- Regime classification -------------------------------------------

def vol_regime_buckets(close: pd.DataFrame, window: int = 30) -> pd.DataFrame:
    """For each symbol, split history into low / mid / high realised-vol regimes
    and report median forward 7d return in each bucket.

    Used by the Thursday volatility-regime calibration."""
    daily_ret = close.pct_change()
    rolling_vol = daily_ret.rolling(window).std() * np.sqrt(TRADING_DAYS_PER_YEAR)
    fwd = close.pct_change(7).shift(-7)

    rows = []
    for sym in close.columns:
        v = rolling_vol[sym].dropna()
        if v.empty:
            continue
        q33, q66 = v.quantile([0.33, 0.66])
        for label, lo, hi in (("low", -np.inf, q33), ("mid", q33, q66), ("high", q66, np.inf)):
            mask = (rolling_vol[sym] > lo) & (rolling_vol[sym] <= hi)
            f = fwd[sym].where(mask).dropna()
            rows.append({
                "symbol": sym,
                "regime": label,
                "n": len(f),
                "median_fwd_7d_pct": float(f.median() * 100) if len(f) else float("nan"),
                "win_rate_pct": float((f > 0).mean() * 100) if len(f) else float("nan"),
            })
    return pd.DataFrame(rows)


def correlation_with_btc(close: pd.DataFrame, window: int = 30) -> pd.DataFrame:
    """Rolling correlation of each symbol's daily returns with BTC.

    Crypto markets often regime-shift between "everything follows BTC" and
    "alts decouple". The Friday calibration uses this to size rotation aggression."""
    if "BTC-USD" not in close.columns:
        return pd.DataFrame()
    rets = close.pct_change()
    btc = rets["BTC-USD"]
    rows = []
    for sym in close.columns:
        if sym == "BTC-USD":
            continue
        rolling = rets[sym].rolling(window).corr(btc)
        rows.append({
            "symbol": sym,
            "median_corr_30d": float(rolling.median()) if rolling.notna().any() else float("nan"),
            "current_corr_30d": float(rolling.iloc[-1]) if rolling.notna().any() else float("nan"),
            "min_corr_30d": float(rolling.min()) if rolling.notna().any() else float("nan"),
            "max_corr_30d": float(rolling.max()) if rolling.notna().any() else float("nan"),
        })
    return pd.DataFrame(rows)


def crypto_sector_summary(close: pd.DataFrame, window: int = 30) -> pd.DataFrame:
    """Group symbols by SYMBOL_SECTOR and report each sector's recent realised
    return + vol. Tuesday's calibration uses this in lieu of stock-style sector ETFs."""
    daily_ret = close.pct_change()
    rows = []
    for sector in set(SYMBOL_SECTOR.values()):
        members = [s for s, sec in SYMBOL_SECTOR.items() if sec == sector and s in close.columns]
        if not members:
            continue
        # Equal-weighted index of the sector.
        ew = daily_ret[members].mean(axis=1).dropna()
        recent = ew.tail(window)
        rows.append({
            "sector": sector,
            "members": ",".join(members),
            "recent_total_return_pct": float((1 + recent).prod() - 1) * 100,
            "recent_realised_vol_annual_pct": float(recent.std() * np.sqrt(TRADING_DAYS_PER_YEAR)) * 100,
        })
    return pd.DataFrame(rows)


# ---------- Funding-rate awareness (PLACEHOLDER) ----------------------------

def funding_rate_buckets(symbol: str) -> pd.DataFrame:
    """TODO: pull recent perp funding-rate history from a public ccxt endpoint
    (binance, bybit) and bucket forward returns by funding regime.

    Hypothesis to test: when funding > +0.01% per 8h sustained 24h,
    forward 24h return is meaningfully negative (longs over-leveraged).

    Until wired, returns an empty DataFrame so callers fall back gracefully.
    The Wednesday calibration entry should be the first to populate this."""
    return pd.DataFrame(columns=["bucket", "n", "median_fwd_24h_pct", "win_rate_pct"])


# ---------- Helpers ---------------------------------------------------------

def annualised_sharpe(daily_returns: pd.Series) -> float:
    """sqrt(365) — crypto trades 24/7."""
    daily_returns = daily_returns.dropna()
    if daily_returns.empty or daily_returns.std() == 0:
        return float("nan")
    return float(daily_returns.mean() / daily_returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR))


def max_drawdown_pct(equity: pd.Series) -> float:
    eq = equity.dropna()
    if eq.empty:
        return float("nan")
    return float((eq / eq.cummax() - 1).min() * 100)
