"""Grid-search calibration sweep over the decision-engine knobs.

Sweeps:
  - chase-trap 5d threshold: 20-40% (5pt steps)
  - rotation score gap: 10-20 (5pt steps)
  - dip threshold from 30d high: 5-12% (1pt steps)

For each grid point, simulates a simple top-1 momentum rotation strategy
across the full parquet history and reports a forward-7d hit-rate metric.
Writes results to ``data/historical/calibration_<date>.json`` so the
operator can review next-week thresholds.

Reuses primitives from lib_calibration.py.

Run: python scripts/research/calibration_sweep.py [--symbols BTC-USD ETH-USD ...]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

# Dev fallback: prefer repo-local .venv when invoked outside it.
_HERE = Path(__file__).resolve()
_VENV_SP = _HERE.parents[2] / ".venv" / "lib" / "python3.13" / "site-packages"
if _VENV_SP.exists() and str(_VENV_SP) not in sys.path:
    sys.path.insert(0, str(_VENV_SP))

import numpy as np
import pandas as pd

from lib_calibration import HIST, close_panel, load_prices

DEFAULT_CHASE_GRID = [0.20, 0.25, 0.30, 0.35, 0.40]
DEFAULT_GAP_GRID = [10.0, 15.0, 20.0]
DEFAULT_DIP_GRID = [0.05, 0.06, 0.07, 0.08, 0.10, 0.12]


def _simulate_grid_point(
    close: pd.DataFrame, *, chase_pct: float, dip_pct: float,
    momentum_lookback: int = 60,
) -> dict:
    """For each day pick the top-1 by 60d momentum subject to:
       (a) 5d return < chase_pct
       (b) drawdown from 30d high <= -dip_pct (we WANT a dip)
       Then look at the forward 7d return."""
    momentum = close.pct_change(momentum_lookback)
    ret_5d = close.pct_change(5)
    high30 = close.rolling(30).max()
    dip = close / high30 - 1.0
    fwd_7d = close.pct_change(7).shift(-7)

    eligible_chase = ret_5d.abs() < chase_pct
    eligible_dip = dip <= -abs(dip_pct)
    eligible = eligible_chase & eligible_dip

    ranked = momentum.where(eligible).rank(axis=1, ascending=False, method="min")
    top1 = ranked == 1
    fwd_when_picked = fwd_7d.where(top1)
    flat = fwd_when_picked.stack()
    if flat.empty:
        return {
            "n_picks": 0,
            "median_fwd_7d_pct": float("nan"),
            "mean_fwd_7d_pct": float("nan"),
            "win_rate_pct": float("nan"),
        }
    return {
        "n_picks": int(top1.sum().sum()),
        "median_fwd_7d_pct": float(flat.median() * 100),
        "mean_fwd_7d_pct": float(flat.mean() * 100),
        "win_rate_pct": float((flat > 0).mean() * 100),
    }


def run_sweep(
    *,
    chase_grid: list[float] | None = None,
    gap_grid: list[float] | None = None,
    dip_grid: list[float] | None = None,
    symbols: list[str] | None = None,
    out_path: Path | None = None,
) -> dict:
    chase_grid = chase_grid or DEFAULT_CHASE_GRID
    gap_grid = gap_grid or DEFAULT_GAP_GRID
    dip_grid = dip_grid or DEFAULT_DIP_GRID

    prices = load_prices()
    close = close_panel(prices, symbols=symbols)

    results: list[dict] = []
    for chase in chase_grid:
        for gap in gap_grid:
            # The rotation gap doesn't show up in this simple top-1 sim
            # (no holding state), so we record it as a context tag for
            # later cross-reference. The decision engine still uses it.
            for dip in dip_grid:
                stats = _simulate_grid_point(
                    close, chase_pct=chase, dip_pct=dip,
                )
                results.append({
                    "chase_trap_5d_pct": chase,
                    "rotation_score_gap": gap,
                    "dip_threshold_from_30d_high_pct": dip,
                    **stats,
                })

    # Pick the row that maximises win rate, breaking ties by mean.
    valid = [r for r in results if not np.isnan(r["win_rate_pct"])]
    best = None
    if valid:
        best = max(
            valid,
            key=lambda r: (r["win_rate_pct"], r["mean_fwd_7d_pct"], -abs(r["dip_threshold_from_30d_high_pct"] - 0.08)),
        )

    out = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "n_grid_points": len(results),
        "best": best,
        "results": results,
    }
    out_path = out_path or HIST / f"calibration_{date.today().isoformat()}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2))
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    out_path = Path(args.out) if args.out else None
    res = run_sweep(symbols=args.symbols, out_path=out_path)
    print(json.dumps({"n": res["n_grid_points"], "best": res["best"]}, indent=2))


if __name__ == "__main__":
    main()
