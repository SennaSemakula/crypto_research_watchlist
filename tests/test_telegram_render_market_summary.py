"""Render tests for benchmarks block in the rotation template.

The new render surfaces market context as benchmark deltas in the
``MY PAPER PORTFOLIO`` block (``vs benchmarks: You +X.X%  ·  BTC ...``).
The full ``MarketSummary`` is no longer rendered as a regime line;
benchmarks summarise it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from crypto_research_watchlist.candidates import Candidate
from crypto_research_watchlist.data.coingecko_provider import MarketSummary
from crypto_research_watchlist.decisions import build_decision
from crypto_research_watchlist.notifiers.telegram import render_html
from crypto_research_watchlist.pipeline import RunResult
from crypto_research_watchlist.risk import RiskVerdict


def _candidate(symbol: str) -> Candidate:
    risk = RiskVerdict(
        action_label="STRONG", max_portfolio_weight=0.15,
        warnings=[], invalidation_conditions=[], time_horizon="2-8 weeks",
    )
    c = Candidate(
        symbol=symbol, score=70.0, action="STRONG",
        reason="ok",
        signals={},
        risk=risk,
        extras={"px": {"last": 100.0, "p1d": 0.0, "p7d": 0.01, "p30d": 0.05,
                       "atr14": 4.0, "high30": 110.0, "low30": 92.0,
                       "high60": 115.0}},
    )
    c.extras["decision"] = build_decision(c, articles=[]).to_dict()
    return c


def _summary(**overrides):
    base = dict(
        total_market_cap_usd=3.42e12,
        btc_dominance_pct=52.3,
        eth_dominance_pct=18.1,
        total_volume_24h_usd=1.45e11,
        fetched_at=datetime(2026, 5, 3, 12, 0, tzinfo=UTC),
    )
    base.update(overrides)
    return MarketSummary(**base)


def test_render_with_market_data_includes_benchmarks_block():
    result = RunResult(
        run_at=datetime(2026, 5, 3, 12, 0, tzinfo=UTC),
        candidates=[_candidate("BTC-USD")],
        market={
            "btc": {"last": 103200.0, "p1d": 0.012, "p7d": -0.004},
            "eth": {"last": 3840.0, "p1d": 0.009, "p7d": -0.018},
            "summary": _summary(),
        },
    )
    html = render_html(result)
    # Benchmarks line shows BTC + ETH 24h prints.
    assert "vs benchmarks" in html
    assert "BTC +1.2%" in html
    assert "ETH +0.9%" in html


def test_render_without_market_data_no_benchmarks_block():
    """When market data is absent the line is suppressed cleanly."""
    result = RunResult(
        run_at=datetime(2026, 5, 3, tzinfo=UTC),
        candidates=[_candidate("BTC-USD")],
        market={},
    )
    html = render_html(result)
    assert "vs benchmarks" not in html
    # Still renders the rest of the message.
    assert "Daily Crypto Rotation" in html
    assert "MY PAPER PORTFOLIO" in html


def test_render_partial_market_data_shows_what_it_has():
    result = RunResult(
        run_at=datetime(2026, 5, 3, tzinfo=UTC),
        candidates=[_candidate("BTC-USD")],
        market={
            "btc": {"last": 103200.0, "p1d": 0.0, "p7d": 0.0},
            "summary": None,
        },
    )
    html = render_html(result)
    # Only BTC bench is present.
    assert "BTC flat" in html or "BTC +0.0%" in html
