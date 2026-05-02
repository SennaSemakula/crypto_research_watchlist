"""Risk filters and action labels.

Mirrors the stock side's risk.py: produces a RiskVerdict with action label,
position size cap, warnings, and invalidation conditions. Crypto-specific
adjustments documented in docs/RESEARCH.md (no leverage, drawdown gate,
stablecoin de-peg).

Score is 0-100 post 2026-05 migration. Action thresholds come from
``cfg.crypto.scoring.thresholds``.
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
    score: float | None = None,
    annualised_vol: float | None = None,
    drawdown_30d: float | None = None,
    portfolio_drawdown_30d: float | None = None,
    has_data: bool = True,
    aggregate_strength: float | None = None,  # legacy [-1, +1] kw, kept for back-compat
) -> RiskVerdict:
    """Produce a RiskVerdict from the 0-100 score + risk inputs.

    Backward-compat: when called with ``aggregate_strength`` (legacy
    [-1, +1] convention, e.g. older tests), we auto-rescale to 0-100.
    Annual vol is fractional (1.0 = 100%); drawdown_30d is also
    fractional and negative (e.g. -0.20 = -20%).
    """
    warnings: list[str] = []
    invalidations: list[str] = []

    if not has_data:
        return RiskVerdict("INSUFFICIENT_DATA", 0.0, ["Data unavailable"], ["Improve data coverage"], "n/a")

    # Resolve score from either kw.
    if score is None and aggregate_strength is not None:
        # Legacy [-1, +1] -> [0, 100].
        score = float(aggregate_strength) * 50.0 + 50.0
    if score is None:
        score = 50.0
    score_100 = max(0.0, min(100.0, float(score)))

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

    # Read thresholds from config when available; fall back to defaults.
    try:
        thr = cfg.crypto.scoring.thresholds
        strong_thr = float(thr.strong)
        watch_thr = float(thr.watchlist)
        avoid_thr = float(thr.avoid)
    except Exception:
        strong_thr, watch_thr, avoid_thr = 72.0, 55.0, 40.0

    if drawdown_gate_tripped:
        label = "AVOID"
    elif score_100 >= strong_thr:
        label = "STRONG"
    elif score_100 >= watch_thr:
        label = "WATCH"
    elif score_100 < avoid_thr:
        label = "AVOID"
    else:
        label = "WATCH"

    base_weight = risk.max_portfolio_weight_single_name
    size_mult = 1.0
    if warnings:
        size_mult *= 0.6
    if annualised_vol is not None and annualised_vol > risk.high_vol_threshold_annual * 1.3:
        size_mult *= 0.5
    max_weight = round(base_weight * size_mult, 4)

    if score_100 >= strong_thr:
        horizon = "2-8 weeks"
    elif score_100 >= watch_thr:
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
