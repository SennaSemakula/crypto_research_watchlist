"""Cross-asset signal: ETH/BTC ratio + relative strength vs BTC.

Crypto rotation alpha lives in the alts-vs-BTC plane. When the ETH/BTC
ratio is rising, alts are outperforming BTC and rotation has edge. When
it is falling, BTC is dominating and rotation away from BTC mostly loses.

For non-BTC symbols, we also compute relative strength: 60-day return
vs BTC's 60-day return.
"""

from __future__ import annotations

import pandas as pd

from . import SignalContext, SignalResult, label_from_strength


def _close(price_df: pd.DataFrame | None) -> pd.Series | None:
    if price_df is None or price_df.empty:
        return None
    df = price_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")
    close = df.get("adjusted_close")
    if close is None or close.isna().all():
        close = df["close"]
    return close.astype(float).reset_index(drop=True)


def _ret(close: pd.Series, days: int) -> float | None:
    if close is None or len(close) < days + 1:
        return None
    return float(close.iloc[-1] / close.iloc[-(days + 1)] - 1.0)


def evaluate(ctx: SignalContext) -> SignalResult:
    own = _close(ctx.price_df)
    btc = _close(ctx.btc_price_df)
    if own is None or btc is None:
        return SignalResult(source="cross_asset", details={"reason": "missing price panels"})

    ret60 = _ret(own, 60)
    btc_ret60 = _ret(btc, 60)
    if ret60 is None or btc_ret60 is None:
        return SignalResult(source="cross_asset", details={"reason": "insufficient history"})

    rs = ret60 - btc_ret60
    bullets: list[str] = []
    strength = 0.0
    details = {
        "ret_60d": round(ret60, 4),
        "btc_ret_60d": round(btc_ret60, 4),
        "rel_strength_60d": round(rs, 4),
    }

    is_btc = ctx.symbol.upper().startswith("BTC")

    if is_btc:
        # For BTC itself, use ETH/BTC ratio direction as a "BTC dominance"
        # proxy. Rising ETH/BTC = alt season, mildly bearish for BTC's
        # rotation merit.
        eth = _close(ctx.eth_price_df)
        if eth is None or len(eth) < 31:
            return SignalResult(source="cross_asset", details=details | {"reason": "no eth panel"})
        ratio = (eth / btc.iloc[-len(eth):].reset_index(drop=True)).dropna()
        ratio_30d_change = float(ratio.iloc[-1] / ratio.iloc[-31] - 1.0) if len(ratio) >= 31 else 0.0
        details["eth_btc_ratio_change_30d"] = round(ratio_30d_change, 4)
        if ratio_30d_change >= 0.10:
            strength = -0.3
            bullets.append("ETH/BTC up 10%+ in 30d: alt season, BTC rotation drag")
        elif ratio_30d_change <= -0.10:
            strength = 0.3
            bullets.append("ETH/BTC down 10%+ in 30d: BTC season, BTC rotation favoured")
    else:
        # Alt: relative strength vs BTC
        if rs >= 0.20:
            strength = 0.5
            bullets.append(f"Outperforming BTC by {rs * 100:.0f} pts over 60d")
        elif rs >= 0.05:
            strength = 0.25
            bullets.append(f"Outperforming BTC by {rs * 100:.0f} pts over 60d")
        elif rs <= -0.20:
            strength = -0.5
            bullets.append(f"Underperforming BTC by {-rs * 100:.0f} pts over 60d")
        elif rs <= -0.05:
            strength = -0.25
            bullets.append(f"Underperforming BTC by {-rs * 100:.0f} pts over 60d")

    return SignalResult(
        source="cross_asset",
        strength=strength,
        label=label_from_strength(strength),
        bullets=bullets,
        details=details,
    )
