# data/historical schema

Files are committed so the autonomous routines can read them without a network
call. Re-run `scripts/research/backfill_history.py` to refresh.

## prices_daily.parquet

Long-form daily bars for the universe + benchmarks + macro markers.

| Column | Type | Notes |
| ------ | ---- | ----- |
| date   | datetime64[ns] | UTC midnight, daily granularity |
| symbol | string | yfinance ticker, e.g. `BTC-USD`, `ETH-USD`, `SPY`, `^VIX` |
| open   | float64 | auto_adjust=True (split + dividend adjusted; no-op for crypto) |
| high   | float64 |  |
| low    | float64 |  |
| close  | float64 | the field used by every calibration function |
| volume | float64 | yfinance reports notional or units depending on symbol; treat as relative |

Compression: zstd. Row order: sort by `(symbol, date)` ascending.

## symbols.json

```json
{
  "universe":  ["BTC-USD", "ETH-USD", ...],
  "benchmarks": ["SPY"],
  "macro":     ["^VIX"],
  "years_back": 5,
  "generated_at": "2026-..."
}
```

The autonomous routines read this to know what is "in scope".

## quality.json

List of per-symbol QualityFlag dicts:

```json
[
  {"symbol": "BTC-USD", "rows": 1825, "first_date": "2021-...", "last_date": "...",
   "gaps_over_3d": 0, "suspect_jumps": 12, "note": ""}
]
```

`suspect_jumps` counts |daily return| > 30% — calibrated higher than the stock
repo's 25% because that magnitude is in-distribution for crypto.
