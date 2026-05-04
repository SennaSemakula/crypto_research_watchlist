"""Tests for the per-candidate decision engine."""

from __future__ import annotations

from dataclasses import dataclass

from crypto_research_watchlist.candidates import Candidate
from crypto_research_watchlist.decisions import (
    CandidateDecision,
    attach_decisions,
    build_decision,
    classify,
    pick_decision,
    pick_tag,
)
from crypto_research_watchlist.risk import RiskVerdict
from crypto_research_watchlist.signals import SignalResult


@dataclass(slots=True)
class _Article:
    title: str
    sentiment_score: float = 0.0


def _candidate(
    symbol: str,
    score: float,
    action: str = "WATCH",
    *,
    px: dict | None = None,
    signals: dict | None = None,
    extras: dict | None = None,
) -> Candidate:
    risk = RiskVerdict(
        action_label=action,
        max_portfolio_weight=0.15,
        warnings=[],
        invalidation_conditions=[],
        time_horizon="2-8 weeks",
    )
    out_extras: dict = {"px": px or {"last": 100.0, "atr14": 4.0,
                                      "p1d": 0.0, "p7d": 0.01,
                                      "p30d": 0.05,
                                      "high30": 110.0, "low30": 92.0,
                                      "high60": 115.0}}
    if extras:
        out_extras.update(extras)
    return Candidate(
        symbol=symbol,
        score=score,
        action=action,
        reason="x",
        signals=signals or {},
        risk=risk,
        extras=out_extras,
    )


# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------


def test_classify_btc_eth_are_core():
    assert classify("BTC-USD") == "CORE"
    assert classify("ETH-USD") == "CORE"


def test_classify_majors():
    for sym in ("SOL-USD", "BNB-USD", "XRP-USD", "ADA-USD"):
        assert classify(sym) == "MAJOR"


def test_classify_mid_cap():
    for sym in ("AVAX-USD", "DOT-USD", "LINK-USD", "MATIC-USD"):
        assert classify(sym) == "MID-CAP"


def test_classify_unknown_returns_higher_risk():
    assert classify("DOGE-USD") == "HIGHER-RISK"


# ---------------------------------------------------------------------------
# pick_decision
# ---------------------------------------------------------------------------


def test_decision_buy_now_when_score_high_no_chase():
    c = _candidate("ETH-USD", 70.0)
    assert pick_decision(c, []) == "BUY_NOW"


def test_decision_blocked_by_chase_trap():
    c = _candidate("SOL-USD", 70.0, px={"last": 100.0, "atr14": 4.0,
                                        "p7d": 0.30})  # +30% chase
    assert pick_decision(c, [], tag="chase trap") == "WAIT"


def test_decision_starter_with_positive_news():
    c = _candidate("SOL-USD", 58.0)
    assert pick_decision(c, [_Article("up only", 0.6)]) == "STARTER"


def test_decision_avoid_below_threshold():
    c = _candidate("LINK-USD", 30.0)
    assert pick_decision(c, []) == "AVOID"


def test_decision_avoid_on_negative_news():
    c = _candidate("BTC-USD", 60.0)
    assert pick_decision(c, [_Article("rug", -0.7)]) == "AVOID"


def test_decision_wait_default_neutral():
    c = _candidate("ADA-USD", 50.0)
    assert pick_decision(c, []) == "WAIT"


# ---------------------------------------------------------------------------
# pick_tag priority order
# ---------------------------------------------------------------------------


def test_tag_chase_trap_wins():
    c = _candidate("SOL-USD", 60.0, px={"last": 100.0, "atr14": 4.0, "p7d": 0.30})
    assert pick_tag(c, [_Article("ok", 0.6)]) == "chase trap"


def test_tag_breaking_positive():
    c = _candidate("ETH-USD", 60.0)
    assert pick_tag(c, [_Article("up only", 0.6)]) == "breaking positive"


def test_tag_breaking_negative():
    c = _candidate("BTC-USD", 60.0)
    assert pick_tag(c, [_Article("rug", -0.7)]) == "breaking negative"


def test_tag_material_event_for_neutral_news():
    c = _candidate("SOL-USD", 55.0)
    assert pick_tag(c, [_Article("update", 0.0)]) == "material event"


def test_tag_at_60d_peak():
    c = _candidate("XRP-USD", 55.0,
                   px={"last": 99.0, "atr14": 1.0, "p7d": 0.0,
                       "high60": 100.0})
    assert pick_tag(c, []) == "at 60d peak"


def test_tag_dip_minus_10():
    c = _candidate("ADA-USD", 50.0,
                   px={"last": 90.0, "atr14": 4.0, "p7d": -0.12,
                       "high30": 110.0, "low30": 85.0, "high60": 110.0})
    assert pick_tag(c, []) == "DIP -10% 5d"


def test_tag_oi_surge_when_flat_price():
    c = _candidate("DOT-USD", 55.0,
                   px={"last": 5.0, "atr14": 0.2, "p7d": 0.01},
                   extras={"oi_today": 1.25, "oi_7d_ago": 1.0})
    assert pick_tag(c, []) == "OI surge"


