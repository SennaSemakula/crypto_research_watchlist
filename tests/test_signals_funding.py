"""Funding-rate evaluator tests."""

from __future__ import annotations

from crypto_research_watchlist.signals import SignalContext
from crypto_research_watchlist.signals.funding_rate import evaluate


def test_neutral_when_no_data():
    out = evaluate(SignalContext(symbol="BTC-USD"))
    assert out.label == "NEUTRAL"
    assert out.strength == 0.0


def test_extreme_positive_funding_is_bearish():
    # +0.10% per 8h, sustained
    out = evaluate(SignalContext(symbol="BTC-USD", funding_rate_history=[0.001, 0.0011, 0.0012]))
    assert out.strength < 0
    assert "over-leveraged" in out.bullets[0].lower() or "positive" in out.bullets[0].lower()


def test_extreme_negative_funding_is_bullish():
    # -0.10% per 8h, sustained
    out = evaluate(SignalContext(symbol="BTC-USD", funding_rate_history=[-0.001, -0.0011, -0.0012]))
    assert out.strength > 0


def test_mid_range_funding_is_neutral():
    out = evaluate(SignalContext(symbol="BTC-USD", funding_rate_history=[0.0001, 0.0001, 0.0001]))
    assert out.strength == 0.0
