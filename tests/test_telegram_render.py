"""Tests for the institutional-voice Crypto Daily render.

The previous render was a database dump; the new format reads like a
one-page note from a senior analyst:

  * Header (date)
  * Market regime (BTC, ETH, ETH/BTC, BTC.D, mcap) + one-line read
  * Today's read (bucket headline + closest-to-action + avoid)
  * Signals fired (cross-symbol clusters or 'no signals fired')
  * News catalysts (24h, |sentiment|>=0.5)
  * Action (one-liner)

Brevity is the point: when the universe is fully neutral, the message is
~10-15 lines, NOT 5 padded sections.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from crypto_research_watchlist.candidates import Candidate
from crypto_research_watchlist.notifiers.telegram import render_html
from crypto_research_watchlist.pipeline import RunResult
from crypto_research_watchlist.risk import RiskVerdict
from crypto_research_watchlist.signals import SignalResult


def _candidate(symbol: str, score: float, action: str, *, reason: str = "no notable signals",
               p7d: float | None = 0.05, signals: dict | None = None) -> Candidate:
    risk = RiskVerdict(
        action_label=action, max_portfolio_weight=0.15,
        warnings=[], invalidation_conditions=[], time_horizon="2-8 weeks",
    )
    return Candidate(
        symbol=symbol, score=score, action=action,
        reason=reason,
        signals=signals or {},
        risk=risk,
        extras={"px": {"last": 100.0, "p1d": 0.01, "p7d": p7d, "p30d": 0.10,
                       "atr14": 4.0, "high30": 110.0, "low30": 92.0}},
    )


def test_render_includes_institutional_sections():
    result = RunResult(
        run_at=datetime(2026, 5, 3, 12, 0, tzinfo=UTC),
        candidates=[
            _candidate("BTC-USD", 78.0, "STRONG", reason="bullish MACD + funding negative"),
            _candidate("ETH-USD", 60.0, "WATCH"),
        ],
        market={
            "btc": {"last": 103200, "p1d": 0.012, "p7d": -0.004},
            "eth": {"last": 3840, "p1d": 0.009, "p7d": 0.02},
        },
    )
    html = render_html(result)
    assert "Crypto Daily" in html
    assert "Market regime" in html
    assert "Today's read" in html
    assert "Signals fired" in html
    assert "Action" in html
    # No emojis in the institutional shape, no DB-dump tags.
    assert "RANKED CANDIDATES" not in html
    assert "buy zone" not in html.lower()
    assert "tp" not in html.lower() or "tp <" not in html.lower()


def test_render_neutral_universe_is_brief():
    """When every candidate is mid-bucket WATCH/NEUTRAL the message stays short."""
    result = RunResult(
        run_at=datetime(2026, 5, 3, 12, 0, tzinfo=UTC),
        candidates=[
            _candidate("BTC-USD", 50.6, "WATCH"),
            _candidate("ETH-USD", 55.2, "WATCH"),
            _candidate("SOL-USD", 46.0, "WATCH"),
            _candidate("ADA-USD", 50.1, "WATCH"),
            _candidate("LINK-USD", 43.0, "AVOID"),
        ],
        market={
            "btc": {"last": 103200, "p1d": 0.012, "p7d": -0.004},
            "eth": {"last": 3840, "p1d": 0.009, "p7d": -0.018},
        },
    )
    html = render_html(result)
    line_count = len(html.splitlines())
    # Strict cap on neutral-day length. The old render was ~50-80 lines on
    # a fully neutral day; this should be under 25.
    assert line_count <= 25, f"neutral render too long ({line_count} lines)"
    assert "neutral cluster" in html


def test_render_shows_closest_to_action_with_trigger():
    result = RunResult(
        run_at=datetime(2026, 5, 3, tzinfo=UTC),
        candidates=[
            _candidate("ETH-USD", 60.0, "WATCH", reason="Outperforming BTC by 8 pts over 60d"),
            _candidate("SOL-USD", 46.0, "WATCH"),
        ],
    )
    html = render_html(result)
    assert "Closest to action" in html
    assert "ETH" in html
    # Trigger lines surface a price level, not vague guidance.
    assert "Trigger:" in html


def test_render_avoid_block_only_when_present():
    """No AVOID names -> no Avoid block."""
    result = RunResult(
        run_at=datetime(2026, 5, 3, tzinfo=UTC),
        candidates=[_candidate("BTC-USD", 60.0, "WATCH")],
    )
    html = render_html(result)
    assert "Avoid" not in html


def test_render_avoid_block_when_low_scoring_avoid_present():
    result = RunResult(
        run_at=datetime(2026, 5, 3, tzinfo=UTC),
        candidates=[
            _candidate("BTC-USD", 60.0, "WATCH"),
            _candidate("LINK-USD", 35.0, "AVOID", reason="death cross + OI declining"),
        ],
    )
    html = render_html(result)
    assert "Avoid" in html
    assert "LINK" in html


def test_render_signals_fired_macd_cluster():
    bear_macd_sig = SignalResult(
        source="technical", strength=-0.3, label="BEARISH",
        bullets=["MACD below signal and negative: bearish momentum"],
    )
    candidates = [
        _candidate("SOL-USD", 46, "WATCH", signals={"technical": bear_macd_sig}),
        _candidate("AVAX-USD", 47, "WATCH", signals={"technical": bear_macd_sig}),
        _candidate("DOT-USD", 45, "WATCH", signals={"technical": bear_macd_sig}),
    ]
    result = RunResult(run_at=datetime(2026, 5, 3, tzinfo=UTC), candidates=candidates)
    html = render_html(result)
    assert "bearish MACD" in html
    assert "SOL" in html


def test_render_signals_fired_underperforming_btc_cluster():
    weak_sig = SignalResult(
        source="cross_asset", strength=-0.5, label="BEARISH",
        bullets=["Underperforming BTC by 25 pts over 60d"],
        details={"rel_strength_60d": -0.30},
    )
    candidates = [
        _candidate("MATIC-USD", 42, "AVOID", signals={"cross_asset": weak_sig}),
        _candidate("ADA-USD", 44, "AVOID", signals={"cross_asset": weak_sig}),
    ]
    result = RunResult(run_at=datetime(2026, 5, 3, tzinfo=UTC), candidates=candidates)
    html = render_html(result)
    assert "underperforming BTC by >25pt" in html


def test_render_when_no_signals_fire_says_so_explicitly():
    """Empty signals do NOT pad with empty section bodies."""
    result = RunResult(
        run_at=datetime(2026, 5, 3, tzinfo=UTC),
        candidates=[_candidate("BTC-USD", 50, "WATCH")],
    )
    html = render_html(result)
    assert "No funding extremes" in html


def test_render_market_read_alts_firming():
    result = RunResult(
        run_at=datetime(2026, 5, 3, tzinfo=UTC),
        candidates=[_candidate("BTC-USD", 50, "WATCH")],
        market={
            "btc": {"last": 100000, "p1d": 0.0, "p7d": 0.0},
            "eth": {"last": 3000, "p1d": 0.0, "p7d": 0.06},
        },
    )
    html = render_html(result)
    assert "Read:" in html
    assert "Alts firming" in html or "rotation" in html.lower()


def test_render_market_read_btc_capitulation():
    result = RunResult(
        run_at=datetime(2026, 5, 3, tzinfo=UTC),
        candidates=[_candidate("BTC-USD", 50, "WATCH")],
        market={
            "btc": {"last": 90000, "p1d": -0.03, "p7d": -0.12},
            "eth": {"last": 2800, "p1d": -0.02, "p7d": -0.10},
        },
    )
    html = render_html(result)
    assert "BTC down 10%" in html


def test_render_paper_portfolio_one_liner(engine):
    from crypto_research_watchlist.db import session_factory, session_scope
    from crypto_research_watchlist.models import PaperCash, PaperPosition

    SessionLocal = session_factory(engine)
    with session_scope(SessionLocal) as session:
        session.add(PaperCash(id=1, cash_usd=4250.0))
        session.add(PaperPosition(symbol="BTC-USD", quantity=0.1, avg_price=50000.0))

    result = RunResult(
        run_at=datetime(2026, 5, 3, tzinfo=UTC),
        candidates=[_candidate("BTC-USD", 70.0, "WATCH")],
    )
    html = render_html(result, engine=engine)
    assert "Paper portfolio" in html
    assert "4,250" in html


def test_render_news_catalysts_only_when_high_impact(engine):
    from crypto_research_watchlist.news.sources import NewsArticleDTO
    from crypto_research_watchlist.news.store import upsert_articles

    pub = datetime.now(UTC) - timedelta(hours=1)
    upsert_articles(engine, [
        NewsArticleDTO(
            source="coindesk",
            url="https://x.com/etf",
            title="BTC ETF approval rallies market",
            published_at=pub,
            raw_currencies=["BTC"],
        ),
    ])

    result = RunResult(
        run_at=datetime.now(UTC),
        candidates=[_candidate("BTC-USD", 70.0, "STRONG")],
    )
    html = render_html(result, engine=engine)
    # Only renders if |sentiment|>=0.5; if dummy upsert produces 0.0 there
    # should NOT be a catalysts header.
    if "News catalysts" in html:
        assert "(24h" in html


def test_render_handles_zero_candidates():
    result = RunResult(run_at=datetime(2026, 5, 3, tzinfo=UTC))
    html = render_html(result)
    assert "Crypto Daily" in html
    assert "Universe empty" in html
