"""Candidate generation: turn signals + risk into ranked recommendations.

A Candidate is a per-symbol record produced by one pipeline run. The
pipeline persists these to the candidates table and writes a markdown
summary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import AppConfig
from .risk import RiskVerdict, classify
from .signals import SignalResult, aggregate_strength


@dataclass(slots=True)
class Candidate:
    symbol: str
    score: float                             # in [-1, +1]
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
    score = aggregate_strength(signals, weights=weights)
    verdict = classify(
        cfg=cfg,
        aggregate_strength=score,
        annualised_vol=annualised_vol,
        drawdown_30d=drawdown_30d,
        portfolio_drawdown_30d=portfolio_drawdown_30d,
        has_data=has_data,
    )

    # Reason: top 1-2 bullets from notable signals.
    bullets: list[str] = []
    for s in sorted(signals.values(), key=lambda x: -abs(x.strength)):
        if not s.is_notable:
            continue
        for b in s.bullets[:1]:
            bullets.append(b)
        if len(bullets) >= 2:
            break
    reason = "; ".join(bullets) if bullets else "no notable signals"

    return Candidate(
        symbol=symbol,
        score=round(score, 4),
        action=verdict.action_label,
        reason=reason,
        signals=signals,
        risk=verdict,
    )


def rank_candidates(candidates: list[Candidate]) -> list[Candidate]:
    """Sort by action priority then score. STRONG > WATCH > AVOID > INSUFFICIENT_DATA."""
    priority = {"STRONG": 0, "WATCH": 1, "AVOID": 2, "INSUFFICIENT_DATA": 3}
    return sorted(candidates, key=lambda c: (priority.get(c.action, 9), -c.score))
