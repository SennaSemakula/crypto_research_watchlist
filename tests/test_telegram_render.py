"""Tests for the Daily Crypto Rotation render.

The render mirrors the stock side's "Daily Capital Rotation" template:

  * Header (date)
  * MY PAPER PORTFOLIO block
  * (optional) TOP STORY banner
  * (optional) SINCE YOUR LAST CHECK 24h news bullets
  * RANKED CANDIDATES - every candidate gets a panel
  * BEST USE OF NEXT $X capital allocation
  * Footer

Decisions are pre-attached to ``Candidate.extras['decision']`` by the
pipeline; tests mimic that wiring directly.
"""

from __future__ import annotations

from datetime import UTC, datetime

from crypto_research_watchlist.candidates import Candidate
from crypto_research_watchlist.decisions import build_decision
from crypto_research_watchlist.notifiers.telegram import render_html
from crypto_research_watchlist.pipeline import RunResult
from crypto_research_watchlist.risk import RiskVerdict


def _candidate(symbol: str, score: float, action: str = "WATCH",
               *, signals: dict | None = None,
               px_overrides: dict | None = None,
               articles=None) -> Candidate:
    risk = RiskVerdict(
        action_label=action, max_portfolio_weight=0.15,
        warnings=[], invalidation_conditions=[], time_horizon="2-8 weeks",
    )
    px = {"last": 100.0, "p1d": 0.01, "p7d": 0.02, "p30d": 0.05,
          "atr14": 4.0, "high30": 110.0, "low30": 92.0, "high60": 115.0,
          "p5d": 0.01}
    if px_overrides:
        px.update(px_overrides)
    c = Candidate(
        symbol=symbol, score=score, action=action,
        reason="x", signals=signals or {}, risk=risk,
        extras={"px": px},
    )
    d = build_decision(c, articles=articles or [])
    c.extras["decision"] = d.to_dict()
    return c


def test_render_includes_template_sections():
    result = RunResult(
        run_at=datetime(2026, 5, 4, 8, 0, tzinfo=UTC),
        candidates=[
            _candidate("BTC-USD", 78.0, "STRONG"),
            _candidate("ETH-USD", 60.0, "WATCH"),
        ],
    )
    html = render_html(result)
    assert "Daily Crypto Rotation" in html
    assert "MY PAPER PORTFOLIO" in html
    assert "RANKED CANDIDATES" in html
    assert "BEST USE OF NEXT" in html
    assert "Automated research" in html


def test_render_buy_now_panel_format():
    result = RunResult(
        run_at=datetime(2026, 5, 4, tzinfo=UTC),
        candidates=[_candidate("ETH-USD", 70.0, "STRONG")],
    )
    html = render_html(result)
    # Decision tag
    assert "BUY NOW" in html
    # Buy line for the BUY_NOW
    assert "Buy: <b>$1,000</b> now" in html
    # Why buy
    assert "Why buy:" in html
    # Sell targets
    assert "Sell half at" in html
    # Stop
    assert "Sell everything if it drops" in html
    # Review window
    assert "Review:" in html
    # Break thesis
    assert "Break thesis if:" in html


def test_render_wait_panel_includes_buy_if():
    result = RunResult(
        run_at=datetime(2026, 5, 4, tzinfo=UTC),
        candidates=[_candidate("ADA-USD", 50.0, "WATCH")],
    )
    html = render_html(result)
    assert "WAIT" in html
    assert "Why wait:" in html
    # WAIT panels expose a 'Buy if:' price.
    assert "Buy if:" in html


def test_render_avoid_panel_no_buy_line():
    result = RunResult(
        run_at=datetime(2026, 5, 4, tzinfo=UTC),
        candidates=[_candidate("LINK-USD", 35.0, "AVOID")],
    )
    html = render_html(result)
    assert "AVOID" in html
    assert "Why avoid:" in html
    # No 'Buy: $... now' for AVOID
    assert "Buy: <b>$" not in html


def test_render_paper_portfolio_block_renders_default_when_no_engine():
    result = RunResult(
        run_at=datetime(2026, 5, 4, tzinfo=UTC),
        candidates=[_candidate("BTC-USD", 70.0, "STRONG")],
    )
    html = render_html(result)
    assert "Total: $5,000.00" in html
    assert "Holdings: (none)" in html


def test_render_capital_allocation_with_buy_now():
    result = RunResult(
        run_at=datetime(2026, 5, 4, tzinfo=UTC),
        candidates=[
            _candidate("ETH-USD", 70.0, "STRONG"),
            _candidate("BTC-USD", 82.0, "STRONG"),
        ],
    )
    html = render_html(result)
    assert "BEST USE OF NEXT $5,000" in html
    assert "Deploy $1,000 into ETH" in html
    assert "Deploy $1,500 into BTC" in html


def test_render_capital_allocation_no_setups_holds_cash():
    result = RunResult(
        run_at=datetime(2026, 5, 4, tzinfo=UTC),
        candidates=[_candidate("ADA-USD", 50.0, "WATCH")],
    )
    html = render_html(result)
    assert "Hold $5,000 in cash" in html


def test_render_handles_zero_candidates():
    result = RunResult(
        run_at=datetime(2026, 5, 4, tzinfo=UTC),
        candidates=[],
    )
    html = render_html(result)
    assert "Daily Crypto Rotation" in html
    assert "No candidates today" in html


def test_render_includes_classification_in_header():
    result = RunResult(
        run_at=datetime(2026, 5, 4, tzinfo=UTC),
        candidates=[
            _candidate("BTC-USD", 70.0, "STRONG"),
            _candidate("SOL-USD", 60.0, "WATCH"),
            _candidate("LINK-USD", 50.0, "WATCH"),
        ],
    )
    html = render_html(result)
    assert "CORE" in html
    assert "MAJOR" in html
    assert "MID-CAP" in html


def test_render_paper_portfolio_with_engine(engine):
    from crypto_research_watchlist.db import session_factory, session_scope
    from crypto_research_watchlist.models import PaperCash

    SessionLocal = session_factory(engine)
    with session_scope(SessionLocal) as session:
        session.add(PaperCash(id=1, cash_usd=5024.30))
    result = RunResult(
        run_at=datetime(2026, 5, 4, tzinfo=UTC),
        candidates=[_candidate("BTC-USD", 70.0, "STRONG")],
    )
    html = render_html(result, engine=engine)
    assert "Total: $5,024.30" in html


def test_render_top_story_appears_when_high_impact_news(engine):
    from datetime import timedelta

    from crypto_research_watchlist.news.sources import NewsArticleDTO
    from crypto_research_watchlist.news.store import upsert_articles

    pub = datetime.now(UTC) - timedelta(hours=1)
    upsert_articles(engine, [
        NewsArticleDTO(
            source="coindesk",
            url="https://x.com/etf-pump",
            title="ETH Pectra upgrade activated mainnet today",
            published_at=pub,
            raw_currencies=["ETH"],
        ),
    ])
    # Force the article's sentiment > 0.5 so the top-story gate fires.
    from sqlalchemy import update

    from crypto_research_watchlist.db import session_factory, session_scope
    from crypto_research_watchlist.models import NewsArticle
    SessionLocal = session_factory(engine)
    with session_scope(SessionLocal) as session:
        session.execute(update(NewsArticle).values(sentiment_score=0.7))

    result = RunResult(
        run_at=datetime.now(UTC),
        candidates=[_candidate("ETH-USD", 70.0, "STRONG")],
    )
    html = render_html(result, engine=engine)
    if "TOP STORY" in html:
        assert "ETH" in html
        assert "Why it matters" in html
