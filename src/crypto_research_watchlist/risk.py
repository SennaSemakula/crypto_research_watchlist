"""Risk filters and action labels.

Mirrors the stock side's risk.py: produces a RiskVerdict with action label,
position size cap, warnings, and invalidation conditions. Crypto-specific
adjustments documented in docs/RESEARCH.md (no leverage, drawdown gate,
stablecoin de-peg).
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import AppConfig

ACTION_LABELS = ["STRONG", "WATCH", "AVOID", "INSUFFICIENT_DATA"]


@dataclass(slots=True)
class RiskVerdict:
    action_label: str
    max_portfolio_weight: float
    warnings: list[str]
    invalidation_conditions: list[str]
    time_horizon: str


def classify(
    *,
    cfg: AppConfig,
    aggregate_strength: float,
    annualised_vol: float | None = None,
    drawdown_30d: float | None = None,
    portfolio_drawdown_30d: float | None = None,
    has_data: bool = True,
) -> RiskVerdict:
    """Produce a RiskVerdict from the aggregated signal strength + risk inputs.

    aggregate_strength is bounded in [-1, +1].
    annualised_vol is the symbol's realised vol (e.g. 1.0 = 100%).
    portfolio_drawdown_30d is the rolling 30d portfolio drawdown (e.g. -0.2 = -20%).
    """
    warnings: list[str] = []
    invalidations: list[str] = []

    if not has_data:
        return RiskVerdict("INSUFFICIENT_DATA", 0.0, ["Data unavailable"], ["Improve data coverage"], "n/a")

    risk = cfg.risk_limits
    if annualised_vol is not None and annualised_vol > risk.high_vol_threshold_annual:
        warnings.append(f"High realised vol ({annualised_vol:.0%} annualised): size accordingly")

    if drawdown_30d is not None and drawdown_30d <= -risk.review_drawdown_pct:
        warnings.append(f"30d drawdown {drawdown_30d * 100:.0f}%: review thesis before adding")

    drawdown_gate_tripped = (
        portfolio_drawdown_30d is not None
        and portfolio_drawdown_30d <= -0.15
    )
    if drawdown_gate_tripped:
        warnings.append("Portfolio drawdown gate: pause new entries")

    invalidations.append("BTC drops 10% intraday: reassess before adding")
    invalidations.append("Stablecoin de-peg (USDT/USDC outside 0.997-1.003): freeze entries")
    invalidations.append("Exchange listing change or regulatory action against the underlying")

    # Action label from aggregate strength + risk gates.
    if drawdown_gate_tripped:
        label = "AVOID"
    elif aggregate_strength >= 0.6:
        label = "STRONG"
    elif aggregate_strength >= 0.3:
        label = "WATCH"
    elif aggregate_strength <= -0.3:
        label = "AVOID"
    else:
        label = "WATCH"

    base_weight = risk.max_portfolio_weight_single_name
    # Down-size when warnings exist or vol is high.
    size_mult = 1.0
    if warnings:
        size_mult *= 0.6
    if annualised_vol is not None and annualised_vol > risk.high_vol_threshold_annual * 1.3:
        size_mult *= 0.5
    max_weight = round(base_weight * size_mult, 4)

    if aggregate_strength >= 0.6:
        horizon = "2-8 weeks"
    elif aggregate_strength >= 0.3:
        horizon = "1-4 weeks"
    else:
        horizon = "n/a"

    return RiskVerdict(
        action_label=label,
        max_portfolio_weight=max_weight,
        warnings=warnings,
        invalidation_conditions=invalidations,
        time_horizon=horizon,
    )
