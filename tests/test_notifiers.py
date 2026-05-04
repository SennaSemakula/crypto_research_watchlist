"""Notifier tests: disabled by default, HTML escaping correct."""

from __future__ import annotations

from datetime import UTC, datetime

from crypto_research_watchlist.candidates import Candidate
from crypto_research_watchlist.notifiers.telegram import TelegramNotifier, _escape, _render_html
from crypto_research_watchlist.pipeline import RunResult


def test_telegram_disabled_by_default(cfg_demo, env_demo):
    nt = TelegramNotifier(cfg_demo, env_demo)
    out = nt.send(RunResult(run_at=datetime.now(UTC)))
    assert out.status == "disabled"


def test_html_escape_basic():
    assert _escape("a & b < c > d") == "a &amp; b &lt; c &gt; d"


def test_render_html_includes_top_candidates():
    """The institutional render names the closest-to-action candidate."""
    result = RunResult(
        run_at=datetime(2026, 1, 1, tzinfo=UTC),
        candidates=[
            Candidate(symbol="BTC-USD", score=78.0, action="STRONG", reason="bullets here"),
            Candidate(symbol="ETH-USD", score=65.0, action="WATCH", reason="watch reason"),
        ],
    )
    html = _render_html(result)
    assert "BTC" in html
    assert "ETH" in html
    assert "Crypto Daily" in html
    assert "Today's read" in html
