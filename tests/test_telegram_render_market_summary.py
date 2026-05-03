"""Telegram render tests for the new CoinGecko market summary line.

Verifies that the Market block extends with a 'Total mcap / BTC.D / ETH.D'
line when result.market["summary"] is present, and renders cleanly
without that line when the summary is None.
"""

from __future__ import annotations

from datetime import datetime, timezone

from crypto_research_watchlist.candidates import Candidate
from crypto_research_watchlist.data.coingecko_provider import MarketSummary
from crypto_research_watchlist.notifiers.telegram import render_html
from crypto_research_watchlist.pipeline import RunResult
from crypto_research_watchlist.risk import RiskVerdict


def _candidate(symbol: str) -> Candidate:
    risk = RiskVerdict(
        action_label="STRONG", max_portfolio_weight=0.15,
        warnings=[], invalidation_conditions=[], time_horizon="2-8 weeks",
    )
    return Candidate(
        symbol=symbol, score=70.0, action="STRONG",
        reason="ok",
        signals={},
        risk=risk,
        extras={"px": {"last": 100.0, "p1d": 0.0, "p7d": 0.01, "p30d": 0.05, "atr14": 4.0, "high30": 110.0}},
    )


def _summary(**overrides):
    base = dict(
        total_market_cap_usd=3.42e12,
        btc_dominance_pct=52.3,
        eth_dominance_pct=18.1,
        total_volume_24h_usd=1.45e11,
        fetched_at=datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc),
    )
    base.update(overrides)
    return MarketSummary(**base)


def test_render_with_summary_includes_mcap_and_dominance():
    result = RunResult(
        run_at=datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc),
        candidates=[_candidate("BTC-USD")],
        market={
            "btc": {"last": 103200.0, "p1d": 0.012, "p7d": -0.004},
            "eth": {"last": 3840.0, "p1d": 0.009, "p7d": -0.018},
            "summary": _summary(),
        },
    )
    html = render_html(result)
    assert "Total mcap" in html
    assert "BTC.D" in html
    assert "ETH.D" in html
    assert "$3.42T" in html
    assert "52.3%" in html
    assert "18.1%" in html


def test_render_without_summary_has_no_summary_line():
    result = RunResult(
        run_at=datetime(2026, 5, 3, tzinfo=timezone.utc),
        candidates=[_candidate("BTC-USD")],
        market={
            "btc": {"last": 103200.0, "p1d": 0.012, "p7d": -0.004},
            "eth": {"last": 3840.0, "p1d": 0.009, "p7d": -0.018},
            "summary": None,
        },
    )
    html = render_html(result)
    assert "Total mcap" not in html
    assert "BTC.D" not in html
    # And the existing block still renders.
    assert "BTC $" in html
    assert "ETH/BTC" in html


def test_render_with_summary_missing_some_fields_partial_line():
    """If CoinGecko returns a partial payload, only present fields render."""
    s = _summary(eth_dominance_pct=None, total_volume_24h_usd=None)
    result = RunResult(
        run_at=datetime(2026, 5, 3, tzinfo=timezone.utc),
        candidates=[_candidate("BTC-USD")],
        market={
            "btc": {"last": 103200.0, "p1d": 0.0, "p7d": 0.0},
            "eth": {"last": 3840.0, "p1d": 0.0, "p7d": 0.0},
            "summary": s,
        },
    )
    html = render_html(result)
    assert "Total mcap" in html
    assert "BTC.D 52.3%" in html
    # ETH.D missing -> not rendered.
    assert "ETH.D" not in html


def test_render_with_no_market_no_crash():
    result = RunResult(
        run_at=datetime(2026, 5, 3, tzinfo=timezone.utc),
        candidates=[_candidate("BTC-USD")],
        market={},
    )
    html = render_html(result)
    assert "Crypto Daily Watchlist" in html
