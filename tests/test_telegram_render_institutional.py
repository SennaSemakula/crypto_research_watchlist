"""Tests for the institutional-voice render shape + should_send daily gate.

Covers:
  * The new render is materially shorter on neutral days than the old one.
  * should_send_daily suppresses messages when nothing material has changed
    since yesterday's run.
  * should_send_daily returns True when top-3 changes, when a score moves
    by more than the tolerance, when a bucket boundary is crossed, or on
    the first run (no prior snapshot).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from crypto_research_watchlist.candidates import Candidate
from crypto_research_watchlist.notifiers.telegram import (
    render_html,
    should_send_daily,
)
from crypto_research_watchlist.pipeline import RunResult
from crypto_research_watchlist.risk import RiskVerdict


def _cand(sym: str, score: float, action: str) -> Candidate:
    return Candidate(
        symbol=sym, score=score, action=action,
        reason="x",
        signals={},
        risk=RiskVerdict(action_label=action, max_portfolio_weight=0.1,
                         warnings=[], invalidation_conditions=[], time_horizon="n/a"),
        extras={"px": {"last": 100.0, "p1d": 0.0, "p7d": 0.0, "p30d": 0.0,
                       "atr14": 1.0, "high30": 110.0, "low30": 90.0}},
    )


def test_render_today_neutral_cluster_is_under_25_lines():
    """The 'all NEUTRAL' day is the failure mode the old render padded."""
    candidates = [
        _cand("BTC-USD", 50.6, "WATCH"),
        _cand("ETH-USD", 55.2, "WATCH"),
        _cand("SOL-USD", 46.0, "WATCH"),
        _cand("BNB-USD", 49.0, "WATCH"),
        _cand("XRP-USD", 52.0, "WATCH"),
        _cand("ADA-USD", 50.1, "WATCH"),
        _cand("AVAX-USD", 48.0, "WATCH"),
        _cand("DOT-USD", 47.0, "WATCH"),
        _cand("LINK-USD", 43.0, "AVOID"),
        _cand("MATIC-USD", 44.0, "AVOID"),
    ]
    result = RunResult(
        run_at=datetime(2026, 5, 3, 8, 0, tzinfo=UTC),
        candidates=candidates,
    )
    html = render_html(result)
    n_lines = len(html.splitlines())
    assert n_lines <= 25, f"neutral render too long: {n_lines} lines\n{html}"


# ---------------------------------------------------------------------------
# should_send_daily
# ---------------------------------------------------------------------------


def _seed_prior_snapshot(engine, *, run_at, rows):
    """Insert a prior CandidateRecord run."""
    from crypto_research_watchlist.db import session_factory, session_scope
    from crypto_research_watchlist.models import CandidateRecord

    SessionLocal = session_factory(engine)
    with session_scope(SessionLocal) as session:
        for sym, score, action in rows:
            session.add(CandidateRecord(
                run_at=run_at,
                symbol=sym,
                action=action,
                score=float(score),
                reason="x",
                payload={},
            ))


def test_should_send_when_no_prior_snapshot(engine):
    candidates = [_cand("BTC-USD", 60, "WATCH")]
    send, reason = should_send_daily(engine=engine, candidates=candidates)
    assert send
    assert "no prior daily snapshot" in reason


def test_should_send_when_top3_changes(engine):
    yesterday = datetime.now(UTC) - timedelta(hours=24)
    _seed_prior_snapshot(engine, run_at=yesterday, rows=[
        ("BTC-USD", 60.0, "WATCH"),
        ("ETH-USD", 58.0, "WATCH"),
        ("SOL-USD", 55.0, "WATCH"),
    ])
    # Today: ETH leapfrogs BTC.
    candidates = [
        _cand("ETH-USD", 65.0, "WATCH"),
        _cand("BTC-USD", 60.0, "WATCH"),
        _cand("SOL-USD", 55.0, "WATCH"),
    ]
    send, reason = should_send_daily(engine=engine, candidates=candidates)
    assert send
    assert "top-3" in reason


def test_should_send_when_score_moves_more_than_tolerance(engine):
    yesterday = datetime.now(UTC) - timedelta(hours=24)
    _seed_prior_snapshot(engine, run_at=yesterday, rows=[
        ("BTC-USD", 60.0, "WATCH"),
        ("ETH-USD", 55.0, "WATCH"),
    ])
    # 6pt move on BTC > 5pt tolerance.
    candidates = [
        _cand("BTC-USD", 66.0, "WATCH"),
        _cand("ETH-USD", 55.0, "WATCH"),
    ]
    send, reason = should_send_daily(engine=engine, candidates=candidates, score_tolerance=5.0)
    assert send
    assert "BTC-USD" in reason


def test_should_send_when_bucket_changes(engine):
    yesterday = datetime.now(UTC) - timedelta(hours=24)
    _seed_prior_snapshot(engine, run_at=yesterday, rows=[
        ("BTC-USD", 70.0, "WATCH"),
        ("ETH-USD", 55.0, "WATCH"),
    ])
    # BTC crosses STRONG threshold (action change).
    candidates = [
        _cand("BTC-USD", 73.0, "STRONG"),
        _cand("ETH-USD", 55.0, "WATCH"),
    ]
    send, reason = should_send_daily(engine=engine, candidates=candidates, score_tolerance=5.0)
    assert send
    # Either bucket change or score change suffices — accept either reason.
    assert "STRONG" in reason or "score" in reason or "bucket" in reason


def test_should_suppress_when_nothing_material_changed(engine):
    yesterday = datetime.now(UTC) - timedelta(hours=24)
    _seed_prior_snapshot(engine, run_at=yesterday, rows=[
        ("BTC-USD", 60.0, "WATCH"),
        ("ETH-USD", 55.0, "WATCH"),
        ("SOL-USD", 50.0, "WATCH"),
    ])
    # Today: scores within 5pt, top-3 unchanged, no bucket change.
    candidates = [
        _cand("BTC-USD", 62.0, "WATCH"),
        _cand("ETH-USD", 56.0, "WATCH"),
        _cand("SOL-USD", 51.0, "WATCH"),
    ]
    send, reason = should_send_daily(engine=engine, candidates=candidates, score_tolerance=5.0)
    assert not send
    assert "no material change" in reason


def test_should_send_returns_true_on_engine_none():
    """No engine -> caller can't compare -> default to send."""
    candidates = [_cand("BTC-USD", 60, "WATCH")]
    send, reason = should_send_daily(engine=None, candidates=candidates)
    assert send
