"""Paper-trading runner: target selection + idempotent submission."""

from __future__ import annotations

from crypto_research_watchlist.autotrader.paper_broker import PaperBroker
from crypto_research_watchlist.autotrader.runner import RunnerOutcome, run, select_targets
from crypto_research_watchlist.candidates import Candidate
from crypto_research_watchlist.risk import RiskVerdict


def _candidate(symbol: str, action: str, score: float) -> Candidate:
    verdict = RiskVerdict(
        action_label=action,
        max_portfolio_weight=0.30,
        warnings=[],
        invalidation_conditions=[],
        time_horizon="2-8 weeks",
    )
    return Candidate(symbol=symbol, score=score, action=action, reason="x", risk=verdict)


def test_select_targets_picks_strong_only(cfg_demo):
    ranked = [
        _candidate("BTC-USD", "STRONG", 0.7),
        _candidate("ETH-USD", "WATCH", 0.4),
        _candidate("SOL-USD", "AVOID", -0.5),
    ]
    out = select_targets(cfg_demo, ranked)
    assert [c.symbol for c in out] == ["BTC-USD"]


def test_runner_buys_target_and_skips_avoid(cfg_demo, engine):
    prices = {"BTC-USD": 50000.0, "ETH-USD": 3000.0, "SOL-USD": 100.0}
    broker = PaperBroker(engine, quote_fn=lambda s: prices.get(s), starting_cash=5000)
    ranked = [
        _candidate("BTC-USD", "STRONG", 0.7),
        _candidate("ETH-USD", "AVOID", -0.5),
    ]
    out = run(cfg_demo, broker, lambda s: prices.get(s), ranked)
    assert isinstance(out, RunnerOutcome)
    placed_syms = [r.symbol for r in out.placed]
    assert "BTC-USD" in placed_syms
    assert "ETH-USD" not in placed_syms


def test_runner_is_idempotent_within_same_run(cfg_demo, engine):
    prices = {"BTC-USD": 50000.0}
    broker = PaperBroker(engine, quote_fn=lambda s: prices.get(s), starting_cash=5000)
    ranked = [_candidate("BTC-USD", "STRONG", 0.7)]
    from datetime import datetime, timezone
    run_dt = datetime(2026, 5, 2, tzinfo=timezone.utc)
    a = run(cfg_demo, broker, lambda s: prices.get(s), ranked, run_dt=run_dt)
    b = run(cfg_demo, broker, lambda s: prices.get(s), ranked, run_dt=run_dt)
    assert any(r.status == "FILLED" for r in a.placed)
    # Second run should not re-buy (already held), and should produce no new
    # FILLED orders for BTC.
    new_btc_fills = [r for r in b.placed if r.symbol == "BTC-USD" and r.status == "FILLED"]
    assert new_btc_fills == []
