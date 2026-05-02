"""Candidate generation: turn signals + risk into ranked recommendations.

A Candidate is a per-symbol record produced by one pipeline run. The
pipeline persists these to the candidates table and writes a markdown
summary.

Score is on a 0-100 scale post 2026-05 migration. Each candidate exposes
the per-feature breakdown via ``extras["features"]``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import AppConfig
from .risk import RiskVerdict, classify
from .scoring import aggregate_score, features_from_signals
from .signals import SignalResult


@dataclass(slots=True)
class Candidate:
    symbol: str
    score: float                             # 0-100 post-migration
    action: str                              # STRONG / WATCH / AVOID / INSUFFICIENT_DATA
    reason: str
    signals: dict[str, SignalResult] = field(default_factory=dict)
    risk: RiskVerdict | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def notable_signals(self) -> list[SignalResult]:
        return [s for s in self.signals.values() if s.is_notable]


def build_candidate(
    *,
    cfg: AppConfig,
    symbol: str,
    signals: dict[str, SignalResult],
    annualised_vol: float | None = None,
    drawdown_30d: float | None = None,
    portfolio_drawdown_30d: float | None = None,
    weights: dict[str, float] | None = None,
) -> Candidate:
    has_data = any(s.bullets for s in signals.values()) or any(
        s.details and "error" not in s.details for s in signals.values()
    )

    # Compute weighted feature scores (0-100). When all features are None,
    # aggregate_score returns None and we mark INSUFFICIENT_DATA.
    feature_scores = features_from_signals(
        signals, annualised_vol=annualised_vol, drawdown_30d=drawdown_30d,
    )

    # Resolve weights: explicit param > cfg.scoring.weights > defaults.
    if weights is None:
        try:
            w_obj = cfg.crypto.scoring.weights
            weights = {
                "momentum": w_obj.momentum,
                "volatility_regime": w_obj.volatility_regime,
                "rel_strength_vs_btc": w_obj.rel_strength_vs_btc,
                "funding_signal": w_obj.funding_signal,
                "drawdown_penalty": w_obj.drawdown_penalty,
            }
        except Exception:
            weights = None

    aggregate = aggregate_score(feature_scores, weights=weights)

    if aggregate is None:
        # INSUFFICIENT_DATA path: zero out signals contribution, give the
        # downstream classifier neutral aggregate, mark explicitly.
        aggregate = 50.0
        has_data = False

    verdict = classify(
        cfg=cfg,
        score=aggregate,
        annualised_vol=annualised_vol,
        drawdown_30d=drawdown_30d,
        portfolio_drawdown_30d=portfolio_drawdown_30d,
        has_data=has_data,
    )

    bullets: list[str] = []
    for s in sorted(signals.values(), key=lambda x: -abs(x.strength)):
        if not s.is_notable:
            continue
        for b in s.bullets[:1]:
            bullets.append(b)
        if len(bullets) >= 2:
            break
    reason = "; ".join(bullets) if bullets else "no notable signals"

    extras: dict[str, Any] = {"features": feature_scores.to_dict()}

    return Candidate(
        symbol=symbol,
        score=round(float(aggregate), 2),
        action=verdict.action_label,
        reason=reason,
        signals=signals,
        risk=verdict,
        extras=extras,
    )


def rank_candidates(candidates: list[Candidate]) -> list[Candidate]:
    """Sort by action priority then score. STRONG > WATCH > AVOID > INSUFFICIENT_DATA."""
    priority = {"STRONG": 0, "WATCH": 1, "AVOID": 2, "INSUFFICIENT_DATA": 3}
    return sorted(candidates, key=lambda c: (priority.get(c.action, 9), -c.score))
