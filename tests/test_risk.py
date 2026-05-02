"""Risk verdict tests (0-100 score post 2026-05 migration)."""

from __future__ import annotations

from crypto_research_watchlist.risk import classify


def test_classify_no_data_returns_insufficient(cfg_demo):
    v = classify(cfg=cfg_demo, score=80.0, has_data=False)
    assert v.action_label == "INSUFFICIENT_DATA"
    assert v.max_portfolio_weight == 0.0


def test_classify_strong_passes_through(cfg_demo):
    v = classify(cfg=cfg_demo, score=78.0)
    assert v.action_label == "STRONG"
    assert v.max_portfolio_weight > 0


def test_classify_drawdown_gate_forces_avoid(cfg_demo):
    v = classify(cfg=cfg_demo, score=85.0, portfolio_drawdown_30d=-0.20)
    assert v.action_label == "AVOID"


def test_classify_high_vol_emits_warning(cfg_demo):
    v = classify(cfg=cfg_demo, score=60.0, annualised_vol=2.0)
    assert any("vol" in w.lower() for w in v.warnings)


def test_classify_neutral_score_is_watch(cfg_demo):
    v = classify(cfg=cfg_demo, score=50.0)
    assert v.action_label == "WATCH"


def test_classify_below_avoid_floor(cfg_demo):
    v = classify(cfg=cfg_demo, score=30.0)
    assert v.action_label == "AVOID"


def test_classify_legacy_aggregate_strength_kw(cfg_demo):
    """Old call sites (e.g. backtests) still pass aggregate_strength."""
    v = classify(cfg=cfg_demo, aggregate_strength=0.5)
    # 0.5 -> 75 in 0-100, which is STRONG (>=72).
    assert v.action_label == "STRONG"
