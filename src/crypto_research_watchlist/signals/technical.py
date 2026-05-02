"""Technical indicator signals — RSI, MACD, EMA cross, volume spike.

Pure pandas/numpy. No network. Daily candles assumed.

Thresholds (see docs/RESEARCH.md):
  * RSI(14)  < 30 oversold ; > 70 overbought ; < 25 / > 80 = strong
  * MACD     bullish when line > signal && line > 0
  * EMA(20) vs EMA(50) cross — golden / death
  * Volume   today >= 2x 30d-avg notable ; >= 3x with price move = strong
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import SignalContext, SignalResult, label_from_strength


def _close_series(price_df: pd.DataFrame) -> pd.Series:
    df = price_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")
    close = df.get("adjusted_close")
    if close is None or close.isna().all():
        close = df["close"]
    return close.astype(float).reset_index(drop=True)


def _volume_series(price_df: pd.DataFrame) -> pd.Series:
    df = price_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")
    if "volume" not in df.columns:
        return pd.Series(dtype=float)
    return df["volume"].astype(float).reset_index(drop=True)


def rsi(close: pd.Series, period: int = 14) -> float | None:
    if len(close) < period + 1:
        return None
    delta = close.diff().dropna()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    last_gain = float(avg_gain.iloc[-1])
    last_loss = float(avg_loss.iloc[-1])
    if last_loss <= 0 and last_gain <= 0:
        return None
    if last_loss <= 0:
        return 100.0
    if last_gain <= 0:
        return 0.0
    rs = last_gain / last_loss
    return float(100 - (100 / (1 + rs)))


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[float, float] | None:
    if len(close) < slow + signal:
        return None
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return float(macd_line.iloc[-1]), float(signal_line.iloc[-1])


def ema_cross(close: pd.Series, fast: int = 20, slow: int = 50, lookback: int = 5) -> str | None:
    """Returns 'golden' / 'death' if a cross occurred within ``lookback``
    sessions, else None."""
    if len(close) < slow + lookback:
        return None
    ema_f = close.ewm(span=fast, adjust=False).mean()
    ema_s = close.ewm(span=slow, adjust=False).mean()
    diff = (ema_f - ema_s).tail(lookback + 1).dropna()
    if len(diff) < 2:
        return None
    sign = np.sign(diff.values)
    for i in range(len(sign) - 1, 0, -1):
        if sign[i - 1] != sign[i] and sign[i] != 0:
            return "golden" if sign[i] > 0 else "death"
    return None


def volume_spike(volume: pd.Series, close: pd.Series) -> tuple[float, float] | None:
    """Return (today_vol/30d_avg, today_pct_move). None if insufficient data."""
    if len(volume) < 31 or len(close) < 2:
        return None
    today_vol = float(volume.iloc[-1])
    avg_vol = float(volume.iloc[-31:-1].mean())
    if avg_vol <= 0:
        return None
    ratio = today_vol / avg_vol
    pct_move = float(close.iloc[-1] / close.iloc[-2] - 1.0)
    return ratio, pct_move


def evaluate(ctx: SignalContext) -> SignalResult:
    if ctx.price_df is None or ctx.price_df.empty:
        return SignalResult(source="technical")

    close = _close_series(ctx.price_df)
    volume = _volume_series(ctx.price_df)

    bullets: list[str] = []
    details: dict = {}
    components: list[float] = []

    r = rsi(close)
    if r is not None:
        details["rsi14"] = round(r, 1)
        if r < 25:
            bullets.append(f"RSI 14 is {r:.0f}: strong oversold")
            components.append(0.6)
        elif r < 30:
            bullets.append(f"RSI 14 is {r:.0f}: oversold")
            components.append(0.3)
        elif r > 80:
            bullets.append(f"RSI 14 is {r:.0f}: strong overbought")
            components.append(-0.6)
        elif r > 70:
            bullets.append(f"RSI 14 is {r:.0f}: overbought")
            components.append(-0.3)

    m = macd(close)
    if m is not None:
        macd_line, signal_line = m
        details["macd"] = {"line": round(macd_line, 4), "signal": round(signal_line, 4)}
        if macd_line > signal_line and macd_line > 0:
            bullets.append("MACD above signal and positive: bullish momentum")
            components.append(0.3)
        elif macd_line < signal_line and macd_line < 0:
            bullets.append("MACD below signal and negative: bearish momentum")
            components.append(-0.3)

    cx = ema_cross(close)
    if cx == "golden":
        bullets.append("Golden cross: 20-EMA crossed above 50-EMA")
        components.append(0.5)
        details["ema_cross"] = "golden"
    elif cx == "death":
        bullets.append("Death cross: 20-EMA crossed below 50-EMA")
        components.append(-0.5)
        details["ema_cross"] = "death"

    spike = volume_spike(volume, close)
    if spike is not None:
        ratio, pct_move = spike
        details["volume_ratio"] = round(ratio, 2)
        if ratio >= 3 and abs(pct_move) >= 0.02:
            sign = "+" if pct_move > 0 else "-"
            direction = "up" if pct_move > 0 else "down"
            bullets.append(
                f"Volume {ratio:.1f}x avg with {sign}{abs(pct_move) * 100:.1f}% move: strong {direction} conviction"
            )
            components.append(0.45 if pct_move > 0 else -0.45)
        elif ratio >= 2:
            bullets.append(f"Volume {ratio:.1f}x 30d average")
            components.append(0.2 if pct_move >= 0 else -0.2)

    strength = max(-1.0, min(1.0, sum(components)))
    return SignalResult(
        source="technical",
        strength=strength,
        label=label_from_strength(strength),
        bullets=bullets,
        details=details,
    )
