"""Funding-rate signal.

Thesis: sustained extreme funding is contrarian. Longs paying shorts at
+0.05% per 8h for 24 hours indicates over-leveraged longs; forward returns
historically mean-revert. Reverse for negative funding.

Inputs come from CCXT (Binance perp, fallback Bybit). The data provider
is stubbed in v1; this evaluator returns NEUTRAL when funding info is
absent so callers do not need to handle missing data.
"""

from __future__ import annotations

from statistics import median

from . import LABEL_NO_DATA, SignalContext, SignalResult, label_from_strength

# Per-8h thresholds. 24h horizon = 3 funding prints.
BULL_THRESHOLD = -0.0003   # -0.03% per 8h
BEAR_THRESHOLD = 0.0005    # +0.05% per 8h
STRONG_MULTIPLIER = 2.0    # 2x threshold => strong


def evaluate(ctx: SignalContext) -> SignalResult:
    history = ctx.funding_rate_history
    latest = ctx.funding_rate

    # Missing data: NO_DATA so the renderer says "funding unavailable" rather
    # than implying we measured neutral funding.
    if not history and latest is None:
        return SignalResult(
            source="funding_rate",
            label=LABEL_NO_DATA,
            details={"reason": "no funding data (provider returned None)"},
        )

    # If we only have the most recent print, use it as a single sample.
    samples = list(history) if history else [latest]  # type: ignore[list-item]
    samples = [float(s) for s in samples if s is not None]
    if not samples:
        return SignalResult(
            source="funding_rate",
            label=LABEL_NO_DATA,
            details={"reason": "no usable funding samples"},
        )

    med = median(samples)
    most_recent = samples[-1]

    bullets: list[str] = []
    details = {
        "median_8h": round(med, 6),
        "most_recent_8h": round(most_recent, 6),
        "samples": len(samples),
    }
    strength = 0.0

    if med <= BULL_THRESHOLD * STRONG_MULTIPLIER:
        strength = 0.6
        bullets.append(f"Median funding {med * 100:.3f}% per 8h: strong negative (capitulation, contrarian long)")
    elif med <= BULL_THRESHOLD:
        strength = 0.3
        bullets.append(f"Median funding {med * 100:.3f}% per 8h: negative (mild contrarian long)")
    elif med >= BEAR_THRESHOLD * STRONG_MULTIPLIER:
        strength = -0.6
        bullets.append(f"Median funding {med * 100:.3f}% per 8h: strong positive (over-leveraged longs)")
    elif med >= BEAR_THRESHOLD:
        strength = -0.3
        bullets.append(f"Median funding {med * 100:.3f}% per 8h: positive (caution on longs)")

    return SignalResult(
        source="funding_rate",
        strength=strength,
        label=label_from_strength(strength),
        bullets=bullets,
        details=details,
    )
