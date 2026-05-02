# SIGNALS

Per-evaluator reference: thesis, formula, regime, calibration knobs.

All evaluators take ``signals.SignalContext`` and return ``signals.SignalResult``.
Strength is bounded in [-1, +1]. Notable threshold = 0.30. Strong = 0.60.

## technical (`signals/technical.py`)

Pure price + volume signals on daily candles.

| Indicator   | Formula                              | Trigger        | Strength |
| ----------- | ------------------------------------ | -------------- | -------- |
| RSI(14)     | Wilder smoothed gain/loss            | < 25           | +0.6     |
|             |                                      | < 30           | +0.3     |
|             |                                      | > 70           | -0.3     |
|             |                                      | > 80           | -0.6     |
| MACD        | EMA(12) - EMA(26), sig EMA(9)        | line>sig & >0  | +0.3     |
|             |                                      | line<sig & <0  | -0.3     |
| EMA cross   | EMA(20) vs EMA(50), 5d lookback      | golden         | +0.5     |
|             |                                      | death          | -0.5     |
| Vol spike   | today / 30d-avg                       | >=3x & +2% day | +0.45    |
|             |                                      | >=3x & -2% day | -0.45    |
|             |                                      | >=2x           | +/-0.2   |

Components combine additively, clamped to [-1, +1].

Calibration knobs to sweep weekly: RSI thresholds (25/30 vs 28/32 vs 20/35),
EMA cross fast/slow window, volume spike multiplier.

## funding_rate (`signals/funding_rate.py`)

Crypto-only. Reads ``ctx.funding_rate_history`` (list of 8h prints, last 24h).
Median over the window classifies the regime.

| Median 8h funding | Direction | Strength |
| ----------------- | --------- | -------- |
| <= -0.06%         | bullish   | +0.6     |
| <= -0.03%         | bullish   | +0.3     |
| >= +0.05%         | bearish   | -0.3     |
| >= +0.10%         | bearish   | -0.6     |

Regime: contrarian. Works in chop / ranging markets. Suspended (don't trade
on it alone) during strong directional trends where funding can persist
extreme for days.

## open_interest (`signals/open_interest.py`)

Combines 7d OI delta with 7d price delta:

| OI    | Price | Reading                        | Strength |
| ----- | ----- | ------------------------------ | -------- |
| up    | up    | trend conviction               | +0.45    |
| down  | down  | capitulation (bottom-y)        | +0.35    |
| up    | down  | shorts adding (squeeze risk)   | +0.25    |
| down  | up    | short cover, unsustainable     | -0.30    |

Both deltas must be notable (|OI| >= 10%, |price| >= 5%) to fire.

## onchain (`signals/onchain.py`)

Two inputs (independent):
- ``active_addresses_z``: z-score of 30d active addresses vs 1y baseline
- ``exchange_netflow_usd_7d``: USD net flow onto exchanges (negative = outflow)

Strong on-chain accumulation (>= 100M USD outflow over 7d) plus high
activity (z >= 2) is the highest-conviction setup. v1 sources Blockchair
(BTC, ETH only); alts return NEUTRAL.

## cross_asset (`signals/cross_asset.py`)

For non-BTC symbols: 60d return minus BTC's 60d return (relative strength).
For BTC: 30d ETH/BTC ratio change as a "BTC dominance" proxy.

Useful for rotation: when alts have outperformed for 60d, the rotation
trade has worked; when BTC has outperformed, rotation drag is high.

## What's stubbed in v1

- All evaluators that need network data (funding, OI, on-chain) accept
  inputs via ``SignalContext`` but the *providers* that fill those
  fields are stubbed. The evaluators themselves are tested.
- Liquidation cascades signal: documented in RESEARCH.md, not implemented
  (websocket capture out of scope).
- Macro signal (DXY, real yields): not yet added; will reuse the stock
  side's FRED provider when ported.

## Calibration cadence

- Daily: technical thresholds + funding-rate thresholds (sweep over backtested forward returns).
- Weekly: signal weights for the aggregator (which signals predict best?).
- Monthly: regime detection (when does each signal break?).

The aggregator is in ``signals/__init__.py::aggregate_strength`` and takes
an optional weights dict. Default is equal-weight; calibration is expected
to argue for non-uniform weights.
