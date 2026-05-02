"""Candidate generation + ranking tests."""

from __future__ import annotations

from crypto_research_watchlist.candidates import build_candidate, rank_candidates
from crypto_research_watchlist.signals import SignalResult


def _signal(name: str, strength: float, label: str = "BULLISH", bullets=None) -> SignalResult:
    return SignalResult(source=name, strength=strength, label=label, bullets=bullets or [f"bullet-{name}"])


def test_build_candidate_aggregates_score(cfg_demo):
    signals = {
        "technical": _signal("technical", 0.6),
        "funding_rate": _signal("funding_rate", 0.4),
        "open_interest": _signal("open_interest", 0.0, label="NEUTRAL", bullets=[]),
    }
    c = build_candidate(cfg=cfg_demo, symbol="BTC-USD", signals=signals)
    assert c.symbol == "BTC-USD"
    assert c.score > 0
    assert c.action in {"STRONG", "WATCH"}
    assert c.reason  # has at least one bullet


def test_rank_candidates_orders_by_action_then_score(cfg_demo):
    s_strong = {"technical": _signal("technical", 0.7)}
    s_weak = {"technical": _signal("technical", 0.1, label="NEUTRAL", bullets=[])}
    a = build_candidate(cfg=cfg_demo, symbol="BTC-USD", signals=s_strong)
    b = build_candidate(cfg=cfg_demo, symbol="ETH-USD", signals=s_weak)
    out = rank_candidates([b, a])
    assert out[0].symbol == "BTC-USD"
