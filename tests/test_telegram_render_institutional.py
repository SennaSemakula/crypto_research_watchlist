"""Legacy should_send_daily gate tests.

The institutional render was replaced by the Daily Crypto Rotation
template; that surface is covered by ``test_telegram_render.py`` and
``test_telegram_render_rotation.py``. The should_send gate stays in
the module for back-compat — these tests assert it still behaves.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from crypto_research_watchlist.candidates import Candidate
from crypto_research_watchlist.notifiers.telegram import should_send_daily
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


def _seed_prior_snapshot(engine, *, run_at, rows):
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
    candidates = [
        _cand("BTC-USD", 73.0, "STRONG"),
        _cand("ETH-USD", 55.0, "WATCH"),
    ]
    send, reason = should_send_daily(engine=engine, candidates=candidates, score_tolerance=5.0)
    assert send
    assert "STRONG" in reason or "score" in reason or "bucket" in reason


def test_should_suppress_when_nothing_material_changed(engine):
    yesterday = datetime.now(UTC) - timedelta(hours=24)
    _seed_prior_snapshot(engine, run_at=yesterday, rows=[
        ("BTC-USD", 60.0, "WATCH"),
        ("ETH-USD", 55.0, "WATCH"),
        ("SOL-USD", 50.0, "WATCH"),
    ])
    candidates = [
        _cand("BTC-USD", 62.0, "WATCH"),
        _cand("ETH-USD", 56.0, "WATCH"),
        _cand("SOL-USD", 51.0, "WATCH"),
    ]
    send, reason = should_send_daily(engine=engine, candidates=candidates, score_tolerance=5.0)
    assert not send
    assert "no material change" in reason


def test_should_send_returns_true_on_engine_none():
    candidates = [_cand("BTC-USD", 60, "WATCH")]
    send, reason = should_send_daily(engine=None, candidates=candidates)
    assert send
