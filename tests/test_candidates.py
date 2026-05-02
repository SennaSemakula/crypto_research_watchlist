"""Candidate generation + ranking tests (0-100 score post 2026-05)."""

from __future__ import annotations

from crypto_research_watchlist.candidates import build_candidate, rank_candidates
from crypto_research_watchlist.signals import SignalResult


def _signal(name: str, strength: float, label: str = "BULLISH", bullets=None, details=None) -> SignalResult:
    return SignalResult(
        source=name, strength=strength, label=label,
        bullets=bullets if bullets is not None else [f"bullet-{name}"],
        details=details or {"k": "v"},
    )


def test_build_candidate_returns_0_100_score(cfg_demo):
    signals = {
        "technical": _signal("technical", 0.6),
        "funding_rate": _signal("funding_rate", 0.4, details={"median_8h": -0.0006}),
        "cross_asset": _signal("cross_asset", 0.5),
    }
    c = build_candidate(
        cfg=cfg_demo, symbol="BTC-USD", signals=signals,
        annualised_vol=0.85, drawdown_30d=-0.05,
    )
    assert c.symbol == "BTC-USD"
    assert 0.0 <= c.score <= 100.0
    assert c.score > 50.0  # bullish technical + cross_asset + healthy regime
    assert c.action in {"STRONG", "WATCH"}
    assert c.reason
    # Feature breakdown is persisted on the candidate.
    assert "features" in c.extras


def test_rank_candidates_orders_by_action_then_score(cfg_demo):
    s_strong = {"technical": _signal("technical", 0.7), "cross_asset": _signal("cross_asset", 0.5)}
    s_weak = {"technical": _signal("technical", 0.0, label="NEUTRAL", bullets=[], details={})}
    a = build_candidate(cfg=cfg_demo, symbol="BTC-USD", signals=s_strong, annualised_vol=0.85)
    b = build_candidate(cfg=cfg_demo, symbol="ETH-USD", signals=s_weak)
    out = rank_candidates([b, a])
    assert out[0].symbol == "BTC-USD"


def test_no_data_marks_insufficient(cfg_demo):
    signals = {
        "technical": SignalResult(source="technical", details={"reason": "no data"}),
    }
    c = build_candidate(cfg=cfg_demo, symbol="BTC-USD", signals=signals)
    assert c.action == "INSUFFICIENT_DATA"