def test_tag_empty_when_nothing_fires():
    c = _candidate("ADA-USD", 50.0,
                   px={"last": 80.0, "atr14": 1.0, "p7d": 0.0,
                       "high30": 100.0, "low30": 75.0, "high60": 105.0})
    assert pick_tag(c, []) == ""


# ---------------------------------------------------------------------------
# build_decision: price targets
# ---------------------------------------------------------------------------


def test_price_targets_atr_based():
    c = _candidate("ETH-USD", 70.0,
                   px={"last": 100.0, "atr14": 5.0, "p7d": 0.0,
                       "high30": 110.0, "low30": 95.0, "high60": 115.0})
    d = build_decision(c, articles=[])
    assert d.buy_if_price == 100.0 - 0.8 * 5.0
    assert d.buy_zone == (100.0 - 0.5 * 5.0, 100.0 - 0.1 * 5.0)
    assert d.max_chase == 100.0 + 0.5 * 5.0
    assert d.sell_half_price == 100.0 + 1.0 * 5.0
    assert d.sell_quarter_price == 100.0 + 2.0 * 5.0
    assert d.stop_price == 100.0 - 1.5 * 5.0
    assert d.target_base == d.sell_half_price
    assert d.target_bull == d.sell_quarter_price


def test_price_targets_none_when_atr_missing():
    c = _candidate("ETH-USD", 70.0, px={"last": 100.0})
    d = build_decision(c, articles=[])
    assert d.buy_if_price is None
    assert d.buy_zone is None


# ---------------------------------------------------------------------------
# build_decision: sizing + review window
# ---------------------------------------------------------------------------


def test_buy_now_sizing_small_book():
    c = _candidate("ETH-USD", 70.0)
    d = build_decision(c, articles=[])
    assert d.decision == "BUY_NOW"
    assert d.suggested_size_usd == 1000.0


def test_buy_now_sizing_high_conviction():
    c = _candidate("BTC-USD", 82.0, action="STRONG")
    d = build_decision(c, articles=[])
    assert d.decision == "BUY_NOW"
    assert d.suggested_size_usd == 1500.0


def test_starter_sizing_500():
    c = _candidate("SOL-USD", 58.0)
    d = build_decision(c, articles=[_Article("ok", 0.6)])
    assert d.decision == "STARTER"
    assert d.suggested_size_usd == 500.0


def test_wait_decision_no_size():
    c = _candidate("ADA-USD", 50.0)
    d = build_decision(c, articles=[])
    assert d.decision == "WAIT"
    assert d.suggested_size_usd is None


def test_review_in_days_breaking_event():
    c = _candidate("ETH-USD", 70.0)
    d = build_decision(c, articles=[_Article("h", 0.7)])
    assert d.review_in_days == 5


def test_review_in_days_wait_default_14():
    c = _candidate("ADA-USD", 50.0)
    d = build_decision(c, articles=[])
    assert d.review_in_days == 14


# ---------------------------------------------------------------------------
# attach_decisions
# ---------------------------------------------------------------------------


def test_attach_decisions_writes_to_extras():
    candidates = [_candidate("BTC-USD", 70.0), _candidate("ADA-USD", 30.0)]
    attach_decisions(candidates, news_by_symbol={"BTC": [_Article("h", 0.6)]})
    assert "decision" in candidates[0].extras
    assert candidates[0].extras["decision"]["decision"] == "BUY_NOW"
    assert candidates[1].extras["decision"]["decision"] == "AVOID"


def test_value_bullets_have_real_data():
    cross = SignalResult(
        source="cross_asset", strength=0.5, label="BULLISH",
        bullets=[],
        details={"rel_strength_60d": 0.12},
    )
    c = _candidate("ETH-USD", 70.0, signals={"cross_asset": cross})
    d = build_decision(c, articles=[])
    assert any("Outperforming BTC by 12pt" in b for b in d.value_bullets)


def test_technical_summary_includes_rsi_and_macd():
    tech = SignalResult(
        source="technical", strength=-0.3, label="BEARISH",
        bullets=["MACD below signal and negative: bearish momentum"],
        details={"rsi14": 28.0, "macd": {"line": -1.0, "signal": -0.5}},
    )
    c = _candidate("SOL-USD", 60.0, signals={"technical": tech})
    d = build_decision(c, articles=[])
    assert "RSI 28" in d.technical_summary
    assert "MACD" in d.technical_summary


def test_decision_dict_round_trips():
    c = _candidate("ETH-USD", 70.0)
    d = build_decision(c, articles=[])
    payload = d.to_dict()
    assert payload["classification"] == "CORE"
    assert payload["decision"] == "BUY_NOW"
    assert isinstance(payload["value_bullets"], list)
    assert payload["buy_zone"] == [d.buy_zone[0], d.buy_zone[1]]


def test_buy_now_not_chase_with_recent_dip():
    """Negative-news dip is *not* a chase trap."""
    c = _candidate("SOL-USD", 70.0,
                   px={"last": 100.0, "atr14": 4.0, "p7d": -0.12,
                       "high30": 110.0, "low30": 90.0, "high60": 115.0})
    d = build_decision(c, articles=[_Article("outage", -0.6)])
    # Negative news triggers AVOID per spec.
    assert d.decision == "AVOID"
