"""Tests for the 0-100 weighted feature scorer."""

from __future__ import annotations

import pytest

from crypto_research_watchlist.scoring import (
    DEFAULT_WEIGHTS,
    aggregate_score,
    build_features,
    drawdown_feature,
    funding_feature,
    momentum_feature,
    rel_strength_feature,
    volatility_feature,
)

# ---- Per-feature isolation -------------------------------------------------

def test_momentum_feature_maps_neg_one_to_zero():
    assert momentum_feature(-1.0) == 0.0


def test_momentum_feature_maps_pos_one_to_hundred():
    assert momentum_feature(1.0) == 100.0


def test_momentum_feature_neutral_is_50():
    assert momentum_feature(0.0) == 50.0


def test_momentum_feature_none_returns_none():
    assert momentum_feature(None) is None


def test_volatility_feature_peaks_in_band():
    # 85% annualised vol = peak.
    peak = volatility_feature(0.85)
    too_quiet = volatility_feature(0.10)
    too_violent = volatility_feature(2.5)
    assert peak > too_quiet
    assert peak > too_violent
    assert peak == pytest.approx(100.0, abs=1.0)


def test_volatility_feature_extreme_caps_at_zero():
    assert volatility_feature(5.0) == 0.0


def test_rel_strength_feature_signed_mapping():
    assert rel_strength_feature(1.0) == 100.0
    assert rel_strength_feature(-1.0) == 0.0
    assert rel_strength_feature(0.0) == 50.0


def test_funding_feature_negative_is_bullish():
    bullish = funding_feature(-0.0008)
    bearish = funding_feature(0.0008)
    neutral = funding_feature(0.0)
    assert bullish > neutral > bearish


def test_funding_feature_extreme_saturates():
    sat = funding_feature(-0.05)
    # Saturates around 85.
    assert 80.0 <= sat <= 90.0


def test_drawdown_feature_no_dd_is_50():
    assert drawdown_feature(0.0) == 50.0


def test_drawdown_feature_dd_pulls_score_down():
    s10 = drawdown_feature(-0.10)
    s25 = drawdown_feature(-0.25)
    s40 = drawdown_feature(-0.40)
    assert s10 > s25 > s40
    assert 30.0 <= s10 <= 40.0


# ---- Aggregate + weights ---------------------------------------------------

def test_aggregate_returns_none_when_all_features_missing():
    feat = build_features(
        technical_strength=None,
        cross_asset_strength=None,
        funding_8h=None,
        annualised_vol=None,
        drawdown_30d=None,
    )
    assert aggregate_score(feat) is None


def test_aggregate_matches_hand_computed_value():
    """Manual calculation cross-check.

    momentum=80, volatility_regime=100, rel_strength=70, funding_signal=50,
    drawdown_penalty=50.

    Using DEFAULT_WEIGHTS (0.35, 0.20, 0.20, 0.10, 0.15) summing to 1.0:
        80*0.35 + 100*0.20 + 70*0.20 + 50*0.10 + 50*0.15
        = 28 + 20 + 14 + 5 + 7.5 = 74.5
    """
    feat = build_features(
        technical_strength=0.6,    # -> 80
        cross_asset_strength=0.4,  # -> 70
        funding_8h=0.0,            # -> 50
        annualised_vol=0.85,       # -> 100
        drawdown_30d=0.0,          # -> 50
    )
    out = aggregate_score(feat)
    assert out == pytest.approx(74.5, abs=0.5)


def test_aggregate_renormalises_when_features_missing():
    """When a feature is None its weight is excluded; the rest renormalise."""
    # Only momentum=80 and rel_strength=70. Weights 0.35 and 0.20 -> renorm
    # to 0.6364 and 0.3636, weighted average = 80*0.6364 + 70*0.3636 = 76.36.
    feat = build_features(
        technical_strength=0.6,    # -> 80
        cross_asset_strength=0.4,  # -> 70
        funding_8h=None,
        annualised_vol=None,
        drawdown_30d=None,
    )
    out = aggregate_score(feat)
    assert out == pytest.approx(76.36, abs=0.5)


def test_default_weights_sum_to_one():
    assert sum(DEFAULT_WEIGHTS.values()) == pytest.approx(1.0)
