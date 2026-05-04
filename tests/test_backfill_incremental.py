"""Tests for the incremental backfill flow.

The full backfill pulls 5y of OHLCV; the incremental path pulls only the
last 7 days and merges into the existing parquet, deduplicating on
(symbol, date). All network calls are mocked; tests are offline.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts" / "research"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import backfill_history as bh


def _frame(symbol: str, dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.to_datetime(dates),
        "open": [1.0] * len(dates),
        "high": [1.1] * len(dates),
        "low": [0.9] * len(dates),
        "close": [1.05] * len(dates),
        "volume": [1000.0] * len(dates),
        "symbol": symbol,
    })


def test_merge_incremental_dedupes_on_symbol_date():
    existing = _frame("BTC-USD", ["2026-04-25", "2026-04-26", "2026-04-27"])
    new = _frame("BTC-USD", ["2026-04-27", "2026-04-28", "2026-04-29"])
    # The shared 2026-04-27 row should appear once, with values from `new`
    # (keep="last").
    new = new.assign(close=[9.0, 9.0, 9.0])

    merged = bh.merge_incremental(existing, new)

    assert len(merged) == 5
    assert list(merged["date"].dt.date.astype(str)) == [
        "2026-04-25", "2026-04-26", "2026-04-27", "2026-04-28", "2026-04-29",
    ]
    # 2026-04-27 row should carry the new close (9.0).
    overlap_close = merged.loc[merged["date"] == pd.Timestamp("2026-04-27"), "close"].iloc[0]
    assert overlap_close == 9.0


def test_merge_incremental_keeps_separate_symbols():
    existing = _frame("BTC-USD", ["2026-04-25", "2026-04-26"])
    new = _frame("ETH-USD", ["2026-04-25", "2026-04-26"])
    merged = bh.merge_incremental(existing, new)
    assert len(merged) == 4
    assert set(merged["symbol"].unique()) == {"BTC-USD", "ETH-USD"}


def test_merge_incremental_handles_empty_existing():
    new = _frame("BTC-USD", ["2026-04-25"])
    merged = bh.merge_incremental(pd.DataFrame(), new)
    assert len(merged) == 1


def test_merge_incremental_handles_empty_new():
    existing = _frame("BTC-USD", ["2026-04-25"])
    merged = bh.merge_incremental(existing, pd.DataFrame())
    assert len(merged) == 1


def test_run_incremental_writes_merged_parquet(monkeypatch, tmp_path):
    """End-to-end: existing parquet + mocked yfinance -> merged parquet."""

    # Redirect OUT_DIR + CONFIG to tmp.
    out_dir = tmp_path / "data" / "historical"
    out_dir.mkdir(parents=True)
    monkeypatch.setattr(bh, "OUT_DIR", out_dir)

    cfg_path = tmp_path / "config.yml"
    cfg_path.write_text(
        "universe:\n"
        "  symbols:\n"
        "    - BTC-USD\n"
        "    - ETH-USD\n"
    )
    monkeypatch.setattr(bh, "CONFIG_PATH", cfg_path)

    # Seed an existing parquet with one old row per symbol (incl. BENCHMARKS+MACRO).
    seed = pd.concat([
        _frame("BTC-USD", ["2026-04-20"]),
        _frame("ETH-USD", ["2026-04-20"]),
        _frame("SPY",     ["2026-04-20"]),
        _frame("^VIX",    ["2026-04-20"]),
    ], ignore_index=True)
    seed_path = out_dir / "prices_daily.parquet"
    seed.to_parquet(seed_path, index=False)

    # Mock fetch_one to return one fresh row per symbol.
    def _fake_fetch(symbol: str, start: str, end: str, retries: int = 3) -> pd.DataFrame:
        return _frame(symbol, ["2026-05-03"])

    monkeypatch.setattr(bh, "fetch_one", _fake_fetch)

    # Avoid the per-symbol sleep slowing the test.
    monkeypatch.setattr(bh.time, "sleep", lambda _s: None)

    rc = bh.run_incremental(["BTC-USD", "ETH-USD"])
    assert rc == 0

    out = pd.read_parquet(seed_path)
    # 4 seeded + 4 fresh = 8 rows (no dups: dates are different).
    assert len(out) == 8
    assert "2026-05-03" in set(out["date"].dt.date.astype(str))


def test_run_incremental_errors_when_no_existing_parquet(monkeypatch, tmp_path):
    out_dir = tmp_path / "data" / "historical"
    out_dir.mkdir(parents=True)
    monkeypatch.setattr(bh, "OUT_DIR", out_dir)

    cfg_path = tmp_path / "config.yml"
    cfg_path.write_text("universe:\n  symbols:\n    - BTC-USD\n")
    monkeypatch.setattr(bh, "CONFIG_PATH", cfg_path)

    rc = bh.run_incremental(["BTC-USD"])
    assert rc == 1
