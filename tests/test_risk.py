"""Risk verdict tests."""

from __future__ import annotations

from crypto_research_watchlist.risk import classify


def test_classify_no_data_returns_insufficient(cfg_demo):
    v = classify(cfg=cfg_demo, aggregate_strength=0.5, has_data=False)
    assert v.action_label == "INSUFFICIENT_DATA"
    assert v.max_portfolio_weight == 0.0


def test_classify_strong_passes_through(cfg_demo):
    v = classify(cfg=cfg_demo, aggregate_strength=0.7)
    assert v.action_label == "STRONG"
    assert v.max_portfolio_weight > 0


def test_classify_drawdown_gate_forces_avoid(cfg_demo):
    v = classify(cfg=cfg_demo, aggregate_strength=0.8, portfolio_drawdown_30d=-0.20)
    assert v.action_label == "AVOID"


def test_classify_high_vol_emits_warning(cfg_demo):
    v = classify(cfg=cfg_demo, aggregate_strength=0.4, annualised_vol=2.0)
    assert any("vol" in w.lower() for w in v.warnings)


def test_classify_neutral_strength_is_watch(cfg_demo):
    v = classify(cfg=cfg_demo, aggregate_strength=0.0)
    assert v.action_label == "WATCH"
