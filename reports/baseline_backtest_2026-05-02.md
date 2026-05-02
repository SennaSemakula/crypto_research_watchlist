# Crypto Baseline Backtest — simplified AGGRESSIVE_ROTATION

_Generated 2026-05-02T12:06:48.015721+00:00_

Price-only approximation. Captures 60d momentum top-1 selection,
30% chase-trap filter (5d), rotation on rank-drop or chase-trap exit,
CEX-retail-tier round-trip cost.

## Setup

- Universe: 10 symbols (`BTC-USD, ETH-USD, SOL-USD, BNB-USD, XRP-USD, ADA-USD, AVAX-USD, DOT-USD, LINK-USD, MATIC-USD`)
- Date range: 2021-06-27 to 2026-05-01
- Initial capital: $10,000
- Chase-trap threshold: 30% (5d move)
- Momentum lookback: 60d
- Rotation trigger: rank drops 3 or more spots, or chase-trap
- Round-trip cost: 0.36%

## Headline Metrics

| | Strategy | BTC | ETH | SPY |
|---|---|---|---|---|
| Total return % | -56.15 | 125.63 | 15.98 | 80.28 |
| CAGR % | -15.65 | 18.29 | 3.11 | 12.94 |
| Sharpe | 0.20 | 0.58 | 0.40 | 0.79 |
| Max drawdown % | -89.75 | -76.63 | -79.35 | -24.50 |

## Trade Stats

- Total trades: 72
- Win rate: 45.8%
- Avg hold: 24.6 days
- Avg winning trade: 18.34%
- Avg losing trade: -13.14%

Exit reason breakdown:
- rotation: 60
- chase-trap: 11
- end-of-data: 1

## Per-Year Returns (%)

| Year | Strategy | BTC | ETH | SPY |
|---|---|---|---|---|
| 2021 | 127.08 | 33.64 | 86.10 | 12.08 |
| 2022 | -86.26 | -64.27 | -67.50 | -18.18 |
| 2023 | 56.20 | 155.42 | 90.64 | 26.18 |
| 2024 | 118.08 | 121.05 | 46.07 | 24.89 |
| 2025 | -38.68 | -6.34 | -10.97 | 17.72 |
| 2026 | -32.84 | -10.66 | -22.65 | 5.97 |

## Symbol Exposure (% of trades)

- BTC-USD: 19.4%
- SOL-USD: 18.1%
- XRP-USD: 13.9%
- ETH-USD: 11.1%
- AVAX-USD: 11.1%
- BNB-USD: 9.7%
- MATIC-USD: 6.9%
- LINK-USD: 6.9%
- ADA-USD: 2.8%

## Notes

- Crypto trades 24/7, so the Sharpe denominator uses sqrt(365), not sqrt(252).
- The chase-trap threshold of 30% (5d) is the calibration baseline; the daily
  calibration agent should sweep [20, 25, 30, 35, 40] and report which dominates.
- Survivorship bias: MATIC, AVAX, SOL came online during this 5y window so
  they are absent from the eligible set in the early period.
- No funding-rate awareness yet; that is on the calibration agent's TODO list.

## Files

- `reports/baseline_backtest_2026-05-02.md` (this file)
- `reports/baseline_backtest_trades.csv`
- `reports/baseline_backtest_equity.csv`