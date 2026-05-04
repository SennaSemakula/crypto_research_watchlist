"""Notifier tests: disabled by default, HTML escaping correct."""

from __future__ import annotations

from datetime import UTC, datetime

from crypto_research_watchlist.candidates import Candidate
from crypto_research_watchlist.decisions import build_decision
from crypto_research_watchlist.notifiers.telegram import (
    TelegramNotifier,
    _escape,
    _render_html,
)
from crypto_research_watchlist.pipeline import RunResult
from crypto_research_watchlist.risk import RiskVerdict


def test_telegram_disabled_by_default(cfg_demo, env_demo):
    nt = TelegramNotifier(cfg_demo, env_demo)
    out = nt.send(RunResult(run_at=datetime.now(UTC)))
    assert out.status == "disabled"


def test_html_escape_basic():
    assert _escape("a & b < c > d") == "a &amp; b &lt; c &gt; d"


def _decorate(c: Candidate) -> Candidate:
    if "px" not in c.extras:
        c.extras["px"] = {"last": 100.0, "atr14": 4.0,
                          "p1d": 0.0, "p7d": 0.0, "p30d": 0.0,
                          "high30": 110.0, "low30": 92.0, "high60": 115.0}
    c.extras["decision"] = build_decision(c, articles=[]).to_dict()
    return c


def test_render_html_includes_top_candidates():
    """Render names every candidate in the RANKED CANDIDATES block."""
    risk = RiskVerdict(action_label="WATCH", max_portfolio_weight=0.1,
                       warnings=[], invalidation_conditions=[], time_horizon="n/a")
    candidates = [
        _decorate(Candidate(symbol="BTC-USD", score=78.0, action="STRONG",
                            reason="x", risk=risk, extras={})),
        _decorate(Candidate(symbol="ETH-USD", score=65.0, action="WATCH",
                            reason="y", risk=risk, extras={})),
    ]
    result = RunResult(run_at=datetime(2026, 1, 1, tzinfo=UTC), candidates=candidates)
    html = _render_html(result)
    assert "BTC" in html
    assert "ETH" in html
    assert "Daily Crypto Rotation" in html
    assert "RANKED CANDIDATES" in html
