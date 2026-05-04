"""Smoke tests. Keep this green at all times — the routines guard on it.

Tests intentionally do not hit the network: they exercise import paths,
config loading, and the gate logic on synthetic panels.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_package_imports():
    import crypto_research_watchlist  # noqa: F401
    from crypto_research_watchlist.autotrader import aggressive, config  # noqa: F401


def test_config_loads():
    from crypto_research_watchlist.autotrader.config import load_config

    cfg = load_config(ROOT / "config.yml")
    assert len(cfg.universe.symbols) == 10
    assert "BTC-USD" in cfg.universe.symbols
    assert "ETH-USD" in cfg.universe.symbols
    # Crypto chase-trap is meaningfully looser than stocks (15%).
    assert cfg.aggressive.chase_trap_5d_pct >= 0.20
    assert cfg.aggressive.momentum_lookback_days >= 30


def test_chase_trap_blocks_high_5d_move():
    from crypto_research_watchlist.autotrader.aggressive import classify
    from crypto_research_watchlist.autotrader.config import AggressiveConfig

    cfg = AggressiveConfig()
    panel = {"r5d": 0.50, "r1d": 0.05, "r60d": 0.80}
    decision = classify("SOL-USD", panel, cfg)
    assert decision.action == "AVOID"
    assert "chase-trap" in decision.reason


def test_strong_momentum_classifies_strong():
    from crypto_research_watchlist.autotrader.aggressive import classify
    from crypto_research_watchlist.autotrader.config import AggressiveConfig

    cfg = AggressiveConfig()
    panel = {"r5d": 0.05, "r1d": 0.01, "r60d": 0.35}
    assert classify("ETH-USD", panel, cfg).action == "STRONG"


def test_low_momentum_classifies_avoid():
    from crypto_research_watchlist.autotrader.aggressive import classify
    from crypto_research_watchlist.autotrader.config import AggressiveConfig

    cfg = AggressiveConfig()
    panel = {"r5d": 0.02, "r1d": 0.001, "r60d": -0.05}
    assert classify("BTC-USD", panel, cfg).action == "AVOID"


def test_rotate_decision_score_gap():
    from crypto_research_watchlist.autotrader.aggressive import rotate_decision
    from crypto_research_watchlist.autotrader.config import AggressiveConfig

    cfg = AggressiveConfig()
    out = rotate_decision(
        "BTC-USD", "SOL-USD",
        holding_signals={"score": 60, "r5d": 0.0, "rank_now": 1, "rank_at_entry": 1},
        candidate_signals={"score": 80},
        cfg=cfg,
    )
    assert out.rotate is True


def test_rotate_decision_no_trigger():
    from crypto_research_watchlist.autotrader.aggressive import rotate_decision
    from crypto_research_watchlist.autotrader.config import AggressiveConfig

    cfg = AggressiveConfig()
    out = rotate_decision(
        "BTC-USD", "SOL-USD",
        holding_signals={"score": 70, "r5d": 0.05, "rank_now": 1, "rank_at_entry": 1},
        candidate_signals={"score": 72},
        cfg=cfg,
    )
    assert out.rotate is False


def test_funding_signal_returns_none_for_now():
    """Placeholder — when ccxt wiring lands, this test gets retired."""
    from crypto_research_watchlist.autotrader.aggressive import funding_signal

    assert funding_signal("BTC-USD") is None


def test_no_stablecoins_in_universe():
    from crypto_research_watchlist.autotrader.config import load_config

    cfg = load_config(ROOT / "config.yml")
    forbidden = {"USDT", "USDC", "DAI", "BUSD", "TUSD", "USDP"}
    for sym in cfg.universe.symbols:
        base = sym.split("-")[0]
        assert base not in forbidden, f"stablecoin {sym} in universe"
