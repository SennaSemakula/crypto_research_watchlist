"""Recalibrate STRONG / WATCH / AVOID score thresholds against history.

Walks the parquet, computes a pipeline score (technical + cross_asset +
volatility regime + drawdown — i.e. the price-derived features that
work without live funding/OI/on-chain data), and reports the score
distribution. Picks thresholds that produce roughly:

  ~10% STRONG, ~30% WATCH, ~50% NEUTRAL, ~10% AVOID

The output is written to data/historical/threshold_calibration_<date>.json
with the recommended thresholds and the empirical bucket distribution
they produce.

Run:
    python scripts/research/threshold_calibration.py
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

# Dev fallback for venv site-packages.
_HERE = Path(__file__).resolve()
_VENV_SP = _HERE.parents[2] / ".venv" / "lib" / "python3.13" / "site-packages"
if _VENV_SP.exists() and str(_VENV_SP) not in sys.path:
    sys.path.insert(0, str(_VENV_SP))

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
HIST = ROOT / "data" / "historical"
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from crypto_research_watchlist.scoring import (  # noqa: E402
    DEFAULT_WEIGHTS,
    aggregate_score,
    drawdown_feature,
    momentum_feature,
    rel_strength_feature,
    volatility_feature,
)
from crypto_research_watchlist.signals import SignalContext  # noqa: E402
from crypto_research_watchlist.signals import cross_asset, technical  # noqa: E402


def _per_symbol_scores(prices: pd.DataFrame, sample_every_days: int = 7) -> list[float]:
    """Compute pipeline scores at weekly snapshots across history."""
    btc = prices[prices.symbol == "BTC-USD"].sort_values("date").reset_index(drop=True)
    eth = prices[prices.symbol == "ETH-USD"].sort_values("date").reset_index(drop=True)

    scores: list[float] = []
    symbols = sorted(prices.symbol.unique())

    for sym in symbols:
        if sym in {"SPY", "^VIX"}:
            continue
        df = prices[prices.symbol == sym].sort_values("date").reset_index(drop=True)
        if len(df) < 90:
            continue

        # Walk weekly.
        for end_idx in range(90, len(df), sample_every_days):
            window = df.iloc[: end_idx + 1].copy()
            btc_window = btc[btc.date <= window.date.iloc[-1]].copy()
            eth_window = eth[eth.date <= window.date.iloc[-1]].copy()

            ctx = SignalContext(
                symbol=sym,
                price_df=window,
                btc_price_df=btc_window,
                eth_price_df=eth_window,
            )
            tech = technical.evaluate(ctx)
            cx = cross_asset.evaluate(ctx)

            # Build the same feature set the live pipeline uses.
            close = window["close"].astype(float)
            ret = close.pct_change().dropna().tail(30)
            ann_vol = float(ret.std() * np.sqrt(365)) if len(ret) > 1 else None
            recent = close.tail(31)
            peak = recent.cummax()
            dd = float(recent.iloc[-1] / peak.max() - 1.0) if not recent.empty else None

            momentum = momentum_feature(tech.strength)
            rs = rel_strength_feature(cx.strength)
            vol = volatility_feature(ann_vol)
            ddf = drawdown_feature(dd)

            from crypto_research_watchlist.scoring import FeatureScores
            features = FeatureScores(
                momentum=momentum,
                volatility_regime=vol,
                rel_strength_vs_btc=rs,
                funding_signal=None,  # not historical
                drawdown_penalty=ddf,
            )
            score = aggregate_score(features, weights=DEFAULT_WEIGHTS)
            if score is not None:
                scores.append(score)
    return scores


def calibrate(
    *,
    target_strong_pct: float = 10.0,
    target_watch_pct: float = 30.0,
    target_avoid_pct: float = 10.0,
) -> dict:
    """Find thresholds matching the target distribution."""
    prices = pd.read_parquet(HIST / "prices_daily.parquet")
    prices["date"] = pd.to_datetime(prices["date"])

    scores = _per_symbol_scores(prices)
    if not scores:
        return {"error": "no scores produced"}

    arr = np.array(scores)

    # Pick thresholds at the empirical percentiles.
    strong_thr = float(np.percentile(arr, 100 - target_strong_pct))
    watch_thr = float(np.percentile(arr, 100 - target_strong_pct - target_watch_pct))
    avoid_thr = float(np.percentile(arr, target_avoid_pct))

    # Round to a tidy half-integer.
    def _round_half(x: float) -> float:
        return round(x * 2) / 2

    strong_thr = _round_half(strong_thr)
    watch_thr = _round_half(watch_thr)
    avoid_thr = _round_half(avoid_thr)

    # Realised distribution under the chosen thresholds.
    n = len(arr)
    n_strong = int((arr >= strong_thr).sum())
    n_watch = int(((arr >= watch_thr) & (arr < strong_thr)).sum())
    n_avoid = int((arr < avoid_thr).sum())
    n_neutral = n - n_strong - n_watch - n_avoid

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_scores": n,
        "score_stats": {
            "min": float(arr.min()),
            "p10": float(np.percentile(arr, 10)),
            "p25": float(np.percentile(arr, 25)),
            "median": float(np.median(arr)),
            "p75": float(np.percentile(arr, 75)),
            "p90": float(np.percentile(arr, 90)),
            "max": float(arr.max()),
            "mean": float(arr.mean()),
            "std": float(arr.std()),
        },
        "targets_pct": {
            "strong": target_strong_pct,
            "watch": target_watch_pct,
            "avoid": target_avoid_pct,
        },
        "thresholds": {
            "strong": strong_thr,
            "watchlist": watch_thr,
            "avoid": avoid_thr,
        },
        "realised_distribution_pct": {
            "STRONG": round(100.0 * n_strong / n, 1),
            "WATCH": round(100.0 * n_watch / n, 1),
            "NEUTRAL": round(100.0 * n_neutral / n, 1),
            "AVOID": round(100.0 * n_avoid / n, 1),
        },
        "realised_counts": {
            "STRONG": n_strong,
            "WATCH": n_watch,
            "NEUTRAL": n_neutral,
            "AVOID": n_avoid,
        },
    }

    out_path = HIST / f"threshold_calibration_{date.today().isoformat()}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2))
    out["out_path"] = str(out_path)
    return out


def main() -> int:
    res = calibrate()
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
