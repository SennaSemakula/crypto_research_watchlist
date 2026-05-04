"""Smoke test that runs the threshold calibration sweep and prints
the recommended thresholds + realised distribution. Useful for the
operator who wants to recalibrate after refreshing the parquet.

Marked as a normal test (not integration) so it runs in `pytest tests/`
and surfaces the JSON output in CI logs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts" / "research"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import threshold_calibration


def test_threshold_calibration_runs_and_writes_json(tmp_path, monkeypatch):
    """Smoke: the calibrator runs against the actual parquet and
    produces ordered thresholds + a JSON output file."""
    if not (threshold_calibration.HIST / "prices_daily.parquet").exists():
        import pytest
        pytest.skip("no parquet to calibrate against")

    res = threshold_calibration.calibrate()
    print("\n--- threshold calibration result ---")
    print(json.dumps(res, indent=2))

    t = res.get("thresholds", {})
    assert t["strong"] > t["watchlist"] > t["avoid"]
    out_path = Path(res["out_path"])
    assert out_path.exists()
