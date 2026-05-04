"""Tests for the Daily Crypto Rotation render shape + multi-part chunking."""

from __future__ import annotations

from datetime import UTC, datetime

from crypto_research_watchlist.candidates import Candidate
from crypto_research_watchlist.decisions import build_decision
from crypto_research_watchlist.notifiers.telegram import (
    _MAX_PER_MESSAGE_CHARS,
    _chunk_sections,
    render_html,
)
from crypto_research_watchlist.pipeline import RunResult
from crypto_research_watchlist.risk import RiskVerdict
from crypto_research_watchlist.signals import SignalResult


def _candidate(symbol: str, score: float, action: str = "WATCH",
               *, signals: dict | None = None,
               px_overrides: dict | None = None,
               articles=None) -> Candidate:
    risk = RiskVerdict(
        action_label=action, max_portfolio_weight=0.15,
        warnings=[], invalidation_conditions=[], time_horizon="2-8 weeks",
    )
    px = {"last": 100.0, "p1d": 0.01, "p7d": 0.02, "p30d": 0.05, "p5d": 0.01,
          "atr14": 4.0, "high30": 110.0, "low30": 92.0, "high60": 115.0}
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


def _full_universe() -> list[Candidate]:
    """10-name universe matching production."""
    return [
        _candidate("BTC-USD", 78.0, "STRONG"),
        _candidate("ETH-USD", 70.0, "STRONG"),
        _candidate("SOL-USD", 60.0, "WATCH"),
        _candidate("BNB-USD", 55.0, "WATCH"),
        _candidate("XRP-USD", 52.0, "WATCH"),
        _candidate("ADA-USD", 50.0, "WATCH"),
        _candidate("AVAX-USD", 48.0, "WATCH"),
        _candidate("DOT-USD", 47.0, "WATCH"),
        _candidate("LINK-USD", 42.0, "AVOID"),
        _candidate("MATIC-USD", 38.0, "AVOID"),
    ]


def test_render_has_every_required_section():
    result = RunResult(
        run_at=datetime(2026, 5, 4, 8, 0, tzinfo=UTC),
        candidates=_full_universe(),
    )
    html = render_html(result)
    assert "Daily Crypto Rotation" in html
    assert "MY PAPER PORTFOLIO" in html
    assert "Holdings:" in html
    assert "RANKED CANDIDATES" in html
    assert "BEST USE OF NEXT" in html
    assert "Automated research" in html


def test_render_buy_now_panel_complete():
    result = RunResult(
        run_at=datetime(2026, 5, 4, tzinfo=UTC),
        candidates=[_candidate("BTC-USD", 82.0, "STRONG")],
    )
    html = render_html(result)
    assert "BUY NOW" in html
    # Buy line + suggested size from the conviction bucket.
    assert "Buy: <b>$1,500</b> now" in html
    # Targets, stop, review, break thesis are all rendered.
    assert "Sell half at" in html
    assert "Sell another quarter at" in html
    assert "Sell everything if it drops to" in html
    assert "Review:" in html
    assert "Break thesis if:" in html
    # CORE/MAJOR + BUY_NOW shows entry + max chase.
    assert "Entry: " in html
    assert "Max chase:" in html


def test_render_wait_panel_short_form():
    result = RunResult(
        run_at=datetime(2026, 5, 4, tzinfo=UTC),
        candidates=[_candidate("ADA-USD", 50.0, "WATCH")],
    )
    html = render_html(result)
    assert "WAIT" in html
    assert "Why wait:" in html
    # WAIT does not get a "Buy: $X now" line.
    assert "Buy: <b>$" not in html
    # WAIT shows a 'Buy if:' price.
    assert "Buy if:" in html


def test_render_capital_allocation_block_lists_buys():
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
    # Remaining cash is held.
    assert "Hold $2,500 in cash" in html


def test_render_capital_allocation_holds_cash_when_no_buys():
    result = RunResult(
        run_at=datetime(2026, 5, 4, tzinfo=UTC),
        candidates=[_candidate("ADA-USD", 50.0, "WATCH")],
    )
    html = render_html(result)
    assert "Hold $5,000 in cash" in html


def test_render_handles_zero_candidates():
    result = RunResult(run_at=datetime(2026, 5, 4, tzinfo=UTC))
    html = render_html(result)
    assert "Daily Crypto Rotation" in html
    assert "No candidates today" in html


# ---------------------------------------------------------------------------
# Multi-part chunking
# ---------------------------------------------------------------------------


def test_chunking_short_message_single_part():
    text = "hello\n\nworld"
    parts = _chunk_sections(text, limit=_MAX_PER_MESSAGE_CHARS)
    assert parts == [text]


def test_chunking_splits_on_section_boundary():
    big = ("X" * 1000) + "\n"
    text = "\n\n".join([big] * 10)
    parts = _chunk_sections(text, limit=_MAX_PER_MESSAGE_CHARS)
    assert len(parts) >= 2
    for p in parts:
        assert len(p) <= _MAX_PER_MESSAGE_CHARS or "\n\n" not in p


def test_chunking_full_universe_under_limit_or_chunked():
    """A real 10-name render should fit in <= 2-3 chunks."""
    result = RunResult(
        run_at=datetime(2026, 5, 4, tzinfo=UTC),
        candidates=_full_universe(),
    )
    html = render_html(result)
    parts = _chunk_sections(html, limit=_MAX_PER_MESSAGE_CHARS)
    assert 1 <= len(parts) <= 5
    for p in parts:
        # Every part should be at or under the limit.
        assert len(p) <= _MAX_PER_MESSAGE_CHARS


def test_render_classification_for_btc_eth_is_core():
    result = RunResult(
        run_at=datetime(2026, 5, 4, tzinfo=UTC),
        candidates=[_candidate("BTC-USD", 70.0, "STRONG")],
    )
    html = render_html(result)
    assert "CORE" in html


def test_render_renders_chase_trap_inline():
    cand = _candidate(
        "SOL-USD", 70.0, "STRONG",
        px_overrides={"p7d": 0.30, "p5d": 0.30},
    )
    result = RunResult(run_at=datetime(2026, 5, 4, tzinfo=UTC), candidates=[cand])
    html = render_html(result)
    assert "CHASE" in html


def test_render_signals_in_technical_summary():
    tech = SignalResult(
        source="technical", strength=-0.3, label="BEARISH",
        bullets=["MACD below signal and negative: bearish momentum"],
        details={"rsi14": 28.0, "macd": {"line": -1.0, "signal": -0.5}},
    )
    cand = _candidate("SOL-USD", 60.0, "WATCH", signals={"technical": tech})
    result = RunResult(run_at=datetime(2026, 5, 4, tzinfo=UTC), candidates=[cand])
    html = render_html(result)
    assert "RSI 28" in html
    assert "MACD" in html
