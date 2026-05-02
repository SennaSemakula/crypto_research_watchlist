"""Feature-weighted 0-100 candidate scoring.

Mirrors the stock side's feature-weighted approach. Each feature is
normalised to a 0-100 float; the composite score is a weighted sum.
Weights live in ``config.yml -> scoring.weights``.

Features
--------
- ``momentum`` (default weight 0.35): rescaled technical signal strength.
  Maps the legacy [-1, +1] technical evaluator to [0, 100] with
  centre 50.
- ``volatility_regime`` (0.20): score peaks in the moderate-vol band
  (annualised 0.6 to 1.1, i.e. 60-110%). Penalises extremes — too quiet
  and there's no mean-reversion edge; too violent and the chase-trap
  fires regardless.
- ``rel_strength_vs_btc`` (0.20): from the cross-asset signal strength.
- ``funding_signal`` (0.10): contrarian. Extreme positive funding is
  bearish (low score); extreme negative funding is bullish (high).
- ``drawdown_penalty`` (0.15): inverted 30d drawdown, so a name in
  drawdown is penalised (score below 50).

Each feature lives in [0, 100]. A missing feature is reported as None
and excluded from the weighted sum (weights renormalised to the
present features). When no feature is computable the candidate reports
INSUFFICIENT_DATA upstream.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_WEIGHTS: dict[str, float] = {
    "momentum": 0.35,
    "volatility_regime": 0.20,
    "rel_strength_vs_btc": 0.20,
    "funding_signal": 0.10,
    "drawdown_penalty": 0.15,
}


@dataclass(slots=True)
class FeatureScores:
    momentum: float | None
    volatility_regime: float | None
    rel_strength_vs_btc: float | None
    funding_signal: float | None
    drawdown_penalty: float | None

    def to_dict(self) -> dict[str, float | None]:
        return {
            "momentum": self.momentum,
            "volatility_regime": self.volatility_regime,
            "rel_strength_vs_btc": self.rel_strength_vs_btc,
            "funding_signal": self.funding_signal,
            "drawdown_penalty": self.drawdown_penalty,
        }


# ---------------------------------------------------------------------------
# Feature builders. Each takes raw inputs and returns a 0-100 float (or None).
# ---------------------------------------------------------------------------


def _clip(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def momentum_feature(technical_strength: float | None) -> float | None:
    """Map technical [-1, +1] to [0, 100]. None when not computable."""
    if technical_strength is None:
        return None
    return _clip(50.0 + 50.0 * float(technical_strength))


def volatility_feature(annualised_vol: float | None) -> float | None:
    """Score peaks at ~85% annualised vol. Punishes extremes.

    Crypto's healthy mean-reversion window is roughly 60-110% annualised
    vol. Below 50% the asset is dormant; above 150% the chase-trap risk
    overwhelms the signal.
    """
    if annualised_vol is None:
        return None
    v = float(annualised_vol)
    # Peak at v=0.85, falling parabolically. Bandwidth = 0.7 (i.e. half-
    # height at 0.15 and 1.55).
    centre = 0.85
    bandwidth = 0.7
    delta = (v - centre) / bandwidth
    score = 100.0 * max(0.0, 1.0 - delta * delta)
    return _clip(score)


def rel_strength_feature(cross_asset_strength: float | None) -> float | None:
    """Map cross-asset signal [-1, +1] to [0, 100]."""
    if cross_asset_strength is None:
        return None
    return _clip(50.0 + 50.0 * float(cross_asset_strength))


def funding_feature(funding_8h: float | None) -> float | None:
    """Contrarian funding score.

    +0.05% per 8h is the bearish (over-leveraged) threshold. -0.03% is
    the bullish capitulation threshold. The mapping is monotonic
    (negative funding -> high score) and saturates beyond +/-0.10%.
    """
    if funding_8h is None:
        return None
    f = float(funding_8h)
    # Saturation band: -0.10% .. +0.10%.
    # f = -0.001 -> ~80, f = 0 -> 50, f = +0.001 -> ~20, f = +0.0005 -> 35.
    sat = 0.001
    pct = max(-1.0, min(1.0, -f / sat))
    return _clip(50.0 + 35.0 * pct)


def drawdown_feature(drawdown_30d: float | None) -> float | None:
    """Penalise drawdown.

    drawdown_30d is in [-1, 0] in fraction form (e.g. -0.20 = -20% off
    30d high). A 0% drawdown maps to 50. A -10% drawdown maps to 35; a
    -25% drawdown maps to 12.5; -40%+ saturates near 0.
    """
    if drawdown_30d is None:
        return None
    dd = float(drawdown_30d)
    # 0 -> 50; -0.40 -> 0; positive (rare, fresh ATH) caps at ~75.
    score = 50.0 + 1.5 * (dd * 100.0)  # dd=-0.10 -> 50 + 1.5*-10 = 35; dd=-0.40 -> 50-60=-10 -> clip 0.
    # Cap upward bias to 75 (recent ATH does NOT mean great score).
    return _clip(score, 0.0, 75.0)


def build_features(
    *,
    technical_strength: float | None,
    cross_asset_strength: float | None,
    funding_8h: float | None,
    annualised_vol: float | None,
    drawdown_30d: float | None,
) -> FeatureScores:
    return FeatureScores(
        momentum=momentum_feature(technical_strength),
        volatility_regime=volatility_feature(annualised_vol),
        rel_strength_vs_btc=rel_strength_feature(cross_asset_strength),
        funding_signal=funding_feature(funding_8h),
        drawdown_penalty=drawdown_feature(drawdown_30d),
    )


def aggregate_score(features: FeatureScores, weights: dict[str, float] | None = None) -> float | None:
    """Weighted aggregation. Returns None when every feature is None.

    Weights are renormalised to whatever subset of features is available.
    """
    weights = weights or DEFAULT_WEIGHTS
    feat_map = features.to_dict()
    total = 0.0
    weight_sum = 0.0
    for name, value in feat_map.items():
        if value is None:
            continue
        w = float(weights.get(name, 0.0))
        if w <= 0:
            continue
        total += w * float(value)
        weight_sum += w
    if weight_sum <= 0:
        return None
    return _clip(total / weight_sum)


def features_from_signals(
    signals: dict[str, Any],
    *,
    annualised_vol: float | None,
    drawdown_30d: float | None,
) -> FeatureScores:
    """Convenience: extract feature inputs from the SignalResult dict.

    Reads .strength on technical / cross_asset signals and the median 8h
    funding from the funding_rate signal's details (as written by
    signals/funding_rate.py).
    """
    def _strength(name: str) -> float | None:
        s = signals.get(name)
        if s is None:
            return None
        # Bullets present means the signal had data. Strength == 0 with
        # empty bullets typically means "no data".
        strength = getattr(s, "strength", 0.0)
        bullets = getattr(s, "bullets", []) or []
        details = getattr(s, "details", {}) or {}
        if not bullets and strength == 0.0 and ("error" in details or "reason" in details):
            return None
        return float(strength)

    funding_8h: float | None = None
    fr = signals.get("funding_rate")
    if fr is not None:
        details = getattr(fr, "details", {}) or {}
        # most_recent_8h is a single 8h print; median_8h is the 24h median.
        # Prefer the median as it's less noisy.
        if "median_8h" in details:
            try:
                funding_8h = float(details["median_8h"])
            except Exception:
                funding_8h = None
        elif "most_recent_8h" in details:
            try:
                funding_8h = float(details["most_recent_8h"])
            except Exception:
                funding_8h = None

    return build_features(
        technical_strength=_strength("technical"),
        cross_asset_strength=_strength("cross_asset"),
        funding_8h=funding_8h,
        annualised_vol=annualised_vol,
        drawdown_30d=drawdown_30d,
    )
