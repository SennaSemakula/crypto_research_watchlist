"""Backfill OHLCV history for the crypto majors + benchmarks + macro.

Two modes:

  * Default (5y full backfill) — first-time setup or quality refresh:
        python scripts/research/backfill_history.py

  * Incremental (last 7 days) — daily refresh, designed to stay under
    60s so the GitHub Actions backfill workflow can run before daily.yml:
        python scripts/research/backfill_history.py --incremental

Output (committed so autonomous agents can read it):
  data/historical/prices_daily.parquet     OHLCV daily bars
  data/historical/symbols.json             Universe + benchmark + macro symbol map
  data/historical/quality.json             Per-symbol gap/jump flags

Idempotent. Re-running refreshes everything (full mode) or merges last
7 days into the existing parquet (incremental mode), de-duplicating
on (symbol, date).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

# When invoked via the local .venv-less interpreter, fall back to the venv's
# site-packages so that `python3 scripts/research/...` works in dev. Routines
# running under the platform agent should set up their own environment via
# `pip install -e .` and ignore this shim.
_HERE = Path(__file__).resolve()
_VENV_SP = _HERE.parents[2] / ".venv" / "lib" / "python3.13" / "site-packages"
if _VENV_SP.exists() and str(_VENV_SP) not in sys.path:
    sys.path.insert(0, str(_VENV_SP))

import pandas as pd
import yaml
import yfinance as yf

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config.yml"
OUT_DIR = ROOT / "data" / "historical"
OUT_DIR.mkdir(parents=True, exist_ok=True)

YEARS_BACK = 5
INCREMENTAL_DAYS = 7

# Benchmarks. BTC is the crypto-native benchmark (also in universe). SPY for cross-asset.
BENCHMARKS = ["SPY"]
# Macro: VIX as regime marker.
MACRO = ["^VIX"]


@dataclass
class QualityFlag:
    symbol: str
    rows: int
    first_date: str
    last_date: str
    gaps_over_3d: int
    suspect_jumps: int  # daily moves > 30% absolute (crypto is volatile)
    note: str = ""


def load_universe() -> list[str]:
    cfg = yaml.safe_load(CONFIG_PATH.read_text())
    syms = cfg.get("universe", {}).get("symbols", []) or []
    return [s.strip() for s in syms if isinstance(s, str) and s.strip()]


def fetch_one(symbol: str, start: str, end: str, retries: int = 3) -> pd.DataFrame:
    """Pull daily OHLCV for one symbol with light retry. Returns empty DF on failure."""
    last_err = None
    for attempt in range(retries):
        try:
            df = yf.download(
                symbol,
                start=start,
                end=end,
                interval="1d",
                auto_adjust=True,
                progress=False,
                threads=False,
            )
            if df is not None and not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [c[0] for c in df.columns]
                df = df.reset_index()
                df["symbol"] = symbol
                df.columns = [str(c).lower().replace(" ", "_") for c in df.columns]
                return df
            last_err = "empty response"
        except Exception as exc:  # noqa: BLE001
            last_err = repr(exc)
        time.sleep(1.0 * (attempt + 1))
    print(f"  ! {symbol}: failed after {retries} retries ({last_err})", file=sys.stderr)
    return pd.DataFrame()


def detect_quality(symbol: str, df: pd.DataFrame) -> QualityFlag:
    """Cheap noise-detection. For crypto we tolerate larger single-day moves
    (30% threshold instead of stocks' 25%) — these happen organically."""
    if df.empty:
        return QualityFlag(symbol=symbol, rows=0, first_date="", last_date="",
                           gaps_over_3d=0, suspect_jumps=0, note="empty")

    df = df.sort_values("date").copy()
    df["date"] = pd.to_datetime(df["date"])
    df["gap_days"] = df["date"].diff().dt.days
    # Crypto trades 24/7, so any gap > 3d is a real data gap (not a weekend).
    gaps = int((df["gap_days"] > 3).sum())

    df["ret"] = df["close"].pct_change()
    suspect = int((df["ret"].abs() > 0.30).sum())

    return QualityFlag(
        symbol=symbol,
        rows=len(df),
        first_date=str(df["date"].min().date()),
        last_date=str(df["date"].max().date()),
        gaps_over_3d=gaps,
        suspect_jumps=suspect,
    )


def merge_incremental(existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """Merge new rows into existing parquet, dedup on (symbol, date), keep last.

    The "last" rule lets re-fetched recent days correct previously-missing
    bars (e.g. yfinance was rate-limited yesterday but returned data today).
    """
    if existing.empty:
        return new.copy()
    if new.empty:
        return existing.copy()
    merged = pd.concat([existing, new], ignore_index=True)
    merged["date"] = pd.to_datetime(merged["date"])
    # Keep the most-recently-fetched row per (symbol, date) — i.e. the new one.
    merged = merged.drop_duplicates(subset=["symbol", "date"], keep="last")
    return merged.sort_values(["symbol", "date"]).reset_index(drop=True)


def run_incremental(universe: list[str]) -> int:
    """Pull last INCREMENTAL_DAYS, merge into existing parquet. <60s."""
    prices_path = OUT_DIR / "prices_daily.parquet"
    if not prices_path.exists():
        print(
            "FATAL: no existing parquet to merge into; run a full backfill first",
            file=sys.stderr,
        )
        return 1

    existing = pd.read_parquet(prices_path)
    existing["date"] = pd.to_datetime(existing["date"])

    # Fetch a slightly wider window (INCREMENTAL_DAYS + 2) to handle TZ
    # boundary jitter and yfinance's exclusive end_date.
    end = datetime.now(UTC).date() + timedelta(days=1)
    start = end - timedelta(days=INCREMENTAL_DAYS + 2)

    all_symbols = sorted(set(universe + BENCHMARKS + MACRO))
    print(f"Incremental backfill: {len(all_symbols)} symbols, {start} -> {end}")

    new_frames: list[pd.DataFrame] = []
    for i, sym in enumerate(all_symbols, 1):
        print(f"[{i:>2}/{len(all_symbols)}] {sym}", flush=True)
        df = fetch_one(sym, str(start), str(end))
        if not df.empty:
            new_frames.append(df)
        # Tighter sleep — incremental needs to stay under 60s.
        time.sleep(0.15)

    if not new_frames:
        print("incremental: no new data fetched; existing parquet unchanged")
        return 0

    new = pd.concat(new_frames, ignore_index=True)
    keep_cols = ["date", "symbol", "open", "high", "low", "close", "volume"]
    new = new[[c for c in keep_cols if c in new.columns]]
    new["date"] = pd.to_datetime(new["date"])

    merged = merge_incremental(existing, new)
    added = len(merged) - len(existing)

    merged.to_parquet(prices_path, index=False, compression="zstd")
    latest = merged["date"].max()
    print(
        f"\nWrote {prices_path}: {len(merged):,} rows total "
        f"(+{added} new), latest date {latest.date()}, "
        f"{prices_path.stat().st_size / 1e6:.2f} MB"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--incremental",
        action="store_true",
        help=f"Refresh only the last {INCREMENTAL_DAYS} days and merge into the "
             "existing parquet. Designed to run in <60s for daily cron.",
    )
    args = parser.parse_args(argv)

    universe = load_universe()
    if args.incremental:
        return run_incremental(universe)

    all_symbols = sorted(set(universe + BENCHMARKS + MACRO))

    end = datetime.now(UTC).date()
    start = end - timedelta(days=YEARS_BACK * 365 + 5)
    print(f"Backfilling {len(all_symbols)} symbols from {start} to {end}")
    print(f"  Universe: {len(universe)}")
    print(f"  Bench:    {len(BENCHMARKS)} ({BENCHMARKS})")
    print(f"  Macro:    {len(MACRO)} ({MACRO})")

    frames: list[pd.DataFrame] = []
    quality: list[QualityFlag] = []

    for i, sym in enumerate(all_symbols, 1):
        print(f"[{i:>2}/{len(all_symbols)}] {sym}", flush=True)
        df = fetch_one(sym, str(start), str(end))
        quality.append(detect_quality(sym, df))
        if not df.empty:
            frames.append(df)
        time.sleep(0.4)

    if not frames:
        print("FATAL: no data fetched", file=sys.stderr)
        return 1

    prices = pd.concat(frames, ignore_index=True)
    keep_cols = ["date", "symbol", "open", "high", "low", "close", "volume"]
    prices = prices[[c for c in keep_cols if c in prices.columns]]
    prices = prices.sort_values(["symbol", "date"]).reset_index(drop=True)

    prices_path = OUT_DIR / "prices_daily.parquet"
    prices.to_parquet(prices_path, index=False, compression="zstd")
    print(f"\nWrote {prices_path}: {len(prices):,} rows, "
          f"{prices_path.stat().st_size / 1e6:.2f} MB")

    sym_path = OUT_DIR / "symbols.json"
    sym_path.write_text(json.dumps({
        "universe": universe,
        "benchmarks": BENCHMARKS,
        "macro": MACRO,
        "years_back": YEARS_BACK,
        "generated_at": datetime.now(UTC).isoformat(),
    }, indent=2))
    print(f"Wrote {sym_path}")

    qpath = OUT_DIR / "quality.json"
    qpath.write_text(json.dumps([asdict(q) for q in quality], indent=2))
    print(f"Wrote {qpath}")

    suspect_total = sum(q.suspect_jumps for q in quality)
    gap_total = sum(q.gaps_over_3d for q in quality)
    print(f"\nQuality: {suspect_total} suspect jumps, {gap_total} gaps "
          f"across {len(quality)} symbols")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
