"""Open-interest delta signal.

Thesis: combining 7d OI change with 7d price change tells you what kind of
move you are in.
  * OI up + price up   = trend conviction
  * OI up + price flat = squeeze brewing
  * OI down + price down = capitulation (often bottoms)
  * OI down + price up  = short-cover (often unsustainable)

v1: data is stubbed; returns NEUTRAL when OI info absent.
"""

from __future__ import annotations

import pandas as pd

from . import LABEL_NO_DATA, SignalContext, SignalResult, label_from_strength

# Thresholds.
OI_DELTA_NOTABLE = 0.10   # 10% OI move over 7d is notable
PRICE_DELTA_NOTABLE = 0.05  # 5% price move over 7d is notable


def _close_pct_change_7d(price_df: pd.DataFrame | None) -> float | None:
    if price_df is None or price_df.empty or len(price_df) < 8:
        return None
    df = price_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")
    close = df.get("adjusted_close")
    if close is None or close.isna().all():
        close = df["close"]
    close = close.astype(float).reset_index(drop=True)
    if len(close) < 8:
        return None
    return float(close.iloc[-1] / close.iloc[-8] - 1.0)


def evaluate(ctx: SignalContext) -> SignalResult:
    oi_today = ctx.open_interest_today
    oi_7d = ctx.open_interest_7d_ago
    if oi_today is None or oi_7d is None or oi_7d == 0:
        return SignalResult(
            source="open_interest",
            label=LABEL_NO_DATA,
            details={"reason": "missing OI data (provider returned None)"},
        )

    oi_delta = (oi_today - oi_7d) / oi_7d
    price_delta = _close_pct_change_7d(ctx.price_df)
    if price_delta is None:
        return SignalResult(
            source="open_interest",
            label=LABEL_NO_DATA,
            details={"reason": "insufficient price history for 7d delta"},
        )

    bullets: list[str] = []
    strength = 0.0
    details = {
        "oi_delta_7d": round(oi_delta, 4),
        "price_delta_7d": round(price_delta, 4),
    }

    notable = abs(oi_delta) >= OI_DELTA_NOTABLE and abs(price_delta) >= PRICE_DELTA_NOTABLE

    if notable:
        if oi_delta > 0 and price_delta > 0:
            strength = 0.45
            bullets.append(
                f"OI up {oi_delta * 100:.0f}% with price up {price_delta * 100:.0f}%: trend conviction"
            )
        elif oi_delta < 0 and price_delta < 0:
            strength = 0.35
            bullets.append(
                f"OI down {oi_delta * 100:.0f}% with price down {price_delta * 100:.0f}%: capitulation"
            )
        elif oi_delta > 0 and price_delta < 0:
            # New shorts piling in on weakness; squeeze risk = mildly bullish
            strength = 0.25
            bullets.append(
                f"OI up {oi_delta * 100:.0f}% with price down {price_delta * 100:.0f}%: shorts adding (squeeze risk)"
            )
        else:
            # OI down + price up = unsustainable short-cover rally
            strength = -0.3
            bullets.append(
                f"OI down {oi_delta * 100:.0f}% with price up {price_delta * 100:.0f}%: short-cover (caution)"
            )

    return SignalResult(
        source="open_interest",
        strength=strength,
        label=label_from_strength(strength),
        bullets=bullets,
        details=details,
    )
