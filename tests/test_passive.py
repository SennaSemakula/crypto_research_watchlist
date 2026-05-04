"""Tests for the passive accumulation engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC

import pytest

from crypto_research_watchlist.autotrader.passive import (
    PassiveAction,
    build_passive_context,
    evaluate,
    persist_decisions,
)
from crypto_research_watchlist.config import load_app_config


@dataclass
class _StubSignal:
    label: str = "NEUTRAL"
    strength: float = 0.0
    bullets: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)
    source: str = "x"

    @property
    def is_notable(self) -> bool:
        return abs(self.strength) >= 0.3


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


def _cfg():
    cfg = load_app_config()
    cfg.crypto.universe.symbols = [
        "BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "AVAX-USD",
    ]
    return cfg


def _px(*, last: float, high30: float) -> dict:
    return {"last": last, "high30": high30, "p1d": 0.01, "p7d": 0.02, "p30d": 0.05}


# ---- Auto-buy first tranche -----------------------------------------------

def test_first_tranche_when_dip_qualifies():
    cfg = _cfg()
    candidate = _StubCandidate(
        symbol="BTC-USD", score=0.65, action="STRONG",
        extras={"px": _px(last=90.0, high30=100.0)},  # -10% dip
    )
    result = _StubResult(candidates=[candidate])
    ctx = build_passive_context(
        run_result=result, paper_cash_usd=5000.0,
        positions_by_symbol_usd={},
    )
    cfg.crypto.passive.shadow_mode = False
    report = evaluate(cfg=cfg.crypto, run_result=result, ctx=ctx)
    assert len(report.decisions) == 1
    d = report.decisions[0]
    assert d.action == PassiveAction.AUTO_BUY_FIRST_TRANCHE
    assert d.tranche_usd == pytest.approx(100.0)
    assert d.high_conviction is True


def test_shadow_mode_relabels_to_auto_buy_shadow():
    cfg = _cfg()
    cfg.crypto.passive.shadow_mode = True
    candidate = _StubCandidate(
        symbol="ETH-USD", score=0.4, action="WATCH",
        extras={"px": _px(last=88.0, high30=100.0)},  # -12% dip
    )
    result = _StubResult(candidates=[candidate])
    ctx = build_passive_context(
        run_result=result, paper_cash_usd=5000.0,
        positions_by_symbol_usd={},
    )
    report = evaluate(cfg=cfg.crypto, run_result=result, ctx=ctx)
    assert len(report.decisions) == 1
    assert report.decisions[0].action == PassiveAction.AUTO_BUY_SHADOW


def test_add_tranche_when_position_exists():
    cfg = _cfg()
    cfg.crypto.passive.shadow_mode = False
    candidate = _StubCandidate(
        symbol="SOL-USD", score=0.55, action="WATCH",
        extras={"px": _px(last=85.0, high30=100.0)},  # -15% dip
    )
    result = _StubResult(candidates=[candidate])
    ctx = build_passive_context(
        run_result=result, paper_cash_usd=5000.0,
        positions_by_symbol_usd={"SOL-USD": 250.0},
    )
    report = evaluate(cfg=cfg.crypto, run_result=result, ctx=ctx)
    d = report.decisions[0]
    assert d.action == PassiveAction.AUTO_ADD_TRANCHE


# ---- Wait / refusal cases --------------------------------------------------

def test_wait_when_dip_not_deep_enough():
    cfg = _cfg()
    candidate = _StubCandidate(
        symbol="BTC-USD", score=0.5, action="WATCH",
        extras={"px": _px(last=98.0, high30=100.0)},  # -2% dip only
    )
    result = _StubResult(candidates=[candidate])
    ctx = build_passive_context(
        run_result=result, paper_cash_usd=5000.0,
        positions_by_symbol_usd={},
    )
    report = evaluate(cfg=cfg.crypto, run_result=result, ctx=ctx)
    assert report.decisions[0].action == PassiveAction.WAIT_FOR_BETTER_PRICE


def test_do_not_buy_when_action_is_avoid():
    cfg = _cfg()
    candidate = _StubCandidate(
        symbol="BTC-USD", score=-0.5, action="AVOID",
        extras={"px": _px(last=85.0, high30=100.0)},
    )
    result = _StubResult(candidates=[candidate])
    ctx = build_passive_context(
        run_result=result, paper_cash_usd=5000.0,
        positions_by_symbol_usd={},
    )
    report = evaluate(cfg=cfg.crypto, run_result=result, ctx=ctx)
    assert report.decisions[0].action == PassiveAction.DO_NOT_BUY


def test_do_not_buy_when_symbol_outside_universe():
    cfg = _cfg()
    candidate = _StubCandidate(
        symbol="DOGE-USD", score=0.5, action="WATCH",
        extras={"px": _px(last=85.0, high30=100.0)},
    )
    result = _StubResult(candidates=[candidate])
    ctx = build_passive_context(
        run_result=result, paper_cash_usd=5000.0,
        positions_by_symbol_usd={},
    )
    report = evaluate(cfg=cfg.crypto, run_result=result, ctx=ctx)
    assert report.decisions[0].action == PassiveAction.DO_NOT_BUY


# ---- Caps + risk gates -----------------------------------------------------

def test_weekly_total_cap_enforced():
    cfg = _cfg()
    cfg.crypto.passive.shadow_mode = False
    candidate = _StubCandidate(
        symbol="BTC-USD", score=0.5, action="WATCH",
        extras={"px": _px(last=85.0, high30=100.0)},
    )
    result = _StubResult(candidates=[candidate])
    ctx = build_passive_context(
        run_result=result, paper_cash_usd=5000.0,
        positions_by_symbol_usd={},
        wtd_buys_total_usd=cfg.crypto.passive.weekly_cap_total_usd,  # exhausted
    )
    report = evaluate(cfg=cfg.crypto, run_result=result, ctx=ctx)
    assert report.decisions[0].action == PassiveAction.WAIT_FOR_BETTER_PRICE


def test_per_symbol_cap_enforced():
    cfg = _cfg()
    cfg.crypto.passive.shadow_mode = False
    candidate = _StubCandidate(
        symbol="BTC-USD", score=0.5, action="WATCH",
        extras={"px": _px(last=85.0, high30=100.0)},
    )
    result = _StubResult(candidates=[candidate])
    ctx = build_passive_context(
        run_result=result, paper_cash_usd=5000.0,
        positions_by_symbol_usd={},
        wtd_buys_per_symbol_usd={"BTC-USD": cfg.crypto.passive.weekly_cap_per_symbol_usd},
    )
    report = evaluate(cfg=cfg.crypto, run_result=result, ctx=ctx)
    assert report.decisions[0].action == PassiveAction.WAIT_FOR_BETTER_PRICE


def test_drawdown_gate_blocks_all_buys():
    cfg = _cfg()
    candidates = [
        _StubCandidate(
            symbol="BTC-USD", score=0.7, action="STRONG",
            extras={"px": _px(last=80.0, high30=100.0)},
        ),
        _StubCandidate(
            symbol="ETH-USD", score=0.6, action="STRONG",
            extras={"px": _px(last=80.0, high30=100.0)},
        ),
    ]
    result = _StubResult(candidates=candidates)
    ctx = build_passive_context(
        run_result=result, paper_cash_usd=5000.0,
        positions_by_symbol_usd={},
        portfolio_drawdown_30d=-0.20,  # below -15% gate
    )
    report = evaluate(cfg=cfg.crypto, run_result=result, ctx=ctx)
    assert all(d.action == PassiveAction.BLOCK_BUY_RISK_EVENT for d in report.decisions)
    assert report.notes  # block reason logged


def test_stablecoin_depeg_blocks_all_buys():
    cfg = _cfg()
    cross = _StubSignal(source="cross_asset", details={"stablecoin_depeg": True})
    candidate = _StubCandidate(
        symbol="BTC-USD", score=0.7, action="STRONG",
        extras={"px": _px(last=80.0, high30=100.0)},
        signals={"cross_asset": cross},
    )
    result = _StubResult(candidates=[candidate])
    ctx = build_passive_context(
        run_result=result, paper_cash_usd=5000.0,
        positions_by_symbol_usd={},
    )
    report = evaluate(cfg=cfg.crypto, run_result=result, ctx=ctx)
    assert report.decisions[0].action == PassiveAction.BLOCK_BUY_RISK_EVENT


# ---- Persistence -----------------------------------------------------------

def test_persist_decisions_writes_rows(engine):
    from datetime import datetime

    from sqlalchemy.orm import Session

    from crypto_research_watchlist.models import (
        PassiveDecision as PassiveDecisionRow,
    )

    cfg = _cfg()
    candidate = _StubCandidate(
        symbol="BTC-USD", score=0.65, action="STRONG",
        extras={"px": _px(last=90.0, high30=100.0)},
    )
    result = _StubResult(candidates=[candidate])
    ctx = build_passive_context(
        run_result=result, paper_cash_usd=5000.0,
        positions_by_symbol_usd={},
    )
    report = evaluate(cfg=cfg.crypto, run_result=result, ctx=ctx)
    n = persist_decisions(engine, datetime.now(UTC), report)
    assert n == len(report.decisions)
    with Session(engine) as s:
        rows = s.query(PassiveDecisionRow).all()
    assert len(rows) == n
    assert rows[0].symbol == "BTC-USD"
