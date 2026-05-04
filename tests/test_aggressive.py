"""Tests for the aggressive rotation engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from crypto_research_watchlist.autotrader.aggressive import (
    AggressiveAction,
    build_aggressive_context,
    evaluate_aggressive,
    persist_aggressive_decisions,
)
from crypto_research_watchlist.config import load_app_config


@dataclass
class _StubCandidate:
    symbol: str
    score: float
    action: str
    extras: dict = field(default_factory=dict)
    signals: dict = field(default_factory=dict)
    reason: str = ""


@dataclass
class _StubResult:
    candidates: list[_StubCandidate]
    market: dict = field(default_factory=dict)


def _px(*, p1d: float = 0.0, p7d: float = 0.0, p30d: float = 0.0, last: float = 100.0) -> dict:
    return {"p1d": p1d, "p7d": p7d, "p30d": p30d, "last": last, "high30": last * 1.05}


# ---- Chase-trap gate -------------------------------------------------------

def test_chase_trap_5d_triggers_do_not_chase():
    cfg = load_app_config()
    candidate = _StubCandidate(
        symbol="SOL-USD", score=0.7, action="STRONG",
        extras={"px": _px(p1d=0.05, p7d=0.40)},  # +40% 5d (we use p7d as r5d)
    )
    result = _StubResult(candidates=[candidate])
    ctx = build_aggressive_context(run_result=result)
    report = evaluate_aggressive(cfg=cfg.crypto, ctx=ctx)
    assert report.decisions[0].action == AggressiveAction.DO_NOT_CHASE


def test_chase_trap_1d_triggers_do_not_chase():
    cfg = load_app_config()
    candidate = _StubCandidate(
        symbol="SOL-USD", score=0.7, action="STRONG",
        extras={"px": _px(p1d=0.20, p7d=0.10)},  # +20% 1d (above 18% guard)
    )
    result = _StubResult(candidates=[candidate])
    ctx = build_aggressive_context(run_result=result)
    report = evaluate_aggressive(cfg=cfg.crypto, ctx=ctx)
    assert report.decisions[0].action == AggressiveAction.DO_NOT_CHASE


def test_no_chase_when_returns_below_thresholds():
    cfg = load_app_config()
    candidate = _StubCandidate(
        symbol="BTC-USD", score=0.7, action="STRONG",
        extras={"px": _px(p1d=0.05, p7d=0.10, p30d=0.30)},
    )
    result = _StubResult(candidates=[candidate])
    ctx = build_aggressive_context(run_result=result)
    report = evaluate_aggressive(cfg=cfg.crypto, ctx=ctx)
    assert report.decisions[0].action != AggressiveAction.DO_NOT_CHASE


# ---- Cooldown --------------------------------------------------------------

def test_cooldown_blocks_recent_chase_trap():
    cfg = load_app_config()
    candidate = _StubCandidate(
        symbol="ETH-USD", score=0.7, action="STRONG",
        extras={"px": _px(p1d=0.05, p7d=0.10)},
    )
    result = _StubResult(candidates=[candidate])
    now = datetime.now(UTC)
    ctx = build_aggressive_context(
        run_result=result,
        last_chase_trap_dates={"ETH-USD": now - timedelta(days=1)},
    )
    report = evaluate_aggressive(cfg=cfg.crypto, ctx=ctx, now=now)
    assert report.decisions[0].action == AggressiveAction.COOLDOWN_HOLD


def test_cooldown_expires_after_n_days():
    cfg = load_app_config()
    candidate = _StubCandidate(
        symbol="ETH-USD", score=0.7, action="STRONG",
        extras={"px": _px(p1d=0.05, p7d=0.10, p30d=0.30)},
    )
    result = _StubResult(candidates=[candidate])
    now = datetime.now(UTC)
    ctx = build_aggressive_context(
        run_result=result,
        last_chase_trap_dates={"ETH-USD": now - timedelta(days=10)},
    )
    report = evaluate_aggressive(cfg=cfg.crypto, ctx=ctx, now=now)
    # Cooldown expired -> not COOLDOWN_HOLD
    assert report.decisions[0].action != AggressiveAction.COOLDOWN_HOLD


# ---- Rotation --------------------------------------------------------------

def test_rotate_on_score_gap():
    cfg = load_app_config()
    cfg.crypto.aggressive.rotation_score_gap = 15.0
    held = _StubCandidate(
        symbol="ETH-USD", score=0.0, action="WATCH",
        extras={"px": _px(p1d=0.0, p7d=0.0, p30d=0.05)},
    )
    new = _StubCandidate(
        symbol="SOL-USD", score=0.5, action="STRONG",
        extras={"px": _px(p1d=0.02, p7d=0.05, p30d=0.30)},
    )
    result = _StubResult(candidates=[new, held])
    ctx = build_aggressive_context(run_result=result, held_symbol="ETH-USD")
    report = evaluate_aggressive(cfg=cfg.crypto, ctx=ctx)
    actions = {d.symbol: d.action for d in report.decisions}
    assert actions["SOL-USD"] == AggressiveAction.ROTATE


def test_rotate_on_rank_drop():
    cfg = load_app_config()
    cfg.crypto.aggressive.rotation_rank_drop = 2
    held = _StubCandidate(
        symbol="ETH-USD", score=0.10, action="WATCH",
        extras={"px": _px(p1d=0.0, p7d=0.0, p30d=0.05)},
    )
    top = _StubCandidate(
        symbol="SOL-USD", score=0.20, action="STRONG",
        extras={"px": _px(p1d=0.02, p7d=0.05, p30d=0.20)},
    )
    other = _StubCandidate(
        symbol="BNB-USD", score=0.18, action="WATCH",
        extras={"px": _px(p1d=0.01, p7d=0.04, p30d=0.10)},
    )
    # Held started at rank 1, now rank 3 (drop of 2 spots).
    result = _StubResult(candidates=[top, other, held])
    ctx = build_aggressive_context(
        run_result=result, held_symbol="ETH-USD", held_rank_at_entry=1,
    )
    report = evaluate_aggressive(cfg=cfg.crypto, ctx=ctx)
    actions = {d.symbol: d.action for d in report.decisions}
    assert actions["SOL-USD"] == AggressiveAction.ROTATE


# ---- BUY / HOLD / persistence ---------------------------------------------

def test_buy_top_when_no_holding_and_strong():
    cfg = load_app_config()
    candidate = _StubCandidate(
        symbol="BTC-USD", score=0.7, action="STRONG",
        extras={"px": _px(p1d=0.01, p7d=0.05, p30d=0.20)},
    )
    result = _StubResult(candidates=[candidate])
    ctx = build_aggressive_context(run_result=result)
    report = evaluate_aggressive(cfg=cfg.crypto, ctx=ctx)
    assert report.decisions[0].action == AggressiveAction.BUY


def test_persist_writes_rows(engine):
    from sqlalchemy.orm import Session

    from crypto_research_watchlist.models import (
        AggressiveDecision as AggressiveDecisionRow,
    )

    cfg = load_app_config()
    candidate = _StubCandidate(
        symbol="BTC-USD", score=0.7, action="STRONG",
        extras={"px": _px(p1d=0.01, p7d=0.05, p30d=0.20)},
    )
    result = _StubResult(candidates=[candidate])
    ctx = build_aggressive_context(run_result=result)
    report = evaluate_aggressive(cfg=cfg.crypto, ctx=ctx)
    n = persist_aggressive_decisions(engine, datetime.now(UTC), report)
    assert n == len(report.decisions)
    with Session(engine) as s:
        rows = s.query(AggressiveDecisionRow).all()
    assert len(rows) == n
