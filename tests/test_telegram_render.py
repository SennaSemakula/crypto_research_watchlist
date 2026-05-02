"""Tests for the new Crypto Daily Watchlist Telegram render."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from crypto_research_watchlist.candidates import Candidate
from crypto_research_watchlist.notifiers.telegram import render_html
from crypto_research_watchlist.pipeline import RunResult
from crypto_research_watchlist.risk import RiskVerdict


def _candidate(symbol: str, score: float, action: str, *, p7d: float | None = 0.05) -> Candidate:
    risk = RiskVerdict(
        action_label=action, max_portfolio_weight=0.15,
        warnings=[], invalidation_conditions=[], time_horizon="2-8 weeks",
    )
    return Candidate(
        symbol=symbol, score=score, action=action,
        reason="strong tech + funding contrarian",
        signals={},
        risk=risk,
        extras={"px": {"last": 100.0, "p1d": 0.01, "p7d": p7d, "p30d": 0.10, "atr14": 4.0, "high30": 110.0}},
    )


def test_render_includes_required_sections():
    result = RunResult(
        run_at=datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc),
        candidates=[_candidate("BTC-USD", 78.0, "STRONG"), _candidate("ETH-USD", 60.0, "WATCH")],
        market={"btc": {"last": 50000, "p1d": 0.01, "p7d": 0.05}, "eth": {"last": 3000, "p1d": 0.0, "p7d": 0.02}},
    )
    html = render_html(result)
    assert "Crypto Daily Watchlist" in html
    assert "RANKED CANDIDATES" in html
    assert "BTC-USD" in html
    assert "78/100" in html
    assert "buy" in html.lower()  # buy zone line
    assert "tp" in html.lower()


def test_render_chase_trap_tag_when_7d_above_30():
    result = RunResult(
        run_at=datetime(2026, 5, 2, tzinfo=timezone.utc),
        candidates=[_candidate("SOL-USD", 75.0, "STRONG", p7d=0.35)],
    )
    html = render_html(result)
    assert "chase trap" in html


def test_render_handles_zero_candidates():
    result = RunResult(run_at=datetime(2026, 5, 2, tzinfo=timezone.utc))
    html = render_html(result)
    assert "Crypto Daily Watchlist" in html


def test_render_paper_portfolio_block(engine):
    """When the paper portfolio has cash + positions, the block shows up."""
    from crypto_research_watchlist.db import session_factory, session_scope
    from crypto_research_watchlist.models import PaperCash, PaperPosition

    SessionLocal = session_factory(engine)
    with session_scope(SessionLocal) as session:
        session.add(PaperCash(id=1, cash_usd=4250.50))
        session.add(PaperPosition(symbol="BTC-USD", quantity=0.1, avg_price=50000.0))

    result = RunResult(
        run_at=datetime(2026, 5, 2, tzinfo=timezone.utc),
        candidates=[_candidate("BTC-USD", 78.0, "STRONG")],
    )
    html = render_html(result, engine=engine)
    assert "PAPER PORTFOLIO" in html
    assert "4,250.50" in html or "4250.50" in html


def test_render_active_catalysts_section(engine):
    """When notable news exists, ACTIVE CATALYSTS block appears."""
    from crypto_research_watchlist.news.sources import NewsArticleDTO
    from crypto_research_watchlist.news.store import upsert_articles

    pub = datetime.now(timezone.utc) - timedelta(hours=2)
    upsert_articles(engine, [
        NewsArticleDTO(
            source="coindesk",
            url="https://x.com/etf",
            title="BTC ETF approval rallies market to all time high",
            published_at=pub,
            raw_currencies=["BTC"],
        ),
        NewsArticleDTO(
            source="cointelegraph",
            url="https://x.com/hack",
            title="Major exchange exploit drains $200M",
            published_at=pub,
            raw_currencies=["ETH"],
        ),
    ])

    result = RunResult(
        run_at=datetime.now(timezone.utc),
        candidates=[_candidate("BTC-USD", 70.0, "STRONG")],
    )
    html = render_html(result, engine=engine)
    assert "ACTIVE CATALYSTS" in html
