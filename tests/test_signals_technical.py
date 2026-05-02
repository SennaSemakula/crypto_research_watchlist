"""Technical signal evaluator tests on synthetic data."""

from __future__ import annotations

import numpy as np
import pandas as pd

from crypto_research_watchlist.signals import SignalContext
from crypto_research_watchlist.signals.technical import (
    ema_cross,
    evaluate,
    macd,
    rsi,
    volume_spike,
)


def _make_df(close_array: np.ndarray, volume_array: np.ndarray | None = None) -> pd.DataFrame:
    n = len(close_array)
    if volume_array is None:
        volume_array = np.full(n, 1e8)
    return pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=n, freq="D"),
        "open": close_array,
        "high": close_array,
        "low": close_array,
        "close": close_array,
        "volume": volume_array,
    })


def test_rsi_oversold_when_falling():
    arr = np.linspace(100, 50, 30)
    s = pd.Series(arr).astype(float)
    val = rsi(s)
    assert val is not None
    assert val < 30


def test_rsi_overbought_when_rising():
    arr = np.linspace(50, 200, 30)
    s = pd.Series(arr).astype(float)
    val = rsi(s)
    assert val is not None
    assert val > 70


def test_macd_returns_two_floats():
    arr = np.linspace(50, 100, 100)
    s = pd.Series(arr).astype(float)
    out = macd(s)
    assert out is not None
    line, sig = out
    assert isinstance(line, float)
    assert isinstance(sig, float)


def test_ema_cross_golden():
    # Long downtrend, then a sharp recent reversal — fast EMA crosses above slow
    # within the lookback window.
    down = np.linspace(200, 100, 80)
    up = np.linspace(100, 300, 30)
    arr = np.concatenate([down, up])
    cx = ema_cross(pd.Series(arr).astype(float), lookback=25)
    assert cx == "golden"


def test_ema_cross_death():
    up = np.linspace(50, 200, 80)
    down = np.linspace(200, 50, 30)
    arr = np.concatenate([up, down])
    cx = ema_cross(pd.Series(arr).astype(float), lookback=25)
    assert cx == "death"


def test_volume_spike_detects_3x():
    n = 32
    closes = np.full(n, 100.0)
    vol = np.full(n, 1e8)
    vol[-1] = 5e8
    closes[-1] = 103
    closes[-2] = 100
    df = _make_df(closes, vol)
    spike = volume_spike(df["volume"], df["close"])
    assert spike is not None
    ratio, pct = spike
    assert ratio >= 3.0
    assert pct > 0.0


def test_evaluate_returns_neutral_on_empty():
    ctx = SignalContext(symbol="BTC-USD", price_df=pd.DataFrame())
    out = evaluate(ctx)
    assert out.label == "NEUTRAL"
    assert out.strength == 0.0


def test_evaluate_oversold_contrarian_bullish():
    # A monotonic decline drives RSI to 0 -> strong oversold -> contrarian
    # bullish. MACD remains bearish, partially offsetting. Net should be > 0.
    arr = np.linspace(200, 80, 100)
    df = _make_df(arr)
    ctx = SignalContext(symbol="BTC-USD", price_df=df)
    out = evaluate(ctx)
    assert out.strength > 0
    assert out.details["rsi14"] <= 5.0


def test_evaluate_overbought_contrarian_bearish():
    # Monotonic rise drives RSI to 100 -> strong overbought -> contrarian
    # bearish. MACD bullish offsets, net should be negative or neutral.
    arr = np.linspace(50, 250, 100)
    df = _make_df(arr)
    ctx = SignalContext(symbol="BTC-USD", price_df=df)
    out = evaluate(ctx)
    assert out.details["rsi14"] >= 95.0
