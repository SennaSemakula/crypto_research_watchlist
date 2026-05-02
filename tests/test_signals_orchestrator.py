"""Orchestrator returns one entry per evaluator and isolates failures."""

from __future__ import annotations

from crypto_research_watchlist.signals import SignalContext, evaluate_all


def test_evaluate_all_returns_known_keys():
    ctx = SignalContext(symbol="BTC-USD")
    out = evaluate_all(ctx)
    assert {"technical", "funding_rate", "open_interest", "onchain", "cross_asset"} <= set(out.keys())


def test_evaluate_all_isolates_exceptions(monkeypatch):
    """Patching one evaluator to raise must not break the others."""
    from crypto_research_watchlist.signals import technical

    def boom(_ctx):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(technical, "evaluate", boom)
    out = evaluate_all(SignalContext(symbol="BTC-USD"))
    assert out["technical"].label == "NEUTRAL"
    assert "error" in out["technical"].details
    # Other evaluators still ran.
    assert "funding_rate" in out
