"""Tests for the calibration sweep grid search."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts" / "research"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _make_synthetic_close(n: int = 200) -> pd.DataFrame:
    rng = np.random.default_rng(123)
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    close_btc = 100 * (1 + rng.normal(0.001, 0.02, n)).cumprod()
    close_eth = 100 * (1 + rng.normal(0.0008, 0.025, n)).cumprod()
    rows = []
    for d, b, e in zip(dates, close_btc, close_eth, strict=False):
        rows.append({
            "date": d, "symbol": "BTC-USD",
            "open": b, "high": b * 1.01, "low": b * 0.99, "close": b, "volume": 1e8,
        })
        rows.append({
            "date": d, "symbol": "ETH-USD",
            "open": e, "high": e * 1.01, "low": e * 0.99, "close": e, "volume": 1e8,
        })
    return pd.DataFrame(rows)


def test_run_sweep_writes_json(tmp_path, monkeypatch):
    # Build a fake parquet at the location lib_calibration expects.
    hist = tmp_path / "data" / "historical"
    hist.mkdir(parents=True, exist_ok=True)
    parquet_path = hist / "prices_daily.parquet"
    _make_synthetic_close().to_parquet(parquet_path)

    # Patch HIST in lib_calibration so loaders find our temp parquet.
    import lib_calibration as lc
    monkeypatch.setattr(lc, "HIST", hist)

    import calibration_sweep as cs
    monkeypatch.setattr(cs, "HIST", hist)

    out_path = tmp_path / "calibration_test.json"
    res = cs.run_sweep(
        chase_grid=[0.20, 0.30],
        gap_grid=[15.0],
        dip_grid=[0.05, 0.08],
        symbols=["BTC-USD", "ETH-USD"],
        out_path=out_path,
    )
    assert out_path.exists()
    payload = json.loads(out_path.read_text())
    assert payload["n_grid_points"] == 2 * 1 * 2
    assert "results" in payload
    assert isinstance(payload["results"], list)
    # Each result row carries the three knobs.
    for r in payload["results"]:
        assert "chase_trap_5d_pct" in r
        assert "rotation_score_gap" in r
        assert "dip_threshold_from_30d_high_pct" in r
        assert "win_rate_pct" in r


def test_run_sweep_picks_best(tmp_path, monkeypatch):
    hist = tmp_path / "data" / "historical"
    hist.mkdir(parents=True, exist_ok=True)
    parquet_path = hist / "prices_daily.parquet"
    _make_synthetic_close().to_parquet(parquet_path)

    import lib_calibration as lc
    monkeypatch.setattr(lc, "HIST", hist)
    import calibration_sweep as cs
    monkeypatch.setattr(cs, "HIST", hist)

    out_path = tmp_path / "cal.json"
    res = cs.run_sweep(
        chase_grid=[0.30],
        gap_grid=[15.0],
        dip_grid=[0.08],
        symbols=["BTC-USD", "ETH-USD"],
        out_path=out_path,
    )
    if res["best"] is not None:
        assert "win_rate_pct" in res["best"]
